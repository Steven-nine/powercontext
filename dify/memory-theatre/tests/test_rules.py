#!/usr/bin/env python3
"""《记忆剧场》规则引擎单元测试（纯标准库，不需要 Dify / PowerContext）。

    python3 tests/test_rules.py

被测代码就是嵌入 Dify Code 节点的 dsl/theatre_rules.py，
因此这里验证过的行为与线上工作流一致。
"""

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dsl"))

import theatre_rules  # noqa: E402

MEMORY = theatre_rules.MEMORY_TAG


def hit(text):
    return {"memory": {"artifact": {"family": "atomic-memory", "artifact_id": "art_test", "revision": 1}, "text": text}}


def run(hits, action, channel="surreal", player_id="p1", player_name="阿舟"):
    payload = json.dumps({"mode": "text", "hits": hits}, ensure_ascii=False)
    return theatre_rules.main(payload, 200, player_id, player_name, action, channel)


def memory_of(turn_result):
    return json.loads(turn_result["save_text"].split("\n", 1)[1])


class RulesTest(unittest.TestCase):
    def test_first_turn_has_no_history(self):
        result = run([], "A 调查移动的出口")
        self.assertIn("第 1 幕", result["answer"])
        self.assertIn("信任 1", result["answer"])
        meta = json.loads(result["meta"])
        self.assertEqual(meta["history_found"], 0)
        self.assertFalse(meta["recalled_previous"])

    def test_prank_is_recorded_as_grudge(self):
        run([], "A 调查移动的出口")
        second = run([hit(MEMORY + "\n" + json.dumps({"message": "A 调查移动的出口", "state": {"turn": 1, "trust": 1, "chaos": 0, "coins": 3, "grudge": "", "motto": ""}, "kind": "investigate"}, ensure_ascii=False))], "B 整蛊鸽子议会")
        meta = json.loads(second["meta"])
        self.assertEqual(meta["action_kind"], "prank")
        self.assertEqual(memory_of(second)["state"]["grudge"], "B 整蛊鸽子议会")

    def test_grudge_is_recalled_on_next_turn(self):
        history = json.dumps(
            {"message": "B 整蛊鸽子议会", "state": {"turn": 2, "trust": 1, "chaos": 1, "coins": 3, "grudge": "B 整蛊鸽子议会", "motto": ""}, "kind": "prank"},
            ensure_ascii=False,
        )
        third = run([hit(MEMORY + "\n" + history)], "C 和门卫协商")
        self.assertIn("翻起了旧账", third["answer"])
        self.assertIn("B 整蛊鸽子议会", third["answer"])
        self.assertTrue(json.loads(third["meta"])["grudge_used"])

    def test_motto_is_remembered_for_free_actions(self):
        first = run([], "我给门卫的灯笼画了一只眼睛")
        self.assertEqual(memory_of(first)["state"]["motto"], "我给门卫的灯笼画了一只眼睛")
        history = json.dumps(
            {"message": "我给门卫的灯笼画了一只眼睛", "state": {"turn": 1, "trust": 0, "chaos": 1, "coins": 3, "grudge": "", "motto": "我给门卫的灯笼画了一只眼睛"}, "kind": "free"},
            ensure_ascii=False,
        )
        second = run([hit(MEMORY + "\n" + history)], "A 调查移动的出口")
        self.assertIn("灯笼画了一只眼睛", second["answer"])
        self.assertTrue(json.loads(second["meta"])["motto_used"])

    def test_negotiate_spends_coin_and_raises_trust(self):
        result = run([], "C 和门卫协商")
        self.assertIn("信任 2", result["answer"])
        self.assertIn("硬币 2", result["answer"])

    def test_achievement_trust(self):
        hits = []
        state = {"turn": 0, "trust": 0, "chaos": 0, "coins": 3, "grudge": "", "motto": ""}
        for message, kind in (("A 调查移动的出口", "investigate"), ("C 和门卫协商", "negotiate")):
            state["turn"] += 1
            state["trust"] += 1 if kind == "investigate" else 2
            state["coins"] -= 1 if kind == "negotiate" else 0
            hits.append(hit(MEMORY + "\n" + json.dumps({"message": message, "state": dict(state), "kind": kind}, ensure_ascii=False)))
        result = run(hits, "C 再次协商")
        self.assertIn("门卫合伙人", result["answer"])

    def test_chaos_achievement(self):
        hits = []
        state = {"turn": 0, "trust": 0, "chaos": 0, "coins": 3, "grudge": "", "motto": ""}
        for _ in range(4):
            state["turn"] += 1
            state["chaos"] += 1
            hits.append(hit(MEMORY + "\n" + json.dumps({"message": "B 整蛊鸽子议会", "state": dict(state), "kind": "prank"}, ensure_ascii=False)))
        result = run(hits, "B 整蛊鸽子议会")
        self.assertIn("混乱市长", result["answer"])

    def test_channels_change_scene(self):
        for channel, scene in (("surreal", "荒诞城门"), ("mystery", "午夜档案室"), ("cyber", "轨道太空港")):
            result = run([], "A 调查移动的出口", channel=channel)
            self.assertIn(scene, result["answer"])
        unknown = run([], "A 调查移动的出口", channel="not-a-channel")
        self.assertIn("荒诞城门", unknown["answer"])

    def test_memory_text_within_limit(self):
        result = run([], "A" * 3000)
        self.assertLessEqual(len(result["save_text"].encode("utf-8")), 8192)

    def test_invalid_status_raises(self):
        with self.assertRaises(ValueError):
            theatre_rules.main("{}", 500, "p1", "阿舟", "A 调查", "surreal")

    def test_empty_action_raises(self):
        with self.assertRaises(ValueError):
            run([], "   ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
