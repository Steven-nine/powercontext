"""记忆剧场 · 门卫阿铁 —— 剧情规则引擎。

这个文件有两个用途，必须保持一致：
1. 被 scripts/build_dsl.py 原样嵌入 Dify Workflow 的 Code 节点；
2. 被 tests/test_rules.py 直接 import 做单元测试。

所以这里不写任何模块级 import（Dify Sandbox 会拒绝模块级 import，
`import json` 必须写在函数体内部），只使用纯 Python 内置能力。
"""

MEMORY_TAG = "记忆剧场"
MAX_BYTES = 8192
MAX_TURNS = 12

CHANNELS = {
    "surreal": {
        "scene": "荒诞城门",
        "npc": "门卫阿铁",
        "events": {
            "investigate": [
                "阿铁掏出一张倒着印的地图，出口在纸面上缓缓挪动，他坚持说自己从没画过这张图。",
                "你沿着墙根走了一圈，发现所有脚印都通向门里，没有一个走出来的。",
                "阿铁承认城门每天换一个名字，但拒绝说出今天的名字，说那属于“机密”。",
            ],
            "prank": [
                "你把阿铁的帽子挂到了鸽子议会的告示牌上，全城的鸽子同时转过头来。",
                "你偷偷把门口的铜铃换成会自己鼓掌的小铃铛，阿铁鼓掌鼓了整整一炷香。",
                "你给阿铁的登记簿喂了一页写着“今日放假”的纸，阿铁盯着它看了很久。",
            ],
            "negotiate": [
                "你用一枚硬币换来阿铁的秘密：城门每天都会忘记自己的名字。",
                "阿铁把城门钥匙在掌心转了三圈，说这是他唯一敢告诉外人的事。",
                "你压低声音问门卫的底线，他咳了一声：“别再喂鸽子了，它们记性太好。”",
            ],
            "free": [
                "你刚说完一句话，一枚发光的螺丝钉便自封为城门的临时市长。",
                "阿铁认真地在登记簿上记下你的话，字迹像一排逃跑的鸡。",
                "城门发出一声像被烫到的呻吟，出口换了个方向继续挪动。",
            ],
        },
    },
    "mystery": {
        "scene": "午夜档案室",
        "npc": "守档人阿铁",
        "events": {
            "investigate": [
                "你在积灰的卷宗里翻到一张照片，照片上的你正朝镜头外的自己挥手。",
                "档案室的灯泡忽明忽暗，每闪一次，抽屉编号就往后跳一位。",
                "阿铁说这里的每一卷档案都还在被某个人续写，笔迹和你的一模一样。",
            ],
            "prank": [
                "你把档案室的座钟拨快了三小时，所有卷宗同时发出了翻页声。",
                "你偷偷替换了阿铁的墨水瓶，他写的字从此全部变成了弹簧字。",
                "你给一卷档案贴上了“已结案”的标签，深夜的走廊开始排队领号。",
            ],
            "negotiate": [
                "你用一枚硬币买下了阿铁的一句实话：午夜十二点，档案室会多出一层。",
                "阿铁压低声音说，别在午夜打开写着你自己名字的卷宗。",
                "他用红笔在一张便签上写下“可交换”，然后把那支笔推向你。",
            ],
            "free": [
                "你的话音落下，档案室深处传来拉链被拉开的声音。",
                "阿铁在登记簿上写下你的话，字迹慢慢洇开，像泡过水。",
                "墙上所有编号同时转向你，午夜的风从抽屉缝里挤了出来。",
            ],
        },
    },
    "cyber": {
        "scene": "轨道太空港",
        "npc": "值班门卫阿铁",
        "events": {
            "investigate": [
                "你调出闸机日志，发现每班闸机都在记录一个尚未出生的人。",
                "货运列车的到站时间全部显示为“昨天”，阿铁说这里的时间轴漏了一格。",
                "阿铁指着监控屏上静止的自己说：“那是我，明天的我，别去搭话。”",
            ],
            "prank": [
                "你把闸机的语音包换成了鸽子的咕咕声，全站的闸机开始集体让路。",
                "你把安检门换成旋转门，门卫第一次被自己的工牌拦在了外面。",
                "你给站台的广告屏投了一行字：今日停运。列车准点停下，全员鼓掌。",
            ],
            "negotiate": [
                "你用一枚硬币换来阿铁的通行证，代价是他要记住你三分钟。",
                "阿铁说这里的记忆可以外包，但只能按秒计费，他建议你买长期套餐。",
                "他在闸机上加了一道只有你能过的指纹，然后假装什么都没发生。",
            ],
            "free": [
                "你的话音被自动翻译成了八种语言，广播里同时回放了你的声音。",
                "阿铁在登记簿上敲了一串乱码，屏幕显示“已记录，但无法解析”。",
                "太空站的光忽然切到夜班模式，所有舷窗一起闪成了深海的蓝。",
            ],
        },
    },
}

DEFAULT_STATE = {"turn": 0, "trust": 0, "chaos": 0, "coins": 3, "grudge": "", "motto": ""}

ACTION_HINTS = [
    ("prank", ["整蛊", "捉弄", "恶作剧", "整蛊鸽子", "B", "b"]),
    ("negotiate", ["协商", "谈判", "交易", "交换", "谈", "C", "c"]),
    ("investigate", ["调查", "调查移动", "查", "搜索", "观察", "A", "a"]),
]


def classify(action: str) -> str:
    """把玩家的一句话归类到四种行动之一。"""
    text = (action or "").strip()
    for kind, hints in ACTION_HINTS:
        for hint in hints:
            if hint in text:
                return kind
    return "free"


def _pick(pool, seed: int):
    return pool[seed % len(pool)]


