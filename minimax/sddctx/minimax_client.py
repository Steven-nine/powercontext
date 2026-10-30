"""MiniMax（OpenAI 兼容接口）客户端。

接入方式：HTTP API，直接调用 ``POST {base_url}/chat/completions``，
默认 ``base_url = https://api.minimax.cn/v1``（中国大陆站），
模型默认 ``MiniMax-M3.1-Flash``。

每一次调用都会写入 JSONL 开发记录（请求、响应、usage、response id），
用于核对"MiniMax 实际参与了本次代码修改"。
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import requests

#: 可重试的错误码（限流 / 超时 / 服务端繁忙）。
RETRYABLE_CODES = {1000, 1001, 1002, 1013, 1024, 1033, 2064, 2066}


class MiniMaxError(RuntimeError):
    """MiniMax API 调用失败。"""

    def __init__(self, code: Any, message: str, http_status: int | None = None, request_id: str | None = None):
        super().__init__(f"MiniMax error {code}: {message} (http={http_status}, request_id={request_id})")
        self.code = code
        self.message = message
        self.http_status = http_status
        self.request_id = request_id


@dataclass
class ChatResult:
    """一次对话补全的结果。"""

    content: str
    reasoning: str = ""
    model: str = ""
    response_id: str = ""
    finish_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "model": self.model,
            "response_id": self.response_id,
            "finish_reason": self.finish_reason,
            "usage": self.usage,
        }


class MiniMaxClient:
    """MiniMax 文本生成客户端。"""

    def __init__(
        self,
        *,
        base_url: str = "https://api.minimax.cn/v1",
        api_key: str = "",
        model: str = "MiniMax-M3.1-Flash",
        max_completion_tokens: int = 32768,
        reasoning_effort: str = "",
        timeout: int = 900,
        retries: int = 3,
        log_path: Path | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self.model = model
        self.max_completion_tokens = max_completion_tokens
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        self.retries = retries
        self.log_path = Path(log_path) if log_path else None
        self._call_seq = 0

    # ------------------------------------------------------------------ 内部

    def _endpoint(self) -> str:
        base = self.base_url
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _next_call_id(self) -> str:
        self._call_seq += 1
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"call-{stamp}-{self._call_seq:03d}"

    def _write_log(self, payload: dict[str, Any]) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ 公共

    def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        system: str = "",
        max_completion_tokens: int | None = None,
    ) -> ChatResult:
        """发送一次对话补全请求。"""

        if not self.api_key:
            raise MiniMaxError("MISSING_CREDENTIAL", "MINIMAX_API_KEY is not set")

        payload_messages: list[dict[str, Any]] = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(dict(message) for message in messages)

        body: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
            "stream": False,
            "max_completion_tokens": int(max_completion_tokens or self.max_completion_tokens),
        }
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = self._endpoint()
        call_id = self._next_call_id()

        last_error: MiniMaxError | None = None
        for attempt in range(self.retries + 1):
            try:
                response = requests.post(url, headers=headers, json=body, timeout=self.timeout)
            except requests.RequestException as exc:  # pragma: no cover - 网络异常
                last_error = MiniMaxError("network", str(exc))
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 20))
                    continue
                raise last_error

            try:
                data = response.json()
            except ValueError:
                data = {}

            base_resp = data.get("base_resp") or {}
            if response.status_code == 200 and base_resp.get("status_code", 0) == 0:
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                result = ChatResult(
                    content=message.get("content") or "",
                    reasoning=message.get("reasoning_content") or "",
                    model=data.get("model", self.model),
                    response_id=data.get("id", ""),
                    finish_reason=choice.get("finish_reason", ""),
                    usage=dict(data.get("usage") or {}),
                    call_id=call_id,
                )
                self._write_log(
                    {
                        "call_id": call_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "endpoint": url,
                        "request": {"model": body["model"], "messages": payload_messages},
                        "response": {
                            "content": result.content,
                            "reasoning": result.reasoning,
                            "model": result.model,
                            "response_id": result.response_id,
                            "finish_reason": result.finish_reason,
                            "usage": result.usage,
                        },
                    }
                )
                return result

            error = data.get("error") or {}
            message_text = error.get("message") or base_resp.get("status_msg") or response.text[:300]
            match = re.search(r"\((\d{3,5})\)", message_text)
            code: Any = base_resp.get("status_code")
            if code is None and match:
                code = int(match.group(1))
            elif code is None:
                code = response.status_code
            last_error = MiniMaxError(code, message_text, response.status_code, data.get("request_id"))

            retryable = response.status_code in (429, 500, 502, 503, 504) or code in RETRYABLE_CODES
            if not retryable:
                break
            if attempt < self.retries:
                time.sleep(min(2**attempt, 20))

        self._write_log(
            {
                "call_id": call_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "endpoint": url,
                "request": {"model": body["model"], "messages": payload_messages},
                "response": {"error": str(last_error)},
            }
        )
        raise last_error or MiniMaxError("unknown", "MiniMax request failed")
