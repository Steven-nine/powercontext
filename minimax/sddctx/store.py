"""seekdb / OceanBase 资料库。

本模块负责把工程资料（规格、代码、测试）以及检索索引写入数据库，
并提供基于倒排索引 + BM25 的检索能力。数据库既是**存储**也是**检索**的承担者：
检索结果直接决定开发上下文中出现哪些规格条目、哪些代码符号、哪些测试。
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import pymysql
from pymysql.cursors import DictCursor

#: 分词用的停用词（中英文）。
STOPWORDS = frozenset(
    """
    的 了 和 是 在 有 与 及 或 对 从 到 为 以 按 等 中 上 下 个 这 那 该 其 之
    并 但 而 则 使 让 把 被 该 并 也 都 就 还 很 更 最 不 没 无 未 已 已
    a an the of to in on for and or is are be by with as at from that this it its
    """.split()
)

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+(?:\.[0-9]+)?|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """把文本切成检索词。

    英文按标识符切分并额外产出小写形式；中文按字切分（单字召回 + 规格编号精确匹配）。
    """

    tokens: list[str] = []
    for match in _TOKEN_RE.findall(text or ""):
        lowered = match.lower()
        if lowered in STOPWORDS:
            continue
        tokens.append(lowered)
        if match[0].isalpha() and len(match) > 1:
            # 驼峰与下划线标识符额外拆分，便于 "shipping_fee" -> "shipping" "fee"
            for part in re.split(r"_", match):
                part = part.lower()
                if part and part != lowered and part not in STOPWORDS:
                    tokens.append(part)
    return tokens


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


@dataclass
class DocRecord:
    """一份被导入数据库的资料。"""

    doc_id: str
    kind: str
    path: str
    title: str
    content: str
    version: str = ""
    symbols: list["SymbolRecord"] = field(default_factory=list)
    spec_entries: list["SpecEntryRecord"] = field(default_factory=list)


@dataclass
class SymbolRecord:
    """代码中的一个符号（函数 / 类 / 方法）。"""

    symbol_id: str
    name: str
    kind: str
    signature: str
    line_start: int
    line_end: int
    content: str
    docstring: str = ""
    cited_specs: str = ""


@dataclass
class SpecEntryRecord:
    """规格文件中的一条 ``SPEC-XXX-NNN`` 条目。"""

    entry_id: str
    title: str
    body: str


SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS sdd_doc (
        doc_id         VARCHAR(128)  NOT NULL,
        kind           VARCHAR(32)   NOT NULL,
        path           VARCHAR(512)  NOT NULL,
        title          VARCHAR(255)  NOT NULL,
        version        VARCHAR(64)   NOT NULL DEFAULT '',
        content        MEDIUMTEXT    NOT NULL,
        revision       INT           NOT NULL DEFAULT 1,
        content_sha256 CHAR(64)      NOT NULL,
        updated_at     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (doc_id),
        KEY idx_sdd_doc_kind (kind)
    ) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS sdd_doc_revision (
        doc_id         VARCHAR(128) NOT NULL,
        revision       INT          NOT NULL,
        content_sha256 CHAR(64)     NOT NULL,
        version        VARCHAR(64)  NOT NULL DEFAULT '',
        recorded_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (doc_id, revision)
    ) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS sdd_spec_entry (
        entry_id   VARCHAR(128) NOT NULL,
        doc_id     VARCHAR(128) NOT NULL,
        title      VARCHAR(255) NOT NULL,
        body       MEDIUMTEXT   NOT NULL,
        revision   INT          NOT NULL DEFAULT 1,
        updated_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (entry_id)
    ) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS sdd_symbol (
        symbol_id    VARCHAR(255) NOT NULL,
        doc_id       VARCHAR(128) NOT NULL,
        name         VARCHAR(255) NOT NULL,
        kind         VARCHAR(32)  NOT NULL,
        signature    VARCHAR(512) NOT NULL DEFAULT '',
        line_start   INT          NOT NULL DEFAULT 0,
        line_end     INT          NOT NULL DEFAULT 0,
        content      MEDIUMTEXT   NOT NULL,
        cited_specs  VARCHAR(255) NOT NULL DEFAULT '',
        updated_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (symbol_id)
    ) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS sdd_term (
        term   VARCHAR(96)  NOT NULL,
        doc_id VARCHAR(128) NOT NULL,
        field  VARCHAR(32)  NOT NULL,
        tf     INT          NOT NULL,
        PRIMARY KEY (term, doc_id, field),
        KEY idx_sdd_term_doc (doc_id)
    ) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin
    """,
)


