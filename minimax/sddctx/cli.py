"""``sddctx`` 命令行入口。

常用流程::

    python -m sddctx ingest                    # 把规格 / 代码 / 测试导入 seekdb
    python -m sddctx context --task "..."      # 组装并输出开发上下文
    python -m sddctx modify --task "..."       # 用 MiniMax 完成一次真实代码修改
    python -m sddctx state show                # 读回 PowerContext 中的任务状态
    python -m sddctx db stats                  # 查看资料库统计
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .agent import DeveloperAgent, run_pytest
from .config import Settings, load_settings
from .context import build_context
from .ingest import build_code_record, build_spec_record, build_test_record, collect_records
from .state import TaskStateStore
from .store import MaterialStore


def make_store(settings: Settings) -> MaterialStore:
    return MaterialStore(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
    )


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_ingest(args: argparse.Namespace, settings: Settings) -> int:
    """把工程资料导入数据库。"""

    store = make_store(settings)
    store.ensure_schema()
    if args.reset:
        store.reset()

    records = collect_records(settings.root, include_history=args.include_history)
    for path in args.spec or []:
        records.append(build_spec_record(Path(path), settings.root))
    for path in args.code or []:
        records.append(build_code_record(Path(path), settings.root))
    for path in args.test or []:
        records.append(build_test_record(Path(path), settings.root))

    imported: list[dict[str, Any]] = []
    for record in records:
        revision = store.upsert_doc(record)
        imported.append(
            {
                "doc_id": record.doc_id,
                "kind": record.kind,
                "path": record.path,
                "version": record.version,
                "revision": revision,
                "symbols": len(record.symbols),
                "spec_entries": len(record.spec_entries),
            }
        )

    summary = {
        "database": {
            "host": settings.db_host,
            "port": settings.db_port,
            "name": settings.db_name,
        },
        "imported": imported,
        "stats": {key: value for key, value in store.describe().items() if key != "documents"},
    }
    if args.json:
        _print_json(summary)
    else:
        print(f"已导入 {len(imported)} 份资料到 {settings.db_host}:{settings.db_port}/{settings.db_name}")
        for item in imported:
            print(
                f"  - [{item['kind']}] {item['path']}  rev={item['revision']}"
                f"  symbols={item['symbols']} spec_entries={item['spec_entries']}"
            )
    _dump_json(settings.logs_dir / "ingest_summary.json", summary)
    return 0


def cmd_context(args: argparse.Namespace, settings: Settings) -> int:
    """组装开发上下文。"""

    store = make_store(settings)
    store.ensure_schema()
    task_id = args.task_id or "default"
    state_store = TaskStateStore(state_db_path=settings.state_db_path, task_id=task_id)
    state = asyncio.run(state_store.load())

    context = build_context(task= args.task, store=store, state=state, root=settings.root)
    payload = context.to_dict()

    if args.json:
        _print_json(payload)
    else:
        print(context.to_markdown())

    if args.out:
        _dump_json(Path(args.out), payload)
        print(f"\n上下文已写入 {args.out}")
    return 0


def cmd_modify(args: argparse.Namespace, settings: Settings) -> int:
    """用 MiniMax 完成一次真实代码修改。"""

    store = make_store(settings)
    store.ensure_schema()
    task_id = args.task_id or "default"
    state_store = TaskStateStore(state_db_path=settings.state_db_path, task_id=task_id)

    state = asyncio.run(state_store.load())
    context = build_context(task=args.task, store=store, state=state, root=settings.root)

    in_scope = list(dict.fromkeys(item.source_path for item in context.code)) or ["business/"]
    asyncio.run(
        state_store.record_contract(
            objective=args.task,
            in_scope=in_scope,
            completion_criteria=[
                "目标测试全部通过",
                "回归测试全部通过",
                "补丁可应用且与规格一致",
            ],
            facts=[f"适用规格条目 {item.identifier}" for item in context.specs],
        )
    )
    asyncio.run(
        state_store.checkpoint(
            objective=args.task,
            state=[
                f"已选定规格条目：{', '.join(item.identifier for item in context.specs) or '（无）'}",
                f"已选定代码符号：{', '.join(item.identifier for item in context.code[:6]) or '（无）'}",
                f"已选定测试：{len(context.tests)} 个",
            ],
            next_action="调用 MiniMax 生成补丁",
        )
    )

    agent = DeveloperAgent(settings=settings, task=args.task, task_id=task_id)
    attempts = asyncio.run(agent.run(context, max_attempts=args.max_attempts))

    report = {
        "task": args.task,
        "task_id": task_id,
        "model": settings.minimax_model,
        "attempts": [
            {
                "index": attempt.index,
                "call_id": attempt.call_id,
                "response_id": attempt.response_id,
                "model": attempt.model,
                "usage": attempt.usage,
                "applied": attempt.applied,
                "apply_error": attempt.apply_error,
                "test_exit_code": attempt.test.exit_code if attempt.test else None,
                "test_passed": attempt.accepted,
                "patch": attempt.patch,
            }
            for attempt in attempts
        ],
        "accepted": any(attempt.accepted for attempt in attempts),
    }
    _dump_json(settings.logs_dir / f"modify_{task_id}.json", report)

    if args.patch_out:
        best = next((attempt for attempt in attempts if attempt.accepted), None)
        if best is not None:
            Path(args.patch_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.patch_out).write_text(best.patch, encoding="utf-8")
            print(f"补丁已写入 {args.patch_out}")

    if report["accepted"]:
        print("MiniMax 补丁已应用，测试全部通过。")
        return 0
    print("MiniMax 未能产出通过的补丁。", file=sys.stderr)
    return 1


def cmd_state_show(args: argparse.Namespace, settings: Settings) -> int:
    """读回 PowerContext 任务状态。"""

    task_id = args.task_id or "default"
    state_store = TaskStateStore(state_db_path=settings.state_db_path, task_id=task_id)
    state = asyncio.run(state_store.load())
    payload = state.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(f"Scope: {payload['scope_id']}")
        print(f"目标: {payload['objective']}")
        print(f"已完成事项 ({len(payload['done'])}):")
        for text in payload["done"]:
            print(f"  - {text}")
        print(f"待办事项 ({len(payload['todo'])}):")
        for text in payload["todo"]:
            print(f"  - {text}")
        print(f"已有验证结果 ({len(payload['verifications'])}):")
        for text in payload["verifications"]:
            print(f"  - {text}")
        print(f"最新里程碑: {json.dumps(payload['latest_handoff'], ensure_ascii=False)}")
    return 0


def cmd_state_reset(args: argparse.Namespace, settings: Settings) -> int:
    """清空任务状态（验证样例的"重置方法"）。"""

    task_id = args.task_id or "default"
    path = settings.state_db_path
    if path.exists():
        path.unlink()
    for suffix in ("-wal", "-shm"):
        extra = Path(str(path) + suffix)
        if extra.exists():
            extra.unlink()
    print(f"已清空任务状态：{path}")
    return 0


def cmd_db_stats(args: argparse.Namespace, settings: Settings) -> int:
    """查看资料库统计。"""

    store = make_store(settings)
    stats = store.describe()
    if args.json:
        _print_json(stats)
    else:
        print(f"资料库 {settings.db_host}:{settings.db_port}/{settings.db_name}")
        for table in ("sdd_doc", "sdd_spec_entry", "sdd_symbol", "sdd_term", "sdd_doc_revision"):
            print(f"  {table}: {stats[table]} 行")
        print("  文档：")
        for doc in stats["documents"]:
            print(
                f"    [{doc['kind']}] {doc['path']}  version={doc['version']} rev={doc['revision']}"
                f" sha256={doc['content_sha256'][:12]}… updated={doc['updated_at']}"
            )
    return 0


def cmd_db_sql(args: argparse.Namespace, settings: Settings) -> int:
    """执行一条只读 SQL（用于生成数据库查询记录）。"""

    import pymysql

    conn = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    with conn, conn.cursor() as cursor:
        cursor.execute(args.statement)
        rows = cursor.fetchall()
    print(json.dumps({"statement": args.statement, "row_count": len(rows), "rows": rows}, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_test(args: argparse.Namespace, settings: Settings) -> int:
    """运行业务工程测试。"""

    run = run_pytest(settings.root, args.node_id or None)
    print(run.summary())
    return run.exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sddctx", description="SDD 上下文管理模块")
    parser.add_argument("--root", default=None, help="项目根目录（默认是包所在目录）")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="把规格 / 代码 / 测试导入 seekdb")
    ingest.add_argument("--reset", action="store_true", help="导入前清空资料库")
    ingest.add_argument("--include-history", action="store_true", help="同时导入 specs/versions 下的历史规格")
    ingest.add_argument("--spec", action="append", help="额外导入的规格文件")
    ingest.add_argument("--code", action="append", help="额外导入的代码文件")
    ingest.add_argument("--test", action="append", help="额外导入的测试文件")
    ingest.add_argument("--json", action="store_true", help="以 JSON 输出")
    ingest.set_defaults(func=cmd_ingest)

    context = sub.add_parser("context", help="组装并输出开发上下文")
    context.add_argument("--task", required=True, help="开发任务描述")
    context.add_argument("--task-id", default="default", help="任务编号（用于关联 PowerContext 状态）")
    context.add_argument("--json", action="store_true", help="以 JSON 输出")
    context.add_argument("--out", default=None, help="把上下文 JSON 写入文件")
    context.set_defaults(func=cmd_context)

    modify = sub.add_parser("modify", help="用 MiniMax 完成一次真实代码修改")
    modify.add_argument("--task", required=True, help="开发任务描述")
    modify.add_argument("--task-id", default="default", help="任务编号")
    modify.add_argument("--max-attempts", type=int, default=3, help="最大尝试次数")
    modify.add_argument("--patch-out", default=None, help="把最终补丁写入文件")
    modify.set_defaults(func=cmd_modify)

    state = sub.add_parser("state", help="PowerContext 任务状态")
    state_sub = state.add_subparsers(dest="state_command", required=True)
    show = state_sub.add_parser("show", help="读回任务状态")
    show.add_argument("--task-id", default="default")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_state_show)
    reset = state_sub.add_parser("reset", help="清空任务状态")
    reset.add_argument("--task-id", default="default")
    reset.set_defaults(func=cmd_state_reset)

    db = sub.add_parser("db", help="资料库运维")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    stats = db_sub.add_parser("stats", help="统计信息")
    stats.add_argument("--json", action="store_true")
    stats.set_defaults(func=cmd_db_stats)
    sql = db_sub.add_parser("sql", help="执行只读 SQL")
    sql.add_argument("statement", help="SQL 语句")
    sql.set_defaults(func=cmd_db_sql)

    test = sub.add_parser("test", help="运行业务工程测试")
    test.add_argument("node_id", nargs="*", help="pytest 节点 ID")
    test.set_defaults(func=cmd_test)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings(Path(args.root) if args.root else None)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.state_db_path.parent.mkdir(parents=True, exist_ok=True)
    return int(args.func(args, settings))


if __name__ == "__main__":
    raise SystemExit(main())
