"""可复核的验证脚本：跑通「导入 → 混合检索 → 带引用回答 → 记忆复用」。

用法：
    python -m scripts.verify_demo
输出会同时打印到终端并写入 docs/verification-log.txt。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from app import service
from app.config import settings
from app.memory import memory
from app.store import store

USER = "demo-user"
LOGS: list[str] = []


def emit(line: str = "") -> None:
    print(line)
    LOGS.append(line)


def section(title: str) -> None:
    emit()
    emit("=" * 68)
    emit(title)
    emit("=" * 68)


def main() -> int:
    emit(f"PaperMind 验证 · {datetime.now().isoformat(timespec='seconds')}")
    emit(
        f"seekdb 模式：{settings.seekdb_mode} · 数据库：{settings.seekdb_database} · "
        f"向量后端：{settings.embedding_backend}（{settings.effective_embedding_dim} 维） · "
        f"对话模型：{'已配置' if settings.has_llm else '未配置（降级为证据清单）'}"
    )

    section("1. seekdb 连接与索引统计")
    store.ensure()
    stats = store.stats()
    emit(json.dumps(stats, ensure_ascii=False, indent=2))
    if stats["documents"] == 0:
        emit("库为空，请先执行：python -m scripts.seed")
        return 1

    section("2. PowerContext 连接")
    status = memory.status()
    emit(json.dumps(status, ensure_ascii=False, indent=2))
    if not status["available"]:
        emit("PowerContext 未启动，记忆验证将跳过（其余功能仍可验证）。")

    section("3. 第一轮提问（无历史记忆）")
    q1 = "混合检索里向量通道和全文通道分别擅长什么？RRF 的 k 一般取多少？"
    emit(f"Q1: {q1}")
    r1 = service.ask(USER, q1)
    emit(f"A1: {r1['answer'][:600]}")
    emit("检索追踪:")
    emit(json.dumps(r1["trace"], ensure_ascii=False, indent=2))
    emit("引用:")
    for c in r1["citations"]:
        emit(f"  [{c['n']}] 《{c['title']}》 · {c['section']} · score={c['score']}")
    emit(f"记忆：命中 {len(r1['memory']['hits'])} 条，回写 {len(r1['memory']['written'])} 条")

    section("4. 表达长期偏好（触发 preference 记忆写入）")
    q2 = "以后回答请先给结论，再给依据，控制在 400 字以内。"
    emit(f"Q2: {q2}")
    r2 = service.ask(USER, q2)
    emit(f"回写记忆：{json.dumps(r2['memory']['written'], ensure_ascii=False, indent=2)}")

    section("5. 新问题的记忆复用")
    q3 = "请按我的回答偏好来：文档切片重叠一般设多少？"
    emit(f"Q3: {q3}")
    r3 = service.ask(USER, q3)
    emit(f"A3: {r3['answer'][:600]}")
    emit(f"长期偏好（每轮注入）{len(r3['memory']['preferences'])} 条：")
    emit(json.dumps(r3["memory"]["preferences"], ensure_ascii=False, indent=2))
    emit(f"记忆命中 {len(r3['memory']['hits'])} 条：")
    emit(json.dumps(r3["memory"]["hits"], ensure_ascii=False, indent=2))
    emit("注入模型的长期记忆上下文：")
    emit(r3["memory"]["memory_context"] or "（空）")

    section("6. 结论")
    checks = {
        "seekdb 已建立索引": stats["documents"] > 0,
        "混合检索返回引用": len(r1["citations"]) > 0,
        "向量通道有命中": len(r1["trace"]["vector_route"]) > 0,
        "全文通道有命中": len(r1["trace"]["fulltext_route"]) > 0,
        "PowerContext 可用": status["available"],
        "偏好被写入记忆": any(w["kind"] == "preference" for w in r2["memory"]["written"]),
        "后续提问复用偏好": len(r3["memory"]["preferences"]) > 0
        and "400" in (r3["memory"]["memory_context"] or ""),
    }
    for name, ok in checks.items():
        emit(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    out = Path(settings.project_root) / "docs" / "verification-log.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(LOGS) + "\n", encoding="utf-8")
    emit(f"\n日志已写入 {out}")
    return 0 if all(checks.values()) else 2


if __name__ == "__main__":
    sys.exit(main())
