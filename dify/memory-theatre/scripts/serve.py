#!/usr/bin/env python3
"""《记忆剧场》的网页入口：静态页面 + 极薄的 Dify 调用代理（仅标准库）。

    python3 scripts/serve.py        # 默认 http://127.0.0.1:8787

代理只做三件事：
  * GET  /            -> ui/index.html
  * GET  /api/health  -> Dify 与 PowerContext 的连通性
  * POST /api/turn    -> 调用 Dify 的 POST /v1/workflows/run

Dify 的应用 API Key 只保存在服务端 .env，不会下发给浏览器。
"""

import datetime as dt
import json
import os
import pathlib
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"
ENV_PATH = ROOT / ".env"

CHANNELS = ("surreal", "mystery", "cyber")


def load_env():
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


ENV = load_env()
DIFY_BASE = ENV.get("DIFY_BASE_URL", "http://127.0.0.1:5001").rstrip("/")
DIFY_KEY = ENV.get("DIFY_API_KEY", "")
PC_URL = ENV.get("POWERCONTEXT_URL", "http://127.0.0.1:8124").rstrip("/")
PORT = int(ENV.get("PORT", "8787"))


def http_json(method, url, payload=None, headers=None, timeout=180):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, {"error": raw[:600]}
    except Exception as error:  # noqa: BLE001
        return 0, {"error": str(error)}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003
        print("%s - %s" % (self.address_string(), fmt % args))

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, (UI_DIR / "index.html").read_text(encoding="utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/health":
            dify_status, dify_body = http_json("GET", DIFY_BASE + "/console/api/setup", timeout=10)
            pc_status, pc_body = http_json("GET", PC_URL + "/health/ready", timeout=10)
            self._send(
                200,
                json.dumps(
                    {
                        "ok": bool(DIFY_KEY) and dify_status == 200 and pc_status == 200,
                        "dify": {"configured": bool(DIFY_KEY), "status": dify_status, "step": dify_body.get("step")},
                        "powerContext": {"url": PC_URL, "status": pc_status},
                        "checkedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    },
                    ensure_ascii=False,
                ),
            )
            return
        self._send(404, json.dumps({"error": "not found"}, ensure_ascii=False))

    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/api/turn":
            self._send(404, json.dumps({"error": "not found"}, ensure_ascii=False))
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            self._send(400, json.dumps({"error": "请求体不是合法 JSON"}, ensure_ascii=False))
            return
        message = str(payload.get("message", "")).strip()
        player_id = str(payload.get("playerId", "")).strip()
        player_name = str(payload.get("playerName", "")).strip()[:40] or "旅人"
        channel = str(payload.get("channel", "surreal")).strip()
        if channel not in CHANNELS:
            channel = "surreal"
        if not message or len(message) > 1000:
            self._send(400, json.dumps({"error": "请写 1–1000 个字的动作"}, ensure_ascii=False))
            return
        if not player_id or len(player_id) > 120:
            self._send(400, json.dumps({"error": "缺少玩家标识"}, ensure_ascii=False))
            return
        if not DIFY_KEY:
            self._send(503, json.dumps({"error": "还没有配置 Dify 应用 API Key，请先运行 scripts/configure-local.py"}, ensure_ascii=False))
            return
        status, body = http_json(
            "POST",
            DIFY_BASE + "/v1/workflows/run",
            {
                "inputs": {
                    "player_id": player_id,
                    "player_name": player_name,
                    "action": message,
                    "channel": channel,
                },
                "response_mode": "blocking",
                "user": player_id,
            },
            headers={"Authorization": "Bearer " + DIFY_KEY},
        )
        if status != 200:
            self._send(502, json.dumps({"error": "Dify 运行失败", "detail": body}, ensure_ascii=False))
            return
        data = body.get("data", {})
        if data.get("status") != "succeeded":
            self._send(502, json.dumps({"error": "工作流没有成功", "detail": body}, ensure_ascii=False))
            return
        outputs = data.get("outputs", {})
        receipt = outputs.get("receipt")
        if isinstance(receipt, str):
            try:
                receipt = json.loads(receipt)
            except ValueError:
                receipt = {"raw": receipt}
        self._send(
            200,
            json.dumps(
                {
                    "answer": outputs.get("answer", ""),
                    "receipt": receipt,
                    "runId": body.get("workflow_run_id"),
                    "elapsedSeconds": data.get("elapsed_time"),
                },
                ensure_ascii=False,
            ),
        )


def main():
    if not (UI_DIR / "index.html").exists():
        raise SystemExit("找不到 ui/index.html")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    print("《记忆剧场》已启动： http://127.0.0.1:%d" % PORT, flush=True)
    print("Dify: %s   PowerContext: %s" % (DIFY_BASE, PC_URL), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
