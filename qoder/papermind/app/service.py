"""业务编排：导入资料、提问、记忆读写。"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from . import llm
from .config import settings
from .ingest import SUPPORTED, build_chunks, parse_document
from .memory import KIND_FACT, KIND_PREFERENCE, KIND_WORKING_NOTE, PowerContextMemory, memory
from .retrieval import extract_keywords, retrieve
from .store import store

log = logging.getLogger("papermind.service")

PREFERENCE_CUES = ("以后", "今后", "每次", "记住", "我都想", "我总是", "请始终", "from now on")


def _pc() -> PowerContextMemory:
    return memory


def ingest_path(path: Path, override: dict | None = None) -> dict:
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError(f"不支持的格式 {path.suffix}，目前支持：{', '.join(sorted(SUPPORTED))}")
    doc = parse_document(path)
    doc = _apply_overrides(doc, override or {})
    chunks = build_chunks(doc)
    count = store.add_document(doc, chunks)

    memory_note = ""
    if _pc().available():
        try:
            scope = _pc().ensure_scope("shared")
            _pc().remember(
                scope,
                KIND_FACT,
                f"资料库新增《{doc.title}》（{doc.source_type}"
                + (f"，{doc.year}" if doc.year else "")
                + f"），主题：{'、'.join(doc.tags) or '未标注'}。",
                reason="用户在 PaperMind 导入资料",
            )
            memory_note = "已写入 PowerContext"
        except Exception as exc:  # noqa: BLE001
            log.warning("写入导入记忆失败: %s", exc)
            memory_note = f"记忆写入失败：{exc}"

    return {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "source_type": doc.source_type,
        "year": doc.year,
        "tags": doc.tags,
        "chunks": count,
        "memory": memory_note,
    }


def ingest_text(title: str, text: str, override: dict | None = None) -> dict:
    safe = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", title).strip("_") or "note"
    virtual = Path(f"{safe}.md")
    content = text
    if not text.lstrip().startswith("---"):
        meta_lines = [f"title: {title}"]
        if override:
            for key in ("type", "year", "tags"):
                if override.get(key):
                    meta_lines.append(f"{key}: {override[key]}")
        content = "---\n" + "\n".join(meta_lines) + "\n---\n\n" + text

    doc_dir = settings.upload_dir
    doc_dir.mkdir(parents=True, exist_ok=True)
    path = doc_dir / f"{safe}.md"
    path.write_text(content, encoding="utf-8")
    return ingest_path(path, override)


def _apply_overrides(doc, override: dict):
    if override.get("title"):
        doc.title = override["title"]
    if override.get("type"):
        doc.source_type = override["type"]
    if override.get("year"):
        try:
            doc.year = int(override["year"])
        except (TypeError, ValueError):
            pass
    tags = override.get("tags")
    if tags:
        doc.tags = [t.strip() for t in re.split(r"[,，;；]", tags) if t.strip()]
    return doc


def save_upload(filename: str, data: bytes, override: dict | None = None) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"不支持的格式 {suffix}，目前支持：{', '.join(sorted(SUPPORTED))}")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    target = settings.upload_dir / Path(filename).name
    target.write_bytes(data)
    return ingest_path(target, override)


def _detect_preference(question: str) -> str | None:
    if any(cue in question for cue in PREFERENCE_CUES) and len(question) <= 200:
        return question.strip()
    match = re.match(r"^\s*(记住|请记住)[:：\s]+(.+)$", question)
    if match:
        return match.group(2).strip()
    return None


def ask(user_id: str, question: str, filters: dict | None = None) -> dict:
    question = question.strip()
    if not question:
        raise ValueError("问题不能为空")

    pc_ok = _pc().available()
    scope_id = ""
    memory_hits: list[dict] = []
    preferences: list[dict] = []
    prepared = ""
    memory_error = ""
    keywords = extract_keywords(question)

    if pc_ok:
        try:
            scope_id = _pc().ensure_scope(user_id)
            # PowerContext 的文本记忆检索按词项匹配，传关键词比整句更稳。
            preferences = _pc().preferences(scope_id)
            memory_hits = _pc().search(scope_id, keywords, limit=5)
            prepared = _pc().prepare(scope_id, keywords, max_bytes=3000)
        except Exception as exc:  # noqa: BLE001
            memory_error = str(exc)
            log.warning("记忆流程失败: %s", exc)
    else:
        memory_error = _pc().last_error or "PowerContext 未启动"

    memory_context = _render_memory(preferences, prepared, memory_hits)
    retrieval = retrieve(question, filters, keywords=keywords)
    answer_text = llm.answer(question, retrieval["citations"], memory_context)

    written: list[dict] = []
    if pc_ok and scope_id:
        try:
            note = llm.summarize_for_memory(question, answer_text, retrieval["citations"])
            written.extend(
                _pc().remember(scope_id, KIND_WORKING_NOTE, note, reason="PaperMind 自动记录本轮研读进展")
            )
            preference = _detect_preference(question)
            if preference:
                written.extend(
                    _pc().remember(
                        scope_id, KIND_PREFERENCE, preference, reason="用户表达的长期偏好"
                    )
                )
        except Exception as exc:  # noqa: BLE001
            memory_error = str(exc)
            log.warning("写入记忆失败: %s", exc)

    return {
        "answer": answer_text,
        "citations": retrieval["citations"],
        "trace": retrieval["trace"],
        "memory": {
            "enabled": pc_ok,
            "scope_id": scope_id,
            "preferences": preferences,
            "hits": memory_hits,
            "prepared_context": prepared,
            "memory_context": memory_context,
            "written": written,
            "error": memory_error,
        },
    }


def _render_memory(preferences: list[dict], prepared: str, hits: list[dict]) -> str:
    blocks = []
    if preferences:
        lines = "\n".join(f"- {p['text']}" for p in preferences[:5])
        blocks.append(f"【用户长期偏好】\n{lines}")
    if prepared:
        blocks.append(prepared)
    elif hits:
        blocks.append(_render_hits(hits))
    return "\n\n".join(blocks)


def _render_hits(hits: list[dict]) -> str:
    if not hits:
        return ""
    return "\n".join(f"- ({h['kind']}) {h['text']}" for h in hits[:5])
