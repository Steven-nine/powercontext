"""Minimal PowerContext REST client used for task-state persistence.

The client talks to a running PowerContext Server. Explicit memory entries keep
the demo independent of inference models while still proving that task state is
stored outside the context module process and can be read after a restart.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8000"
SCOPE_TITLE = "minimax-sdd-demo"
SCOPE_SUMMARY = "Spec-driven context demo for the MiniMax ecosystem track."
STATE_KIND = "task-state"


class PowerContextError(RuntimeError):
    """Raised when the PowerContext Server rejects a request."""


class PowerContextClient:
    """Thin JSON client for the PowerContext Server v1 API."""

    def __init__(self, base_url: str = DEFAULT_URL, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise PowerContextError(f"{method} {path} failed: {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise PowerContextError(f"PowerContext Server unreachable: {exc.reason}") from exc

    def ensure_scope(self) -> str:
        """Returns the demo scope id, creating the scope on first use."""

        listing = self._request("GET", "/v1/scopes")
        scopes = listing.get("scopes", listing) if isinstance(listing, dict) else listing
        if isinstance(scopes, list):
            for scope in scopes:
                if isinstance(scope, dict) and scope.get("title") == SCOPE_TITLE:
                    return str(scope["scope_id"])
        created = self._request(
            "POST",
            "/v1/scopes",
            {
                "title": SCOPE_TITLE,
                "summary": SCOPE_SUMMARY,
                "idempotency_key": "minimax-sdd-demo-v1",
            },
        )
        return str(created["scope_id"])

    def remember(self, text: str, kind: str = STATE_KIND, reason: str | None = None) -> dict:
        """Stores one explicit memory entry in the demo scope."""

        scope_id = self.ensure_scope()
        return self._request(
            "POST",
            "/v1/memory/remember",
            {"scope_id": scope_id, "kind": kind, "text": text, "reason": reason},
        )

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Searches active memory entries in the demo scope."""

        scope_id = self.ensure_scope()
        result = self._request(
            "POST",
            "/v1/memory/search",
            {"scope_id": scope_id, "query": query, "limit": limit},
        )
        return list(result.get("hits", []))

    def save_state(self, state: dict) -> None:
        """Persists one task-state record as JSON text."""

        self.remember(json.dumps(state, ensure_ascii=False), reason="context module state")

    def load_state(self, query: str = "task state") -> list[dict]:
        """Loads stored task-state records that match the query."""

        states: list[dict] = []
        for hit in self.search(query, limit=10):
            text = hit.get("text", "")
            try:
                states.append(json.loads(text))
            except json.JSONDecodeError:
                continue
        return states