class MaterialStore:
    """工程资料库（seekdb / OceanBase）。"""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.query_log: list[dict[str, Any]] = []

    # ---------------------------------------------------------------- 连接

    def connect(self, *, with_database: bool = True) -> pymysql.connections.Connection:
        kwargs: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "charset": "utf8mb4",
            "cursorclass": DictCursor,
            "autocommit": True,
        }
        if with_database:
            kwargs["database"] = self.database
        return pymysql.connect(**kwargs)

    def _execute(self, cursor, sql: str, params: Sequence[Any] = ()) -> int:
        if params and isinstance(params[0], (tuple, list)):
            cursor.executemany(sql, params)
        else:
            cursor.execute(sql, params)
        return cursor.rowcount

    def ensure_schema(self) -> None:
        """创建数据库与表结构（幂等）。"""

        with self.connect(with_database=False) as conn, conn.cursor() as cursor:
            self._execute(
                cursor,
                f"CREATE DATABASE IF NOT EXISTS `{self.database}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin",
            )
        with self.connect() as conn, conn.cursor() as cursor:
            for statement in SCHEMA_STATEMENTS:
                self._execute(cursor, statement)

    def reset(self) -> None:
        """清空全部资料与索引（验证样例的"重置方法"）。"""

        with self.connect() as conn, conn.cursor() as cursor:
            for table in ("sdd_term", "sdd_symbol", "sdd_spec_entry", "sdd_doc_revision", "sdd_doc"):
                self._execute(cursor, f"DELETE FROM {table}")

    # ---------------------------------------------------------------- 写入

    def upsert_doc(self, doc: DocRecord) -> int:
        """写入（或更新）一份资料，返回修订号。

        同一 ``doc_id`` 再次导入时修订号 +1，并把历史修订写入 ``sdd_doc_revision``，
        因此"规格更新后重新导入"可以被观察和核对。
        """

        digest = sha256_text(doc.content)
        with self.connect() as conn, conn.cursor() as cursor:
            self._execute(
                cursor,
                "SELECT revision, content_sha256 FROM sdd_doc WHERE doc_id = %s",
                (doc.doc_id,),
            )
            row = cursor.fetchone()
            revision = 1
            if row is None:
                self._execute(
                    cursor,
                    "INSERT INTO sdd_doc (doc_id, kind, path, title, version, content, revision, content_sha256)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        doc.doc_id,
                        doc.kind,
                        doc.path,
                        doc.title,
                        doc.version,
                        doc.content,
                        revision,
                        digest,
                    ),
                )
            else:
                revision = int(row["revision"])
                if row["content_sha256"] == digest:
                    # 内容未变，只刷新元数据，不产生新修订。
                    self._execute(
                        cursor,
                        "UPDATE sdd_doc SET kind=%s, path=%s, title=%s, version=%s WHERE doc_id=%s",
                        (doc.kind, doc.path, doc.title, doc.version, doc.doc_id),
                    )
                    return revision
                revision += 1
                self._execute(
                    cursor,
                    "UPDATE sdd_doc SET kind=%s, path=%s, title=%s, version=%s, content=%s,"
                    " revision=%s, content_sha256=%s WHERE doc_id=%s",
                    (
                        doc.kind,
                        doc.path,
                        doc.title,
                        doc.version,
                        doc.content,
                        revision,
                        digest,
                        doc.doc_id,
                    ),
                )
            self._execute(
                cursor,
                "INSERT INTO sdd_doc_revision (doc_id, revision, content_sha256, version)"
                " VALUES (%s, %s, %s, %s)"
                " ON DUPLICATE KEY UPDATE content_sha256=VALUES(content_sha256), version=VALUES(version)",
                (doc.doc_id, revision, digest, doc.version),
            )
            self._execute(cursor, "DELETE FROM sdd_term WHERE doc_id = %s", (doc.doc_id,))
            self._execute(cursor, "DELETE FROM sdd_symbol WHERE doc_id = %s", (doc.doc_id,))
            self._execute(cursor, "DELETE FROM sdd_spec_entry WHERE doc_id = %s", (doc.doc_id,))
            for symbol in doc.symbols:
                self._execute(
                    cursor,
                    "INSERT INTO sdd_symbol (symbol_id, doc_id, name, kind, signature, line_start, line_end, content, cited_specs)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    " ON DUPLICATE KEY UPDATE name=VALUES(name), kind=VALUES(kind), signature=VALUES(signature),"
                    " line_start=VALUES(line_start), line_end=VALUES(line_end), content=VALUES(content),"
                    " cited_specs=VALUES(cited_specs)",
                    (
                        symbol.symbol_id,
                        doc.doc_id,
                        symbol.name,
                        symbol.kind,
                        symbol.signature,
                        symbol.line_start,
                        symbol.line_end,
                        symbol.content,
                        symbol.cited_specs,
                    ),
                )
            for entry in doc.spec_entries:
                self._execute(
                    cursor,
                    "INSERT INTO sdd_spec_entry (entry_id, doc_id, title, body, revision)"
                    " VALUES (%s, %s, %s, %s, %s)"
                    " ON DUPLICATE KEY UPDATE title=VALUES(title), body=VALUES(body), revision=VALUES(revision)",
                    (entry.entry_id, doc.doc_id, entry.title, entry.body, revision),
                )
            self._index_document(cursor, doc, revision)
        return revision

    def _index_document(self, cursor, doc: DocRecord, revision: int) -> None:
        """把文档写入倒排索引 ``sdd_term``。"""

        term_counts: dict[tuple[str, str], int] = {}

        def add(field_name: str, text: str) -> None:
            for token in tokenize(text):
                key = (token, field_name)
                term_counts[key] = term_counts.get(key, 0) + 1

        add(doc.kind, doc.title)
        add(doc.kind, doc.path)
        add(doc.kind, doc.content)

        for symbol in doc.symbols:
            add("symbol", symbol.name)
            add("symbol", symbol.docstring)
            add("symbol", symbol.signature)

        for entry in doc.spec_entries:
            add("spec_entry", entry.entry_id)
            add("spec_entry", entry.title)
            add("spec_entry", entry.body)

        rows = [(term, doc.doc_id, field_name, tf) for (term, field_name), tf in term_counts.items()]
        if rows:
            self._execute(
                cursor,
                "INSERT INTO sdd_term (term, doc_id, field, tf) VALUES (%s, %s, %s, %s)"
                " ON DUPLICATE KEY UPDATE tf = tf + VALUES(tf)",
                rows,
            )

    # ---------------------------------------------------------------- 检索

    def search(
        self,
        query: str,
        *,
        kinds: Iterable[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """BM25 检索：倒排索引命中 + 文档频次统计，全部在数据库中完成。"""

        tokens = tokenize(query)
        if not tokens:
            return []
        unique = sorted(set(tokens))
        placeholders = ", ".join(["%s"] * len(unique))

        with self.connect() as conn, conn.cursor() as cursor:
            kind_clause = ""
            params: list[Any] = list(unique)
            if kinds:
                kind_clause = " AND d.kind IN (" + ", ".join(["%s"] * len(list(kinds))) + ")"
                params.extend(list(kinds))
            self._execute(
                cursor,
                "SELECT t.term, t.doc_id, t.field, t.tf FROM sdd_term t"
                " JOIN sdd_doc d ON d.doc_id = t.doc_id"
                f" WHERE t.term IN ({placeholders}){kind_clause}",
                params,
            )
            hits = cursor.fetchall()

            self._execute(
                cursor,
                f"SELECT term, COUNT(DISTINCT doc_id) AS df FROM sdd_term WHERE term IN ({placeholders}) GROUP BY term",
                list(unique),
            )
            df_rows = cursor.fetchall()

            self._execute(cursor, "SELECT COUNT(*) AS n FROM sdd_doc")
            total_docs = int(cursor.fetchone()["n"])
            self._execute(cursor, "SELECT doc_id, kind, path, title, version, revision, content FROM sdd_doc")
            docs = {row["doc_id"]: row for row in cursor.fetchall()}

            self._execute(cursor, "SELECT entry_id, doc_id, title, body, revision FROM sdd_spec_entry")
            entries = {row["entry_id"]: row for row in cursor.fetchall()}

            self._execute(
                cursor,
                "SELECT symbol_id, doc_id, name, kind, signature, line_start, line_end, content, cited_specs"
                " FROM sdd_symbol",
            )
            symbols = cursor.fetchall()

        df_map = {row["term"]: int(row["df"]) for row in df_rows}
        doc_len = {doc_id: max(len(tokenize(row["content"])), 1) for doc_id, row in docs.items()}
        avg_len = max(sum(doc_len.values()) / max(len(doc_len), 1), 1.0)

        field_weight = {"spec": 2.0, "spec_entry": 3.0, "symbol": 2.0, "code": 1.0, "test": 1.0}

        scores: dict[tuple[str, str], float] = {}
        matched: dict[tuple[str, str], set[str]] = {}
        for hit in hits:
            term = hit["term"]
            df = max(df_map.get(term, 1), 1)
            idf = max(0.05, math.log(1.0 + (total_docs - df + 0.5) / (df + 0.5)))
            length_norm = 1.0 - 0.75 + 0.75 * (doc_len.get(hit["doc_id"], 1) / avg_len)
            base = idf * (int(hit["tf"]) * 2.2) / (int(hit["tf"]) + 1.2 * length_norm)
            key = (hit["doc_id"], hit["field"])
            scores[key] = scores.get(key, 0.0) + base * field_weight.get(hit["field"], 1.0)
            matched.setdefault(key, set()).add(term)

        # 规格条目：条目自身的得分加上所属文档的得分。
        entry_scores: dict[str, float] = {}
        for entry_id, entry in entries.items():
            doc_id = entry["doc_id"]
            doc_score = scores.get((doc_id, "spec"), 0.0) + scores.get((doc_id, "spec_entry"), 0.0)
            terms = set(tokenize(f"{entry['entry_id']} {entry['title']} {entry['body']}"))
            exact = 1.0 if entry_id.lower() in query.lower() else 0.0
            entry_scores[entry_id] = doc_score + exact * 50.0 + 0.05 * len(terms & set(tokenize(query)))

        results: list[dict[str, Any]] = []
        for (doc_id, field_name), score in scores.items():
            doc = docs.get(doc_id)
            if doc is None:
                continue
            results.append(
                {
                    "kind": doc["kind"],
                    "path": doc["path"],
                    "title": doc["title"],
                    "version": doc["version"],
                    "revision": int(doc["revision"]),
                    "doc_id": doc_id,
                    "field": field_name,
                    "score": round(score, 4),
                    "matched_terms": sorted(matched.get((doc_id, field_name), set())),
                }
            )
        results.sort(key=lambda item: item["score"], reverse=True)
        results = results[:limit]

        spec_entries = [
            {
                "entry_id": entry_id,
                "title": entries[entry_id]["title"],
                "body": entries[entry_id]["body"],
                "doc_id": entries[entry_id]["doc_id"],
                "path": docs[entries[entry_id]["doc_id"]]["path"],
                "version": docs[entries[entry_id]["doc_id"]]["version"],
                "revision": int(entries[entry_id]["revision"]),
                "score": round(entry_scores[entry_id], 4),
            }
            for entry_id in sorted(entry_scores, key=lambda key: entry_scores[key], reverse=True)
        ][:limit]

        return {
            "documents": results,
            "spec_entries": spec_entries,
            "symbols": [
                {
                    "symbol_id": row["symbol_id"],
                    "name": row["name"],
                    "kind": row["kind"],
                    "signature": row["signature"],
                    "line_start": int(row["line_start"]),
                    "line_end": int(row["line_end"]),
                    "path": docs[row["doc_id"]]["path"] if row["doc_id"] in docs else "",
                    "content": row["content"],
                    "cited_specs": row["cited_specs"],
                }
                for row in symbols
            ],
        }

    def describe(self) -> dict[str, Any]:
        """返回资料库统计信息（用于运行说明与使用记录）。"""

        with self.connect() as conn, conn.cursor() as cursor:
            stats: dict[str, Any] = {}
            for table in ("sdd_doc", "sdd_spec_entry", "sdd_symbol", "sdd_term", "sdd_doc_revision"):
                self._execute(cursor, f"SELECT COUNT(*) AS n FROM {table}")
                stats[table] = int(cursor.fetchone()["n"])
            self._execute(
                cursor,
                "SELECT doc_id, kind, path, version, revision, content_sha256, updated_at"
                " FROM sdd_doc ORDER BY kind, path",
            )
            stats["documents"] = cursor.fetchall()
        return stats


def relative_path(path: Path, root: Path) -> str:
    """返回相对 ``root`` 的 POSIX 风格路径（写入数据库的稳定标识）。"""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()
