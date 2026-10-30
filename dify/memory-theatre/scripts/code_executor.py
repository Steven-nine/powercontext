#!/usr/bin/env python3
"""最小 Code Executor —— 兼容 Dify 1.9.x 的 Code 节点执行协议。

为什么需要它：
    官方 ``langgenius/dify-sandbox:0.2.12`` 的 Python runner 是内嵌 CPython 的
    ``python.so``（带 seccomp 过滤器）。在 WSL2 内核上它连 ``import json`` 都会被
    拒绝（EPERM），于是 Dify 的 Code 节点报
    ``Not all output parameters are validated.``。
    本文件用标准库实现 Dify 需要的同一套协议，让《记忆剧场》的 Code 节点
    在 Linux / WSL2 / Windows 上都能跑通。

协议（Dify api/core/helper/code_executor/code_executor.py）：
    POST /v1/sandbox/run
    Header : X-Api-Key: <CODE_EXECUTION_API_KEY>
    Body   : {"language": "python3", "code": "<runner script>", "preload": "", "enable_network": true}
    Resp   : {"code": 0, "message": "success",
              "data": {"error": "", "stdout": "<<RESULT>>{...}<<RESULT>>"}}

Dify 发来的 ``code`` 已经把用户代码与 inputs（base64）拼好，并约定用
``<<RESULT>>...<<RESULT>>`` 包裹输出，所以这里只要如实执行并回传 stdout。

安全边界：
    * 只监听 127.0.0.1；
    * 需要正确的 X-Api-Key 才会执行；
    * 子进程有超时与地址空间限制（本机演示用，不要当成多租户沙箱）。
"""

import json
import os
import resource
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_KEY = os.environ.get("CODE_EXECUTION_API_KEY", "")
HOST = os.environ.get("CODE_EXECUTOR_HOST", "127.0.0.1")
PORT = int(os.environ.get("CODE_EXECUTOR_PORT", "8194"))
TIMEOUT = float(os.environ.get("CODE_EXECUTOR_TIMEOUT", "30"))
MEMORY_LIMIT_MB = int(os.environ.get("CODE_EXECUTOR_MEMORY_MB", "512"))

# 兼容旧版协议（inputs 直接作为参数传入）的最小 runner
LEGACY_RUNNER = """
import json, sys

_inputs = json.loads(sys.argv[1])
_result = main(**_inputs)
if not isinstance(_result, dict):
    raise TypeError('main() must return a dict, got %s' % type(_result).__name__)
print('<<RESULT>>' + json.dumps(_result, ensure_ascii=False, default=str) + '<<RESULT>>')
"""


def _limit():
    try:
        limit = MEMORY_LIMIT_MB * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ValueError, OSError):
        pass


def execute(script: str, legacy_inputs=None):
    """执行脚本，返回 (error, stdout)。"""
    with tempfile.TemporaryDirectory() as workdir:
        path = os.path.join(workdir, "snippet.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
            if legacy_inputs is not None:
                handle.write(LEGACY_RUNNER)
        argv = [sys.executable, "-I", path]
        if legacy_inputs is not None:
            argv.append(json.dumps(legacy_inputs, ensure_ascii=False))
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT,
                cwd=workdir,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                    "HOME": workdir,
                    "TMPDIR": workdir,
                },
                preexec_fn=_limit,
            )
        except subprocess.TimeoutExpired:
            return "error: code execution timed out after %ss\n" % TIMEOUT, ""
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if completed.returncode != 0:
            return "error: " + (stderr.strip() or "exit code %d" % completed.returncode) + "\n", stdout
        return "", stdout


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def _reply(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") in ("/health", ""):
            self._reply(200, {"status": "ok", "executor": "theatre-local"})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") != "/v1/sandbox/run":
            self._reply(404, {"error": "not found"})
            return
        if API_KEY and self.headers.get("X-Api-Key", "") != API_KEY:
            self._reply(401, {"error": "invalid api key"})
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            request = json.loads(raw.decode("utf-8") or "{}")
        except ValueError as error:
            self._reply(400, {"code": 400, "message": str(error), "data": None})
            return
        language = request.get("language", "python3")
        if language not in ("python3", "python"):
            self._reply(400, {"code": -400, "message": "unsupported language", "data": None})
            return
        script = request.get("code", "") or ""
        preload = request.get("preload", "") or ""
        legacy_inputs = request.get("inputs")
        print(
            "run language=%s legacy_inputs=%s" % (language, sorted(legacy_inputs.keys()) if isinstance(legacy_inputs, dict) else None),
            file=sys.stderr,
            flush=True,
        )
        if preload:
            script = preload + "\n" + script
        error, stdout = execute(script, legacy_inputs if isinstance(legacy_inputs, dict) else None)
        self._reply(200, {"code": 0, "message": "success", "data": {"error": error, "stdout": stdout}})


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print("code executor listening on http://%s:%d" % (HOST, PORT), flush=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        thread.join()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
