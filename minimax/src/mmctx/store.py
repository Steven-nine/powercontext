"""SeekDB-backed document store for the SDD context module.

The store keeps specification, source, and test documents in one embedded
seekdb database so the context module can retrieve the material a task needs
without scanning the whole repository.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

import pylibseekdb

DEFAULT_DB = ".data/seekdb"
DOC_GLOBS = {
    "spec": ("specs/**/*.md",),
    "code": ("src/**/*.py",),
    "test": ("tests/**/*.py",),
    "guide": ("AGENTS.md", "README.md"),
}
TEXT_SUFFIXES = {".md", ".py", ".txt", ".yaml", ".yml", ".toml"}


@dataclass(frozen=True)
class Doc:
    """One ingested repository document."""

    kind: str
    path: str
    title: str
    body: str
    digest: str


def sql_str(value: str) -> str:
    """Quotes a string literal for seekdb SQL statements."""

    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _title_for(path: Path, body: str) -> str:
    if path.suffix == ".py":
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith(("def ", "class ")):
                return stripped.rstrip(":")[:200]
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
        return stripped[:200]
    return path.name


def collect_docs(root: Path) -> list[Doc]:
    """Reads spec, source, and test documents under root."""

    docs: list[Doc] = []
    for kind, patterns in DOC_GLOBS.items():
        for pattern in patterns:
            for path in sorted(root.glob(pattern)):
                if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                    continue
                body = path.read_text(encoding="utf-8", errors="replace")
                rel = path.relative_to(root).as_posix()
                docs.append(
                    Doc(
                        kind=kind,
                        path=rel,
                        title=_title_for(path, body),
                        body=body,
                        digest=hashlib.sha256(body.encode()).hexdigest(),
                    )
                )
    return docs


class Store:
    """Embedded seekdb store with a full-text index over document bodies."""

    def __init__(self, db_dir: str | os.PathLike[str] = DEFAULT_DB) -> None:
        self.db_dir = str(db_dir)
        Path(self.db_dir).parent.mkdir(parents=True, exist_ok=True)
        pylibseekdb.open(self.db_dir)
        self._conn = pylibseekdb.connect(database="test", autocommit=True)
        self._cursor = self._conn.cursor()
        self._create_table()

    def _create_table(self) -> None:
        self._cursor.execute(
            "CREATE TABLE IF NOT EXISTS docs ("
            "id BIGINT AUTO_INCREMENT PRIMARY KEY, "
            "kind VARCHAR(16) NOT NULL, "
            "path VARCHAR(512) NOT NULL, "
            "title VARCHAR(512) NOT NULL, "
            "body LONGTEXT NOT NULL, "
            "digest VARCHAR(64) NOT NULL, "
            "UNIQUE KEY uk_path (path))"
        )
        try:
            self._cursor.execute("CREATE FULLTEXT INDEX ft_docs_body ON docs(body)")
        except Exception as exc:  # The index already existing is expected on reruns.
            message = str(exc).lower()
            if "exist" not in message and "duplicate" not in message and "1061" not in message:
                raise

    def replace_all(self, docs: list[Doc]) -> int:
        """Replaces the stored document set with the given documents."""

        self._cursor.execute("DELETE FROM docs")
        for doc in docs:
            self._cursor.execute(
                "INSERT INTO docs (kind, path, title, body, digest) VALUES (%s, %s, %s, %s, %s)"
                % (
                    sql_str(doc.kind),
                    sql_str(doc.path),
                    sql_str(doc.title),
                    sql_str(doc.body),
                    sql_str(doc.digest),
                )
            )
        return len(docs)

    def query(self, text: str, kind: str | None = None, limit: int = 5) -> list[dict]:
        """Searches documents by full-text match with a LIKE fallback."""

        terms = _terms(text)
        rows = self._match(terms, kind, limit)
        if not rows:
            rows = self._like(terms or [text], kind, limit)
        return [
            {
                "kind": row[0],
                "path": row[1],
                "title": row[2],
                "body": row[3],
                "score": float(row[4]) if row[4] is not None else 0.0,
            }
            for row in rows
        ]

    def _match(self, terms: list[str], kind: str | None, limit: int) -> list[tuple]:
        if not terms:
            return []
        expression = " ".join(terms)
        sql = (
            "SELECT kind, path, title, body, "
            "MATCH(body) AGAINST(%s IN NATURAL LANGUAGE MODE) AS score "
            "FROM docs WHERE MATCH(body) AGAINST(%s IN NATURAL LANGUAGE MODE)"
        ) % (sql_str(expression), sql_str(expression))
        if kind:
            sql += " AND kind = %s" % sql_str(kind)
        sql += " ORDER BY score DESC LIMIT %d" % limit
        try:
            self._cursor.execute(sql)
            return self._cursor.fetchall()
        except Exception:
            return []

    def _like(self, terms: list[str], kind: str | None, limit: int) -> list[tuple]:
        if not terms:
            return []
        clauses = []
        for term in terms:
            escaped = term.replace("%", "\\%").replace("_", "\\_")
            clauses.append("(body LIKE %s OR title LIKE %s)" % (sql_str("%" + escaped + "%"), sql_str("%" + escaped + "%")))
        sql = "SELECT kind, path, title, body, 0 FROM docs WHERE (" + " OR ".join(clauses) + ")"
        if kind:
            sql += " AND kind = %s" % sql_str(kind)
        sql += " LIMIT %d" % limit
        try:
            self._cursor.execute(sql)
            return self._cursor.fetchall()
        except Exception:
            return []

    def list_kind(self, kind: str, limit: int = 20) -> list[dict]:
        """Lists stored documents of one kind in path order."""

        self._cursor.execute(
            "SELECT kind, path, title, body, 0 FROM docs WHERE kind = %s ORDER BY path LIMIT %d"
            % (sql_str(kind), limit)
        )
        return [
            {"kind": row[0], "path": row[1], "title": row[2], "body": row[3], "score": 0.0}
            for row in self._cursor.fetchall()
        ]

    def close(self) -> None:
        """Releases the embedded seekdb instance."""

        self._conn.close()
        pylibseekdb.close()


def _terms(text: str) -> list[str]:
    return [term for term in re.findall(r"[A-Za-z0-9_]{2,}", text.lower()) if term not in {"the", "and", "for"}]
