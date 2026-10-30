"""检索编排：关键词抽取、结构化过滤条件、混合检索与通道诊断。"""

from __future__ import annotations

import logging
import re
import threading

from .config import settings
from .store import store

log = logging.getLogger("papermind.retrieval")

STOPWORDS = {
    "的", "了", "是", "在", "和", "与", "及", "或", "我", "你", "他", "她", "它",
    "这", "那", "有", "没有", "什么", "怎么", "如何", "为什么", "哪些", "哪个",
    "可以", "能否", "请", "一下", "关于", "一个", "以及", "对于", "进行", "是否",
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for",
    "and", "or", "what", "how", "why", "which", "that", "this", "with", "about",
    "please", "can", "could", "do", "does", "did", "me", "my", "we", "our",
}

_jieba_lock = threading.Lock()
_jieba = None


def _tokenize(text: str) -> list[str]:
    global _jieba
    with _jieba_lock:
        if _jieba is None:
            import jieba

            jieba.setLogLevel(logging.WARNING)
            _jieba = jieba
        return list(_jieba.cut(text))


def extract_keywords(question: str, limit: int = 8) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", question.lower())
    tokens = []
    for token in _tokenize(text):
        token = token.strip()
        if len(token) < 2 or token in STOPWORDS:
            continue
        if re.fullmatch(r"\d+", token):
            continue
        if token not in tokens:
            tokens.append(token)
    return " ".join(tokens[:limit]) or question.strip()


def build_where(filters: dict | None) -> dict | None:
    if not filters:
        return None
    where: dict = {}
    if (source_type := filters.get("source_type")) and source_type != "all":
        where["source_type"] = {"$eq": source_type}
    if (year_from := filters.get("year_from")):
        where["year"] = {"$gte": int(year_from)}
    return where or None


def _citation(row: dict, order: int) -> dict:
    meta = row.get("metadata") or {}
    return {
        "n": order,
        "chunk_id": row.get("id", ""),
        "doc_id": meta.get("doc_id", ""),
        "title": meta.get("title", "未命名"),
        "section": meta.get("section", ""),
        "page": meta.get("page", 0),
        "source_type": meta.get("source_type", ""),
        "year": meta.get("year", 0),
        "snippet": (row.get("document") or "")[:320],
        "score": row.get("distance"),
    }


def retrieve(question: str, filters: dict | None = None, keywords: str | None = None) -> dict:
    keywords = keywords or extract_keywords(question)
    where = build_where(filters)

    fused = store.hybrid_search(question, keywords, where=where)
    citations = [_citation(row, i + 1) for i, row in enumerate(fused)]

    vector_hits = store.vector_search(question, where=where, top_k=5)
    keyword_hits = store.keyword_search(keywords, where=where, top_k=5)

    trace = {
        "keywords": keywords,
        "filter": where or {},
        "mode": "hybrid_search · vector KNN + fulltext (IK) + RRF",
        "candidates_per_route": settings.candidates,
        "fused": [
            {
                "n": c["n"],
                "title": c["title"],
                "section": c["section"],
                "doc_id": c["doc_id"],
                "score": c["score"],
            }
            for c in citations
        ],
        "vector_route": [
            {
                "title": (r.get("metadata") or {}).get("title", ""),
                "section": (r.get("metadata") or {}).get("section", ""),
                "doc_id": (r.get("metadata") or {}).get("doc_id", ""),
                "distance": r.get("distance"),
            }
            for r in vector_hits
        ],
        "fulltext_route": [
            {
                "title": (r.get("metadata") or {}).get("title", ""),
                "section": (r.get("metadata") or {}).get("section", ""),
                "doc_id": (r.get("metadata") or {}).get("doc_id", ""),
            }
            for r in keyword_hits
        ],
    }
    return {"keywords": keywords, "where": where, "citations": citations, "trace": trace}
