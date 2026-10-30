"""生成《记忆剧场》的 Dify Workflow DSL。

规则引擎源码在 dsl/theatre_rules.py，这里把它原样嵌入 Code 节点，
保证「提交的 DSL」与「可单测的源码」永远是同一份逻辑。

用法：
    python3 scripts/build_dsl.py
输出：
    dsl/memory-theatre-workflow.yml
"""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES = (ROOT / "dsl" / "theatre_rules.py").read_text(encoding="utf-8")

PC_URL = "{{#env.POWERCONTEXT_URL#}}"
PC_HEADERS = "Content-Type:application/json"
Y = 260


def node(node_id, kind, title, x, **data):
    return {
        "id": node_id,
        "type": "custom",
        "position": {"x": x, "y": Y},
        "positionAbsolute": {"x": x, "y": Y},
        "width": 244,
        "height": 100,
        "sourcePosition": "right",
        "targetPosition": "left",
        "data": {"type": kind, "title": title, "desc": "", "selected": False, **data},
    }


def var(name, selector):
    return {"variable": name, "value_selector": selector}


def http(node_id, title, x, path, body_expr):
    return node(
        node_id,
        "http-request",
        title,
        x,
        method="post",
        url=PC_URL + path,
        authorization={"type": "no-auth"},
        headers=PC_HEADERS,
        params="",
        body={"type": "raw-text", "data": [{"type": "text", "key": "", "value": body_expr}]},
        timeout={"connect": 10, "read": 60, "write": 10},
        ssl_verify=True,
    )


START_VARS = [
    {
        "variable": "player_id",
        "label": "玩家标识",
        "type": "text-input",
        "required": True,
        "max_length": 120,
        "options": [],
        "description": "同一个标识对应同一条 PowerContext 记忆线。",
    },
    {
        "variable": "player_name",
        "label": "玩家称呼",
        "type": "text-input",
        "required": False,
        "max_length": 40,
        "options": [],
        "description": "留空则显示为「旅人」。",
    },
    {
        "variable": "action",
        "label": "这一幕你想做什么",
        "type": "paragraph",
        "required": True,
        "max_length": 1000,
        "options": [],
        "description": "例如：A 调查移动的出口 / B 整蛊鸽子议会 / C 和门卫协商，也可以写自己的行动。",
    },
    {
        "variable": "channel",
        "label": "剧场频道",
        "type": "text-input",
        "required": False,
        "max_length": 30,
        "options": [],
        "description": "surreal（荒诞喜剧，默认）/ mystery（午夜悬疑）/ cyber（赛博朋克）。",
    },
]

