#!/usr/bin/env python3
"""把《记忆剧场》的 Dify DSL 导入本地 Dify、发布，并生成应用 API Key。

流程全部走 Dify 官方 Console HTTP API（不依赖 Dify 的 Web 前端）：
    GET  /console/api/setup
    POST /console/api/setup                （首次初始化本地管理员）
    POST /console/api/login
    POST /console/api/apps/imports         （mode=yaml-content）
    POST /console/api/apps/imports/{id}/confirm
    POST /console/api/apps/{app_id}/workflows/publish
    GET  /console/api/apps/{app_id}/api-keys
    POST /console/api/apps/{app_id}/api-keys

用法：
    python3 scripts/configure-local.py --initialize \
        --dify-url http://127.0.0.1:5001 \
        --powercontext-url http://127.0.0.1:8124
"""

import argparse
import datetime as dt
import hashlib
import http.cookiejar
import json
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DSL_PATH = ROOT / "dsl" / "memory-theatre-workflow.yml"
RUNTIME_PATH = ROOT / ".local-runtime.json"
ENV_PATH = ROOT / ".env"
EVIDENCE_PATH = ROOT / "evidence" / "dify-import.json"


class Console:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/") + "/console/api"
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _csrf(self):
        for cookie in self.jar:
            if "csrf" in cookie.name.lower():
                return cookie.value
        return ""

    def call(self, method: str, path: str, payload=None):
        url = self.base + path
        headers = {"Content-Type": "application/json"}
        csrf = self._csrf()
        if csrf:
            headers["X-CSRF-Token"] = csrf
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=120) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", "replace")
            raise SystemExit(f"{method} {path}: HTTP {error.code}: {raw[:800]}") from error

    def setup_state(self):
        return self.call("GET", "/setup")

    def initialize(self, email, password, name):
        return self.call("POST", "/setup", {"email": email, "password": password, "name": name, "language": "zh-Hans"})

    def login(self, email, password):
        return self.call("POST", "/login", {"email": email, "password": password, "remember_me": True})

    def import_app(self, yaml_content, app_id=None):
        payload = {"mode": "yaml-content", "yaml_content": yaml_content}
        if app_id:
            payload["app_id"] = app_id
        return self.call("POST", "/apps/imports", payload)

    def confirm_import(self, import_id):
        return self.call("POST", f"/apps/imports/{import_id}/confirm", {})

    def publish(self, app_id):
        return self.call("POST", f"/apps/{app_id}/workflows/publish", {"marked_name": "theatre-verified"})

    def api_keys(self, app_id):
        return self.call("GET", f"/apps/{app_id}/api-keys")

    def create_api_key(self, app_id):
        return self.call("POST", f"/apps/{app_id}/api-keys", {})


def load_runtime():
    if RUNTIME_PATH.exists():
        return json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
    return {
        "email": "theatre@example.com",
        "password": "Theatre" + secrets.token_hex(16),
        "dify_version": "1.9.2",
    }


def patch_dsl(yaml_text: str, powercontext_url: str) -> str:
    """把 PowerContext 地址写进 DSL 的环境变量，导入后即可用。"""
    import yaml

    document = yaml.safe_load(yaml_text)
    for variable in document["workflow"]["environment_variables"]:
        if variable["name"] == "POWERCONTEXT_URL":
            variable["value"] = powercontext_url
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=4096)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dify-url", default="http://127.0.0.1:5001")
    parser.add_argument("--powercontext-url", default="http://127.0.0.1:8124")
    parser.add_argument("--initialize", action="store_true", help="首次运行时创建本地管理员")
    parser.add_argument("--dsl", default=str(DSL_PATH))
    args = parser.parse_args()

    runtime = load_runtime()
    console = Console(args.dify_url)

    state = console.setup_state()
    if state.get("step") == "not_started":
        if not args.initialize:
            raise SystemExit("这是一个全新的 Dify，请加 --initialize 以创建本地管理员")
        console.initialize(runtime["email"], runtime["password"], "记忆剧场")
    console.login(runtime["email"], runtime["password"])

    raw_dsl = Path(args.dsl).read_text(encoding="utf-8")
    patched = patch_dsl(raw_dsl, args.powercontext_url)

    app_id = runtime.get("app_id")
    imported = console.import_app(patched, app_id)
    if imported.get("status") == "pending":
        imported = console.confirm_import(imported["id"])
    app_id = imported.get("app_id") or app_id
    if not app_id:
        raise SystemExit(f"导入没有返回 app_id：{imported}")

    published = console.publish(app_id)

    keys = console.api_keys(app_id)
    token = ""
    if keys.get("data"):
        token = keys["data"][0].get("token", "")
    else:
        token = console.create_api_key(app_id).get("token", "")
    if not token:
        raise SystemExit("没有拿到应用 API Key")

    runtime["app_id"] = app_id
    RUNTIME_PATH.write_text(json.dumps(runtime, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    env_path = Path(ENV_PATH)
    env_path.write_text(
        "\n".join(
            [
                "DIFY_BASE_URL=" + args.dify_url,
                "DIFY_API_KEY=" + token,
                "DIFY_APP_ID=" + app_id,
                "POWERCONTEXT_URL=" + args.powercontext_url,
                "PORT=8787",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_path.chmod(0o600)

    evidence = {
        "checkedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "difyVersion": runtime.get("dify_version", "1.9.2"),
        "dslFile": Path(args.dsl).name,
        "dslSha256": hashlib.sha256(raw_dsl.encode("utf-8")).hexdigest(),
        "appId": app_id,
        "import": imported.get("status"),
        "publish": published.get("result"),
        "powercontextUrl": args.powercontext_url,
        "method": "真实 Dify Console HTTP API：imports -> confirm -> workflows/publish -> api-keys",
        "credentialsIncluded": False,
    }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    print("\n已写入 .env（DIFY_API_KEY 只保存在本地，不要提交）")


if __name__ == "__main__":
    sys.exit(main())