def _seed(turn: int, action: str) -> int:
    # 不依赖 hashlib（Sandbox 白名单更严格），用可复现的字符和。
    return turn * 7 + sum(ord(ch) for ch in (action or ""))


def _records_from_hits(hits):
    """从 PowerContext 检索结果里还原历史回合记录。"""
    import json

    records = []
    for hit in hits or []:
        memory = hit.get("memory") if isinstance(hit, dict) else None
        text = ""
        if isinstance(memory, dict):
            text = memory.get("text") or ""
        elif isinstance(hit, dict):
            text = hit.get("text") or ""
        if not isinstance(text, str) or not text.startswith(MEMORY_TAG + "\n"):
            continue
        try:
            record = json.loads(text.split("\n", 1)[1])
        except (ValueError, TypeError):
            continue
        if isinstance(record, dict) and isinstance(record.get("state"), dict):
            records.append(record)
    return records


def _ending(state):
    if state["trust"] >= 5:
        return "达成结局【门卫合伙人】：阿铁把备用钥匙塞进你手里，说从今天起你替他值班。"
    if state["chaos"] >= 5:
        return "达成结局【混乱市长】：鸽子议会全票通过，任命你为这座城门的新市长。"
    if state["coins"] <= 0 and state["trust"] < 2:
        return "达成结局【被城门除名】：你的名字从登记簿上蒸发了，门在你身后轻轻关上。"
    if state["turn"] >= MAX_TURNS:
        return "达成结局【长夜未央】：城门终于不动了，阿铁说这是他三百年来第一次下班。"
    return ""


def main(
    search_json: str,
    status_code: int,
    player_id: str,
    player_name: str,
    action: str,
    channel: str,
) -> dict:
    import json

    if status_code != 200:
        raise ValueError("PowerContext 检索失败: " + (search_json or "")[:300])

    payload = json.loads(search_json or "{}")
    hits = payload.get("hits")
    if not isinstance(hits, list):
        raise ValueError("PowerContext 返回的 hits 格式不正确")

    channel_key = channel if channel in CHANNELS else "surreal"
    profile = CHANNELS[channel_key]

    history = _records_from_hits(hits)
    previous = max(history, key=lambda item: item["state"].get("turn", 0), default=None)
    state = dict(DEFAULT_STATE)
    if previous:
        for key, value in previous["state"].items():
            if key in DEFAULT_STATE:
                state[key] = value
    state["turn"] = int(state["turn"]) + 1

    text = (action or "").strip()
    if not text:
        raise ValueError("请先写下一句你想做的事")
    kind = classify(text)

    if kind == "investigate":
        state["trust"] += 1
    elif kind == "prank":
        state["chaos"] += 1
        state["grudge"] = text[:80]
    elif kind == "negotiate":
        state["coins"] = max(0, int(state["coins"]) - 1)
        state["trust"] += 2
    else:
        state["chaos"] += 1
        if not state["motto"]:
            state["motto"] = text[:40]

    npc = profile["npc"]
    scene = profile["scene"]
    event = _pick(profile["events"][kind], _seed(state["turn"], text))

    # —— 记忆复用的三个证据点 ——
    recall = "这是你们第一次见面，阿铁把你的名字写在了会自己逃跑的登记簿上。"
    if previous:
        recall = npc + "还记得你上一幕干的事：‘" + str(previous.get("message", ""))[:60] + "’。"
    grudge_line = ""
    if previous and str(previous.get("kind", "")) == "prank":
        grudge_line = (
            "而且阿铁翻起了旧账：‘上回你干的那事——"
            + str(previous.get("message", ""))[:40]
            + "——我到现在还记着。’"
        )
    motto_line = ""
    if state["motto"] and state["turn"] >= 2:
        motto_line = "门卫又在念叨你那句‘" + state["motto"] + "’，念得像一句咒语。"

    ending = _ending(state)
    lines = [
        "第 " + str(state["turn"]) + " 幕 · " + scene,
        (player_name or "旅人") + "，" + recall,
    ]
    if grudge_line:
        lines.append(grudge_line)
    if motto_line:
        lines.append(motto_line)
    lines.append("▸ 你的行动：" + text)
    lines.append(event)
    if ending:
        lines.append(ending)
    lines.append(
        "状态：信任 "
        + str(state["trust"])
        + " / 混乱 "
        + str(state["chaos"])
        + " / 硬币 "
        + str(state["coins"])
    )
    lines.append("下一步：A 调查移动的出口 · B 整蛊鸽子议会 · C 和门卫协商 · 或者写下你自己的行动。")
    answer = "\n".join(lines)

    record = {
        "message": text,
        "answer": answer,
        "state": state,
        "channel": channel_key,
        "kind": kind,
    }
    payload_text = MEMORY_TAG + "\n" + json.dumps(record, ensure_ascii=False)
    if len(payload_text.encode("utf-8")) > MAX_BYTES:
        record["answer"] = answer[:600]
        payload_text = MEMORY_TAG + "\n" + json.dumps(record, ensure_ascii=False)
    if len(payload_text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("本轮互动超出 PowerContext 单条记忆 8192 字节上限")

    save_body = {
        "scope_id": "",
        "kind": "decision",
        "text": payload_text,
    }
    meta = {        "turn": state["turn"],
        "trust": state["trust"],
        "chaos": state["chaos"],
        "coins": state["coins"],
        "action_kind": kind,
        "channel": channel_key,
        "history_found": len(history),
        "history_hits": len(hits),
        "recalled_previous": bool(previous),
        "grudge_used": bool(grudge_line),
        "motto_used": bool(motto_line),
        "ending": ending,
        "player_id": player_id,
    }
    return {
        "answer": answer,
        "save_text": payload_text,
        "meta": json.dumps(meta, ensure_ascii=False),
    }
