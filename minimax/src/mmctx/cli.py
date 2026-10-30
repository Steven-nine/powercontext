"""Command-line entry point for the SDD context module."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from mmctx.context import build_context
from mmctx.pc import DEFAULT_URL, PowerContextClient, PowerContextError
from mmctx.store import DEFAULT_DB, Store, collect_docs


def _add_store_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", default=DEFAULT_DB, help="seekdb data directory")


def cmd_ingest(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    docs = collect_docs(root)
    store = Store(args.db)
    try:
        count = store.replace_all(docs)
    finally:
        store.close()
    print(json.dumps({"root": str(root), "documents": count}, ensure_ascii=False))
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    store = Store(args.db)
    pc = None if args.no_state else PowerContextClient(args.pc_url)
    try:
        context = build_context(store, args.task, root, pc)
    finally:
        store.close()
    print(json.dumps(context, ensure_ascii=False, indent=2))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    store = Store(args.db)
    try:
        hits = store.query(args.text, kind=args.kind, limit=args.limit)
    finally:
        store.close()
    print(json.dumps(hits, ensure_ascii=False, indent=2))
    return 0


def cmd_state_save(args: argparse.Namespace) -> int:
    pc = PowerContextClient(args.pc_url)
    state = {
        "task": args.task,
        "status": args.status,
        "notes": args.notes or "",
        "phase": args.phase or "",
    }
    if args.done:
        state["done"] = [item.strip() for item in args.done.split(",") if item.strip()]
    if args.todo:
        state["todo"] = [item.strip() for item in args.todo.split(",") if item.strip()]
    if args.verification:
        state["verification"] = [item.strip() for item in args.verification.split(",") if item.strip()]
    pc.save_state(state)
    print(json.dumps(state, ensure_ascii=False))
    return 0


def cmd_state_load(args: argparse.Namespace) -> int:
    pc = PowerContextClient(args.pc_url)
    states = pc.load_state(args.query)
    print(json.dumps(states, ensure_ascii=False, indent=2))
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    log_dir = Path(args.log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{args.label}.log"
    command = [sys.executable, "-m", "pytest", "-q", "tests"]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True)
    output = completed.stdout + completed.stderr
    log_path.write_text(output, encoding="utf-8")
    print(output)
    print(f"exit_code={completed.returncode} log={log_path}")
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mmctx", description="Spec-driven context module for the MiniMax demo.")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Ingest repository documents into seekdb")
    ingest.add_argument("--root", default="demo-app")
    _add_store_args(ingest)
    ingest.set_defaults(func=cmd_ingest)

    context = sub.add_parser("context", help="Build the context package for one task")
    context.add_argument("--task", required=True)
    context.add_argument("--root", default="demo-app")
    context.add_argument("--pc-url", default=DEFAULT_URL)
    context.add_argument("--no-state", action="store_true", help="Do not save or read PowerContext state")
    _add_store_args(context)
    context.set_defaults(func=cmd_context)

    query = sub.add_parser("query", help="Query the seekdb document store directly")
    query.add_argument("--text", required=True)
    query.add_argument("--kind", choices=["spec", "code", "test", "guide"])
    query.add_argument("--limit", type=int, default=5)
    _add_store_args(query)
    query.set_defaults(func=cmd_query)

    state = sub.add_parser("state", help="Save or load task state through PowerContext")
    state_sub = state.add_subparsers(dest="state_command", required=True)
    save = state_sub.add_parser("save")
    save.add_argument("--task", required=True)
    save.add_argument("--status", required=True)
    save.add_argument("--notes", default="")
    save.add_argument("--phase", default="")
    save.add_argument("--done", default="")
    save.add_argument("--todo", default="")
    save.add_argument("--verification", default="")
    save.add_argument("--pc-url", default=DEFAULT_URL)
    save.set_defaults(func=cmd_state_save)
    load = state_sub.add_parser("load")
    load.add_argument("--query", default="task state")
    load.add_argument("--pc-url", default=DEFAULT_URL)
    load.set_defaults(func=cmd_state_load)

    test = sub.add_parser("test", help="Run demo tests and record a log")
    test.add_argument("--root", default="demo-app")
    test.add_argument("--label", required=True)
    test.add_argument("--log-dir", default="evidence/logs")
    test.set_defaults(func=cmd_test)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except PowerContextError as exc:
        print(f"powercontext error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
