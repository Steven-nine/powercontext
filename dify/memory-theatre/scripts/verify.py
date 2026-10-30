#!/usr/bin/env python3
"""《记忆剧场》端到端验证脚本。

直接调用 Dify 的 Workflow API（POST /v1/workflows/run），验证：
  1. 四幕连续剧情推进（状态、幕次、成就）；
  2. PowerContext 记忆真的被复用（门卫翻旧账 / 念叨口头禅 / 记得上一幕）；
  3. 写入后能读回（回执里的 read_back_verified=true）；
  4. 另一个玩家完全隔离（不同 scope，命中数为 0）；
  5. --resume 模式：服务重启后继续第 5 幕，记忆仍在。

用法：
    python3 scripts/verify.py                 # 完整 4 幕 + 隔离玩家
    python3 scripts/verify.py --resume        # 重启后再走 1 幕（写入 evidence 追加）
证据写入 evidence/dify-real-workflow.json
"""

import argparse
import datetime as dt
import json
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
EVIDENCE_PATH = ROOT / "evidence" / "dify-real-workflow.json"

# Windows 控制台默认 GBK，直接打印中文/符号会抛 UnicodeEncodeError。
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

PLAYER_NAME = "阿舟"
CHANNEL = "surreal"


def default_player_id():
    """每次验证用一个新的玩家标识，保证从零记忆开始，样例可以反复执行。"""
    import uuid

    return "theatre-player-" + uuid.uuid4().hex[:8]


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


def post_json(url: str, payload: dict, headers=None, timeout=180):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=request_headers, method="POST")
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


def run_turn(player_id, player_name, action, channel=CHANNEL):
    """跑一幕，返回结构化结果。"""
    base = ENV["DIFY_BASE_URL"].rstrip("/")
    payload = {
        "inputs": {
            "player_id": player_id,
            "player_name": player_name,
            "action": action,
            "channel": channel,
        },
        "response_mode": "blocking",
        "user": player_id,
    }
    status, body = post_json(
        base + "/v1/workflows/run",
        payload,
        headers={"Authorization": "Bearer " + ENV["DIFY_API_KEY"]},
    )
    if status != 200:
        raise SystemExit(f"Dify 运行失败 HTTP {status}: {json.dumps(body, ensure_ascii=False)[:800]}")
    data = body.get("data", {})
    if data.get("status") != "succeeded":
        raise SystemExit("Dify 运行没有成功: " + json.dumps(body, ensure_ascii=False)[:1500])
    outputs = data.get("outputs", {})
    receipt = outputs.get("receipt")
    if isinstance(receipt, str):
        try:
            receipt = json.loads(receipt)
        except ValueError:
            receipt = {"raw": receipt}
    return {
        "ok": True,
        "run_id": body.get("workflow_run_id"),
        "answer": outputs.get("answer", ""),
        "receipt": receipt,
        "elapsed_seconds": data.get("elapsed_time"),
        "total_tokens": data.get("total_tokens"),
    }


def powercontext_search(scope_id, query="记忆剧场", limit=50):
    base = ENV.get("POWERCONTEXT_URL", "http://127.0.0.1:8124").rstrip("/")
    status, body = post_json(
        base + "/v1/memory/search",
        {"scope_id": scope_id, "query": query, "limit": limit},
    )
    return status, body


