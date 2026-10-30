"""Context assembly for the spec-driven development demo.

The module turns one development task into a bounded context package: the
specification clauses, source files, and tests that the task depends on. The
payload is written next to the demo project so an agent can consume it from
the workspace.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from mmctx.pc import PowerContextClient, PowerContextError
from mmctx.store import Store

CONTEXT_DIR = ".mmcontext"
PER_KIND = 3


def build_context(
    store: Store,
    task: str,
    root: Path,
    pc: PowerContextClient | None = None,
) -> dict:
    """Builds and persists the context package for one task."""

    sections: dict[str, list[dict]] = {}
    for kind in ("spec", "code", "test"):
        hits = store.query(task, kind=kind, limit=PER_KIND)
        if not hits:
            hits = store.list_kind(kind, limit=PER_KIND)
        sections[kind] = hits

    previous_state: list[dict] = []
    if pc is not None:
        try:
            previous_state = pc.load_state(task)
        except PowerContextError:
            previous_state = []

    latest = previous_state[-1] if previous_state else {}
    progress = {
        "done": latest.get("done", ["context package built from seekdb sources"]),
        "todo": latest.get("todo", ["apply the code change", "run target and regression tests"]),
        "verification": latest.get("verification", []),
    }

    context = {
        "task": task,
        "generated_at": datetime.now(UTC).isoformat(),
        "specs": sections["spec"],
        "code": sections["code"],
        "tests": sections["test"],
        "sources": sorted({item["path"] for items in sections.values() for item in items}),
        "progress": progress,
        "previous_state": previous_state,
    }

    context_dir = root / CONTEXT_DIR
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "context.json").write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    (context_dir / "prompt.md").write_text(render_prompt(context), encoding="utf-8")

    if pc is not None:
        try:
            pc.save_state(
                {
                    "task": task,
                    "status": "context-built",
                    "sources": context["sources"],
                    "context_file": str(context_dir / "context.json"),
                    "updated_at": context["generated_at"],
                    "done": progress["done"],
                    "todo": progress["todo"],
                    "verification": progress["verification"],
                }
            )
        except PowerContextError:
            pass
    return context


def render_prompt(context: dict) -> str:
    """Renders the context package as an agent-facing prompt."""

    lines = [
        "# Development task",
        "",
        context["task"],
        "",
        "# Applicable specification",
        "",
    ]
    for item in context["specs"]:
        lines.extend([f"## {item['path']}", "", item["body"].strip(), ""])
    lines.extend(["# Files to inspect", ""])
    for item in context["code"]:
        lines.append(f"- `{item['path']}`: {item['title']}")
    lines.extend(["", "# Tests that define done", ""])
    for item in context["tests"]:
        lines.append(f"- `{item['path']}`: {item['title']}")
    progress = context.get("progress", {})
    lines.extend(["", "# Progress", ""])
    lines.append("Done: " + "; ".join(progress.get("done", []) or ["none"]))
    lines.append("Todo: " + "; ".join(progress.get("todo", []) or ["none"]))
    lines.append("Verification: " + "; ".join(progress.get("verification", []) or ["none"]))
    if context["previous_state"]:
        lines.extend(["", "# Previous task state", ""])
        lines.append(json.dumps(context["previous_state"][-1], ensure_ascii=False, indent=2))
    lines.extend(
        [
            "",
            "# Constraints",
            "",
            "- Modify only files under `src/`.",
            "- Keep the existing public API and all existing tests passing.",
            "- Run `python -m pytest -q tests` before finishing.",
            "",
        ]
    )
    return "\n".join(lines)
