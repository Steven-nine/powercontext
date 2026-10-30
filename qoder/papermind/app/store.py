"""seekdb 存储与混合检索层。

分工：seekdb 负责文档切片的向量索引、全文索引与结构化过滤，
`hybrid_search` 在库内完成向量 KNN 与全文匹配的并行召回，再用 RRF 融合。
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

import pyseekdb

from .config import settings
from .ingest import Chunk, ParsedDocument

log = logging.getLogger("papermind.store")


class StoreError(RuntimeError):
    """seekdb 不可用时抛出，带上可执行的排查提示。"""


class VectorStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._client = None
        self._docs = None
        self._chunks = None
        self._ef = None

    # ---------- 连接 ----------

    def _embedding_function(self):
        if self._ef is None:
            if settings.is_local_embedding:
                from .embedding import LocalHashEmbeddingFunction

                self._ef = LocalHashEmbeddingFunction(dimension=settings.local_embedding_dim)
                return self._ef
            if not settings.has_llm:
                raise StoreError(
                    "缺少 DASHSCOPE_API_KEY，无法调用通义向量模型。"
                    "请在 .env 中配置 Key，或设置 EMBEDDING_BACKEND=local 使用本地哈希向量。"
                )
            from pyseekdb.utils.embedding_functions import QwenEmbeddingFunction

            self._ef = QwenEmbeddingFunction(
                model_name=settings.embedding_model,
                api_key_env="DASHSCOPE_API_KEY",
                api_base=settings.dashscope_base_url,
                dimensions=settings.embedding_dim,
            )
        return self._ef

    def _make_client(self):
        if settings.seekdb_is_embedded:
            if settings.seekdb_path.startswith("/mnt/"):
                raise StoreError(
                    "嵌入式 seekdb 不能把数据目录放在 /mnt/ 下（Windows 挂载盘不支持其文件语义）。"
                    "请把 DATA_DIR / SEEKDB_PATH 指到 WSL 内的路径，例如 /home/<user>/.papermind/data；"
                    "或设置 SEEKDB_MODE=server 连接 Docker seekdb。"
                )
            self._ensure_database()
            return pyseekdb.Client(path=settings.seekdb_path, database=settings.seekdb_database)
        self._ensure_database()
        return pyseekdb.Client(
            host=settings.seekdb_host,
            port=settings.seekdb_port,
            database=settings.seekdb_database,
            user=settings.seekdb_user,
            password=settings.seekdb_password,
        )

    def _ensure_database(self) -> None:
        """首次使用时库可能还不存在：嵌入式用 AdminClient，服务端用 MySQL 协议建库。"""
        name = settings.seekdb_database
        if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", name):
            raise StoreError(f"非法的数据库名：{name}")

        if settings.seekdb_is_embedded:
            admin = pyseekdb.AdminClient(path=settings.seekdb_path)
            names = {getattr(db, "name", str(db)) for db in admin.list_databases()}
            if name not in names:
                admin.create_database(name)
            return

        import pymysql

        conn = pymysql.connect(
            host=settings.seekdb_host,
            port=settings.seekdb_port,
            user=settings.seekdb_user,
            password=settings.seekdb_password,
            charset="utf8mb4",
            connect_timeout=10,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}`")
            conn.commit()
        finally:
            conn.close()

    def client(self):
        with self._lock:
            if self._client is None:
                try:
                    self._client = self._make_client()
                except Exception as exc:  # noqa: BLE001
                    raise StoreError(f"连接 seekdb 失败（{settings.seekdb_mode}）：{exc}") from exc
            return self._client

    def _schema(self, ef):
        from pyseekdb import FulltextIndexConfig, HNSWConfiguration, Schema, VectorIndexConfig

        hnsw = HNSWConfiguration(dimension=settings.effective_embedding_dim, distance="cosine")
        return Schema(
            vector_index=VectorIndexConfig(hnsw=hnsw, embedding_function=ef),
            fulltext_index=FulltextIndexConfig(analyzer="ik"),
        )

    def _collection(self, name: str):
        client = self.client()
        return client.get_or_create_collection(name=name, schema=self._schema(self._embedding_function()))

    @staticmethod
    def _name(base: str) -> str:
        # 两套向量维度不同，用独立 collection 避免同一库内冲突。
        return f"{base}_local" if settings.is_local_embedding else base

    @property
    def docs(self):
        with self._lock:
            if self._docs is None:
                self._docs = self._collection(self._name(settings.doc_collection))
            return self._docs

    @property
    def chunks(self):
        with self._lock:
            if self._chunks is None:
                self._chunks = self._collection(self._name(settings.chunk_collection))
            return self._chunks

    def ensure(self) -> None:
        self.docs
        self.chunks

    # ---------- 写入 ----------

    def add_document(self, doc: ParsedDocument, chunks: list[Chunk]) -> int:
        if not chunks:
            raise StoreError("该文档没有可索引的正文内容。")
        doc_meta = {
            "doc_id": doc.doc_id,
            "title": doc.title,
            "file_name": doc.file_name,
            "source_type": doc.source_type,
            "year": doc.year,
            "tags": ",".join(doc.tags),
            "chunk_count": len(chunks),
            "summary": doc.summary,
        }
        doc_text = f"{doc.title}\n{' '.join(doc.tags)}\n{doc.summary}"
        with self._lock:
            self.docs.upsert(ids=doc.doc_id, documents=doc_text, metadatas=doc_meta)
            self.chunks.upsert(
                ids=[c.id for c in chunks],
                documents=[c.text for c in chunks],
                metadatas=[c.metadata for c in chunks],
            )
            self.chunks.refresh_index()
            self.docs.refresh_index()
        return len(chunks)

    def delete_document(self, doc_id: str) -> None:
        if ":" in doc_id or not doc_id:
            raise StoreError("非法的 doc_id")
        with self._lock:
            self.chunks.delete(where={"doc_id": {"$eq": doc_id}})
            self.docs.delete(ids=doc_id)
            self.chunks.refresh_index()

    # ---------- 读取 ----------

    def list_documents(self) -> list[dict]:
        with self._lock:
            res = self.docs.get(limit=500, include=["metadatas"])
        rows = []
        for meta in res.get("metadatas") or []:
            if meta:
                rows.append(dict(meta))
        rows.sort(key=lambda m: (m.get("title") or "").lower())
        return rows

    def stats(self) -> dict:
        with self._lock:
            return {
                "documents": self.docs.count(),
                "chunks": self.chunks.count(),
                "mode": settings.seekdb_mode,
                "collection": self._name(settings.chunk_collection),
                "dimension": settings.effective_embedding_dim,
                "embedding_backend": settings.embedding_backend,
            }

    # ---------- 检索 ----------

    def hybrid_search(
        self,
        question: str,
        keywords: str,
        where: dict | None = None,
        top_k: int | None = None,
        candidates: int | None = None,
    ) -> dict[str, Any]:
        top_k = top_k or settings.top_k
        candidates = candidates or settings.candidates
        with self._lock:
            fused = self.chunks.hybrid_search(
                query={
                    "where_document": {"$contains": keywords},
                    **({"where": where} if where else {}),
                    "n_results": candidates,
                },
                knn={
                    "query_texts": [question],
                    **({"where": where} if where else {}),
                    "n_results": candidates,
                },
                rank={"rrf": {"rank_window_size": 60, "rank_constant": 60}},
                n_results=top_k,
                include=["documents", "metadatas"],
            )
        return _rows(fused)

    def vector_search(
        self, question: str, where: dict | None = None, top_k: int = 5
    ) -> list[dict]:
        with self._lock:
            res = self.chunks.query(
                query_texts=[question],
                where=where,
                n_results=top_k,
                include=["documents", "metadatas"],
            )
        return _rows(res)

    def keyword_search(self, keywords: str, where: dict | None = None, top_k: int = 5) -> list[dict]:
        with self._lock:
            res = self.chunks.get(
                where_document={"$contains": keywords},
                where=where,
                limit=top_k,
                include=["documents", "metadatas"],
            )
        rows = []
        for i, chunk_id in enumerate(res.get("ids") or []):
            docs = res.get("documents") or []
            metas = res.get("metadatas") or []
            rows.append(
                {
                    "id": chunk_id,
                    "document": docs[i] if i < len(docs) else "",
                    "metadata": metas[i] if i < len(metas) else {},
                    "distance": None,
                }
            )
        return rows


def _rows(result: dict) -> list[dict]:
    ids = (result.get("ids") or [[]])[0] if result.get("ids") else []
    docs = (result.get("documents") or [[]])[0] if result.get("documents") else []
    metas = (result.get("metadatas") or [[]])[0] if result.get("metadatas") else []
    dists = (result.get("distances") or [[]])[0] if result.get("distances") else []
    rows = []
    for i, chunk_id in enumerate(ids):
        rows.append(
            {
                "id": chunk_id,
                "document": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
                "distance": dists[i] if i < len(dists) else None,
            }
        )
    return rows


store = VectorStore()