NODES = [
    node("start", "start", "玩家输入", 0, variables=START_VARS),
    node(
        "scope_req",
        "code",
        "准备记忆空间请求",
        280,
        code_language="python3",
        variables=[var("player_id", ["start", "player_id"])],
        code=(
            "def main(player_id: str) -> dict:\n"
            "    import json\n"
            "    pid = (player_id or '').strip()\n"
            "    if not pid:\n"
            "        raise ValueError('缺少 player_id')\n"
            "    body = {\n"
            "        'title': '记忆剧场 · ' + pid,\n"
            "        'summary': '一个玩家在记忆剧场里的全部幕次与记忆。',\n"
            "        'idempotency_key': 'memory-theatre-' + pid,\n"
            "    }\n"
            "    return {'scope_body': json.dumps(body, ensure_ascii=False)}\n"
        ),
        outputs={"scope_body": {"type": "string"}},
    ),
    http("scope_create", "打开玩家记忆空间", 560, "/v1/scopes", "{{#scope_req.scope_body#}}"),
    node(
        "scope_parse",
        "code",
        "取出 scope_id",
        840,
        code_language="python3",
        variables=[var("body", ["scope_create", "body"]), var("status_code", ["scope_create", "status_code"])],
        code=(
            "def main(body: str, status_code: int) -> dict:\n"
            "    import json\n"
            "    if status_code not in (200, 201):\n"
            "        raise ValueError('PowerContext 创建记忆空间失败: ' + (body or '')[:300])\n"
            "    data = json.loads(body or '{}')\n"
            "    scope_id = data.get('scope_id')\n"
            "    if not scope_id:\n"
            "        raise ValueError('PowerContext 没有返回 scope_id')\n"
            "    search = {'scope_id': scope_id, 'query': '记忆剧场', 'limit': 50}\n"
            "    return {'scope_id': scope_id, 'search_body': json.dumps(search, ensure_ascii=False)}\n"
        ),
        outputs={"scope_id": {"type": "string"}, "search_body": {"type": "string"}},
    ),
    http("search", "检索该玩家的历史记忆", 1120, "/v1/memory/search", "{{#scope_parse.search_body#}}"),
    node(
        "rules",
        "code",
        "剧情规则引擎",
        1400,
        code_language="python3",
        variables=[
            var("search_json", ["search", "body"]),
            var("status_code", ["search", "status_code"]),
            var("player_id", ["start", "player_id"]),
            var("player_name", ["start", "player_name"]),
            var("action", ["start", "action"]),
            var("channel", ["start", "channel"]),
        ],
        code=RULES,
        outputs={
            "answer": {"type": "string"},
            "save_text": {"type": "string"},
            "meta": {"type": "string"},
        },
    ),
    node(
        "remember_req",
        "code",
        "组装记忆写入请求",
        1680,
        code_language="python3",
        variables=[
            var("scope_id", ["scope_parse", "scope_id"]),
            var("save_text", ["rules", "save_text"]),
        ],
        code=(
            "def main(scope_id: str, save_text: str) -> dict:\n"
            "    import json\n"
            "    body = {'scope_id': scope_id, 'kind': 'decision', 'text': save_text}\n"
            "    return {'remember_body': json.dumps(body, ensure_ascii=False)}\n"
        ),
        outputs={"remember_body": {"type": "string"}},
    ),
    http("remember", "写入本幕记忆", 1960, "/v1/memory/remember", "{{#remember_req.remember_body#}}"),
    node(
        "verify_req",
        "code",
        "校验写入结果",
        2240,
        code_language="python3",
        variables=[
            var("body", ["remember", "body"]),
            var("status_code", ["remember", "status_code"]),
            var("scope_id", ["scope_parse", "scope_id"]),
        ],
        code=(
            "def main(body: str, status_code: int, scope_id: str) -> dict:\n"
            "    import json\n"
            "    if status_code != 200:\n"
            "        raise ValueError('PowerContext 写入记忆失败: ' + (body or '')[:300])\n"
            "    data = json.loads(body or '{}')\n"
            "    if not data.get('changed'):\n"
            "        raise ValueError('PowerContext 没有确认记忆变更')\n"
            "    records = data.get('records') or []\n"
            "    if not records:\n"
            "        raise ValueError('PowerContext 没有返回记忆条目')\n"
            "    artifact = records[0].get('artifact') or {}\n"
            "    verify = {'scope_id': scope_id, 'query': '记忆剧场', 'limit': 10}\n"
            "    info = {\n"
            "        'artifact_id': artifact.get('artifact_id'),\n"
            "        'revision': artifact.get('revision'),\n"
            "        'family': artifact.get('family'),\n"
            "        'kind': records[0].get('kind'),\n"
            "        'state': records[0].get('state'),\n"
            "    }\n"
            "    return {'verify_body': json.dumps(verify, ensure_ascii=False), 'saved': json.dumps(info, ensure_ascii=False)}\n"
        ),
        outputs={"verify_body": {"type": "string"}, "saved": {"type": "string"}},
    ),
    http("verify_read", "读回校验本幕记忆", 2520, "/v1/memory/search", "{{#verify_req.verify_body#}}"),
    node(
        "receipt",
        "code",
        "生成记忆回执",
        2800,
        code_language="python3",
        variables=[
            var("body", ["verify_read", "body"]),
            var("status_code", ["verify_read", "status_code"]),
            var("saved", ["verify_req", "saved"]),
            var("save_text", ["rules", "save_text"]),
            var("meta", ["rules", "meta"]),
            var("scope_id", ["scope_parse", "scope_id"]),
        ],
        code=(
            "def main(body: str, status_code: int, saved: str, save_text: str, meta: str, scope_id: str) -> dict:\n"
            "    import json\n"
            "    if status_code != 200:\n"
            "        raise ValueError('PowerContext 读回失败: ' + (body or '')[:300])\n"
            "    data = json.loads(body or '{}')\n"
            "    hits = data.get('hits') or []\n"
            "    found = False\n"
            "    for hit in hits:\n"
            "        memory = hit.get('memory') or {}\n"
            "        if memory.get('text') == save_text:\n"
            "            found = True\n"
            "            break\n"
            "    if not found:\n"
            "        raise ValueError('写入的记忆没有在 PowerContext 中读回')\n"
            "    receipt = {\n"
            "        'scope_id': scope_id,\n"
            "        'memory_artifact': json.loads(saved or '{}'),\n"
            "        'read_back_hits': len(hits),\n"
            "        'read_back_verified': True,\n"
            "        'round': json.loads(meta or '{}'),\n"
            "    }\n"
            "    return {'receipt': json.dumps(receipt, ensure_ascii=False)}\n"
        ),
        outputs={"receipt": {"type": "string"}},
    ),
    node(
        "end",
        "end",
        "本幕剧情与记忆回执",
        3080,
        outputs=[var("answer", ["rules", "answer"]), var("receipt", ["receipt", "receipt"])],
    ),
]