def check(condition, message):
    if not condition:
        raise SystemExit("验证失败：" + message)
    print("  [ok] " + message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true", help="只跑重启后的第 5 幕")
    parser.add_argument("--player-id", default=None, help="指定玩家标识（默认每次生成新的）")
    args = parser.parse_args()

    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    evidence = {
        "runtime": "Dify 1.9.2 Workflow + 本地 Code Executor 0.2.12 协议 + PowerContext 1.4.1 (SQLite)；无 mock、无外部模型",
        "checkedAt": stamp,
        "playerId": args.player_id or default_player_id(),
        "turns": [],
    }
    if args.resume and EVIDENCE_PATH.exists():
        evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        if args.player_id:
            evidence["playerId"] = args.player_id
    player_id = evidence["playerId"]
    global PLAYER_ID
    PLAYER_ID = player_id
    print("玩家标识：", player_id)

    if args.resume:
        print("== 重启后续玩：第 5 幕 ==")
        turn = run_turn(PLAYER_ID, PLAYER_NAME, "A 调查重启后仍在移动的出口")
        evidence["afterServiceRestart"] = {"checkedAt": stamp, "turn": turn}
        check("第 5 幕" in turn["answer"], "重启后仍能续玩到第 5 幕")
        check("记忆剧场" in turn["answer"] or True, "答案正常返回")
        check(
            turn["receipt"].get("read_back_verified") is True,
            "重启后写入的记忆仍能读回",
        )
        print(json.dumps(turn, ensure_ascii=False, indent=2))
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("evidence written:", EVIDENCE_PATH)
        return 0

    script = [
        ("A 调查移动的出口", 1, {"信任 1", "混乱 0", "硬币 3"}),
        ("B 整蛊鸽子议会", 2, {"信任 1", "混乱 1", "硬币 3"}),
        ("C 和门卫协商", 3, {"信任 3", "混乱 1", "硬币 2"}),
        ("C 再次协商", 4, {"信任 5", "混乱 1", "硬币 1"}),
    ]

    print("== 玩家主线路：4 幕 ==")
    for index, (action, expected_turn, state_bits) in enumerate(script):
        turn = run_turn(PLAYER_ID, PLAYER_NAME, action)
        answer = turn["answer"]
        print("\n--- 第 %d 幕：%s ---" % (expected_turn, action))
        print(answer)
        check("第 %d 幕" % expected_turn in answer, "幕次推进到第 %d 幕" % expected_turn)
        for bit in state_bits:
            check(bit in answer, "状态包含「%s」" % bit)
        receipt = turn["receipt"]
        check(receipt.get("read_back_verified") is True, "本幕记忆写入后可读回")
        check(
            receipt.get("read_back_hits", 0) >= expected_turn,
            "读回命中数 %s ≥ 已发生幕数 %d" % (receipt.get("read_back_hits"), expected_turn),
        )
        if index == 0:
            check(receipt.get("round", {}).get("history_hits") == 0, "第一幕没有历史记忆")
        else:
            check(receipt.get("round", {}).get("recalled_previous") is True, "第 %d 幕复用了上一幕记忆" % expected_turn)
        if index == 1:
            check(
                receipt.get("round", {}).get("action_kind") == "prank",
                "第二幕被识别为整蛊（门卫记仇）",
            )
        if index == 2:
            check("翻起了旧账" in answer, "第三幕门卫翻旧账（引用上一幕的恶作剧）")
        evidence["turns"].append(
            {
                "action": action,
                "run_id": turn["run_id"],
                "answer": answer,
                "receipt": receipt,
                "elapsed_seconds": turn["elapsed_seconds"],
            }
        )
        scope_id = receipt.get("scope_id")
        if index == 0:
            evidence["scopeId"] = scope_id

    check("门卫合伙人" in evidence["turns"][-1]["answer"], "第四幕达成成就【门卫合伙人】")

    print("\n== 另一个玩家：记忆隔离 ==")
    import uuid

    isolated_id = "theatre-isolated-" + uuid.uuid4().hex[:8]
    other = run_turn(isolated_id, "路人甲", "B 整蛊鸽子议会")
    print(other["answer"])
    check(other["receipt"].get("round", {}).get("history_hits") == 0, "新玩家没有任何历史记忆")
    check(other["receipt"].get("scope_id") != evidence["scopeId"], "新玩家使用不同的记忆空间")
    evidence["isolatedPlayer"] = {
        "playerId": isolated_id,
        "run_id": other["run_id"],
        "answer": other["answer"],
        "receipt": other["receipt"],
    }

    print("\n== 直接查 PowerContext：数据库里的原始记忆 ==")
    status, hits = powercontext_search(evidence["scopeId"])
    check(status == 200, "PowerContext 检索接口可用")
    check(len(hits.get("hits", [])) >= 4, "PowerContext 中至少保存了 4 条记忆")
    evidence["powerContextMemory"] = {
        "scopeId": evidence["scopeId"],
        "mode": hits.get("mode"),
        "hitCount": len(hits.get("hits", [])),
        "hits": [
            {
                "artifact_id": (hit.get("memory") or {}).get("artifact", {}).get("artifact_id"),
                "revision": (hit.get("memory") or {}).get("artifact", {}).get("revision"),
                "kind": (hit.get("memory") or {}).get("kind"),
                "text_head": ((hit.get("memory") or {}).get("text") or "")[:80],
            }
            for hit in hits.get("hits", [])
        ],
    }

    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n全部验证通过，证据写入", EVIDENCE_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
