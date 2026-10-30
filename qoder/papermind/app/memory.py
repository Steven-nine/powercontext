"""PowerContext 长期记忆层。

分工：PowerContext 负责跨会话的记忆读写——用户的研究偏好、已确认结论、
阅读进展；每次提问前检索并注入上下文，回答后回写本轮结论。
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import httpx

from .config import settings

log = logging.getLogger("papermind.memory")

KIND_FACT = "fact"
KIND_PREFERENCE = "preference"
KIND_DECISION = "decision"
KIND_WORKING_NOTE = "working_note"


class PowerContextMemory:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cache_path = Path(settings.data_dir) / "scopes.json"
        self._scopes: dict[str, str] | None = None
        self.last_error: str | None = None

    # ---------- 基础 ----------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if settings.powercontext_token:
            headers["Authorization"] = f"Bearer {settings.powercontext_token}"
        return headers

    def _post(self, path: str, payload: dict, timeout: float = 15.0) -> dict:
        url = f"{settings.powercontext_url}{path}"
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    def _get(self, path: str, timeout: float = 10.0) -> dict:
        url = f"{settings.powercontext_url}{path}"
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    def available(self) -> bool:
        try:
            with httpx.Client(timeout=4.0) as client:
                resp = client.get(f"{settings.powercontext_url}/health/live")
                ok = resp.status_code == 200
            self.last_error = None if ok else f"HTTP {resp.status_code}"
            return ok
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            return False

    def status(self) -> dict:
        ok = self.available()
        return {
            "available": ok,
            "url": settings.powercontext_url,
            "error": self.last_error,
        }

    # ---------- Scope ----------

    def _load_cache(self) -> dict[str, str]:
        if self._scopes is None:
            try:
                self._scopes = json.loads(self._cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._scopes = {}
        return self._scopes

    def _save_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(
            json.dumps(self._scopes or {}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _scope_title(user_id: str) -> str:
        return f"{settings.powercontext_scope_prefix} · {user_id}"

    def ensure_scope(self, user_id: str) -> str:
        with self._lock:
            cache = self._load_cache()
            if user_id in cache:
                return cache[user_id]

            title = self._scope_title(user_id)
            scope_id = ""
            try:
                created = self._post(
                    "/v1/scopes",
                    {
                        "title": title,
                        "summary": "PaperMind 文献研读助手的长期记忆：研究偏好、结论与阅读进展。",
                        "idempotency_key": f"{settings.powercontext_scope_prefix}-{user_id}",
                    },
                )
                scope_id = created.get("scope_id", "")
            except httpx.HTTPError as exc:
                log.warning("创建 Scope 失败，尝试复用已有 Scope: %s", exc)

            if not scope_id:
                page = self._get("/v1/scopes")
                for item in page.get("items", []):
                    if item.get("title") == title:
                        scope_id = item.get("scope_id", "")
                        break
            if not scope_id:
                raise RuntimeError("PowerContext 中没有可用的 Scope，且创建失败。")

            cache[user_id] = scope_id
            self._save_cache()
            return scope_id

    # ---------- 读写记忆 ----------

    def remember(self, scope_id: str, kind: str, text: str, reason: str = "") -> list[dict]:
        text = text.strip()
        if not text:
            return []
        if len(text.encode("utf-8")) > 8000:
            text = text.encode("utf-8")[:8000].decode("utf-8", errors="ignore")
        payload = {"scope_id": scope_id, "kind": kind, "text": text}
        if reason:
            payload["reason"] = reason
        data = self._post("/v1/memory/remember", payload)
        records = data.get("records") or []
        return [
            {
                "artifact_id": (r.get("artifact") or {}).get("artifact_id", ""),
                "kind": r.get("kind", kind),
                "text": r.get("text", text),
                "state": r.get("state", "active"),
            }
            for r in records
        ]

    def search(self, scope_id: str, query: str, limit: int = 5) -> list[dict]:
        try:
            data = self._post(
                "/v1/atomic-memory/search",
                {"scope_id": scope_id, "query": query, "limit": limit, "mode": "text"},
            )
        except httpx.HTTPError as exc:
            log.warning("记忆检索失败: %s", exc)
            self.last_error = str(exc)
            return []
        hits = []
        for hit in data.get("hits") or []:
            mem = hit.get("memory") or {}
            hits.append(
                {
                    "kind": mem.get("kind", ""),
                    "text": mem.get("text", ""),
                    "score": hit.get("score"),
                    "matched_by": hit.get("matched_by", []),
                    "artifact_id": (mem.get("artifact") or {}).get("artifact_id", ""),
                }
            )
        return hits

    def preferences(self, scope_id: str, limit: int = 5) -> list[dict]:
        """长期偏好需要每轮都生效，不依赖本轮提问是否恰好命中相关词。"""
        try:
            data = self._post(
                "/v1/atomic-memory/list",
                {
                    "scope_id": scope_id,
                    "kind": KIND_PREFERENCE,
                    "states": ["active"],
                    "limit": limit,
                },
            )
        except httpx.HTTPError as exc:
            log.warning("读取偏好失败: %s", exc)
            return []
        rows = []
        seen: set[str] = set()
        for item in data.get("items") or []:
            mem = item.get("memory") if isinstance(item, dict) and "memory" in item else item
            if isinstance(mem, dict) and mem.get("kind") == KIND_PREFERENCE:
                text = mem.get("text", "")
                if not text or text in seen:
                    continue
                seen.add(text)
                rows.append(
                    {
                        "kind": KIND_PREFERENCE,
                        "text": text,
                        "artifact_id": (mem.get("artifact") or {}).get("artifact_id", ""),
                    }
                )
        return rows

    def prepare(self, scope_id: str, query: str, max_bytes: int = 3000) -> str:
        try:
            data = self._post(
                "/v1/context/prepare",
                {"scope_id": scope_id, "query": query, "max_bytes": max_bytes},
            )
        except httpx.HTTPError as exc:
            log.warning("准备上下文失败: %s", exc)
            self.last_error = str(exc)
            return ""
        if data.get("status") != "ready":
            return ""
        return data.get("content") or ""

    def list_memories(self, scope_id: str, limit: int = 50) -> list[dict]:
        try:
            data = self._post(
                "/v1/atomic-memory/list", {"scope_id": scope_id, "limit": limit}
            )
        except httpx.HTTPError as exc:
            log.warning("列出记忆失败: %s", exc)
            return []
        items = data.get("items") or data.get("memories") or data.get("records") or []
        rows = []
        for item in items:
            mem = item.get("memory") if isinstance(item, dict) and "memory" in item else item
            if not isinstance(mem, dict):
                continue
            rows.append(
                {
                    "kind": mem.get("kind", ""),
                    "text": mem.get("text", ""),
                    "state": mem.get("state", "active"),
                    "state_version": mem.get("state_version", 0),
                    "artifact_id": (mem.get("artifact") or {}).get("artifact_id", ""),
                }
            )
        return rows


memory = PowerContextMemory()