EDGES = []
for a, b in zip(NODES, NODES[1:]):
    EDGES.append(
        {
            "id": a["id"] + "-" + b["id"],
            "type": "custom",
            "source": a["id"],
            "sourceHandle": "source",
            "target": b["id"],
            "targetHandle": "target",
            "data": {
                "sourceType": a["data"]["type"],
                "targetType": b["data"]["type"],
                "isInIteration": False,
                "isInLoop": False,
            },
        }
    )

WORKFLOW = {
    "app": {
        "name": "记忆剧场 · 门卫阿铁",
        "mode": "workflow",
        "icon": "🎭",
        "icon_background": "#FEF3C7",
        "description": "Dify 编排的即兴荒诞剧场：门卫阿铁会记住你的每一次恶作剧，并在之后翻旧账。记忆由 PowerContext 持久化。",
        "use_icon_as_answer_icon": False,
    },
    "kind": "app",
    "version": "0.4.0",
    "dependencies": [],
    "workflow": {
        "conversation_variables": [],
        "environment_variables": [
            {
                "id": "powercontext-url",
                "name": "POWERCONTEXT_URL",
                "value": "http://127.0.0.1:8124",
                "value_type": "string",
                "description": "Dify API 容器可访问的 PowerContext 地址（无 /v1 后缀）",
            }
        ],
        "features": {
            "file_upload": {"enabled": False},
            "opening_statement": "",
            "retriever_resource": {"enabled": False},
            "sensitive_word_avoidance": {"enabled": False},
            "speech_to_text": {"enabled": False},
            "suggested_questions": [],
            "suggested_questions_after_answer": {"enabled": False},
            "text_to_speech": {"enabled": False},
        },
        "graph": {
            "nodes": NODES,
            "edges": EDGES,
            "viewport": {"x": 0, "y": 0, "zoom": 0.55},
        },
    },
}


def main():
    out = ROOT / "dsl" / "memory-theatre-workflow.yml"
    text = yaml.safe_dump(WORKFLOW, allow_unicode=True, sort_keys=False, width=4096, default_flow_style=False)
    out.write_text(text, encoding="utf-8", newline="\n")
    print("generated:", out, len(text), "bytes")


if __name__ == "__main__":
    main()
