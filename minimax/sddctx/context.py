"""开发上下文组装。

输入：一个开发任务描述 + 资料库（seekdb）+ 任务状态（PowerContext）。
输出：结构化的开发上下文，定位四类信息：

1. 本次任务适用的**规格条目**；
2. 需要修改的**代码文件或符号**；
3. 用于验证功能与兼容性的**测试**；
4. **已完成事项、待办事项和已有验证结果**（来自 PowerContext）。

上下文中的每一条来源都必须真实存在于工作区，否则组装直接失败。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .state import TaskState
from .store import MaterialStore, tokenize

#: 任务描述里出现的规格编号。
SPEC_ID_RE = re.compile(r"\bSPEC-[A-Z0-9]+-\d+\b")

#: 判定"目标测试"的最小引用强度：测试函数的 docstring 或名称里引用了任务点名的规格。
TARGET_SPEC_HIT = 1.0


@dataclass
class ContextItem:
    """上下文中的一条记录。"""

    kind: str
    identifier: str
    title: str
    source_path: str
    detail: str = ""
    score: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "kind": self.kind,
            "id": self.identifier,
            "title": self.title,
            "source": {"path": self.source_path, "exists": True},
            "score": round(self.score, 4),
        }
        if self.detail:
            payload["detail"] = self.detail
        payload.update(self.extra)
        return payload


@dataclass
class DevelopmentContext:
    """一次任务对应的开发上下文。"""

    task: str
    task_spec_ids: list[str]
    specs: list[ContextItem]
    code: list[ContextItem]
    tests: list[ContextItem]
    state: TaskState
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": {
                "text": self.task,
                "spec_ids": self.task_spec_ids,
            },
            "generated_at": self.generated_at,
            "specs": [item.to_dict() for item in self.specs],
            "code": [item.to_dict() for item in self.code],
            "tests": [item.to_dict() for item in self.tests],
            "state": {
                "scope_id": self.state.scope_id,
                "objective": self.state.objective,
                "done": self.state.done,
                "todo": self.state.todo,
                "verifications": self.state.verifications,
                "decisions": self.state.decisions,
                "latest_handoff": self.state.latest_handoff,
                "continuity_events": self.state.continuity_events,
            },
        }

    def to_markdown(self) -> str:
        """渲染成人可读的 Markdown，便于评审核对来源。"""

        lines: list[str] = []
        lines.append(f"# 开发上下文：{self.task}")
        lines.append("")
        lines.append(f"- 生成时间：{self.generated_at}")
        lines.append(f"- 任务点名的规格条目：{', '.join(self.task_spec_ids) or '（无）'}")
        lines.append(f"- PowerContext Scope：{self.state.scope_id}")
        lines.append("")
        lines.append("## 1. 适用的规格条目")
        lines.append("")
        for item in self.specs:
            lines.append(f"- **{item.identifier}** {item.title}  ")
            lines.append(f"  - 来源：`{item.source_path}`（规格版本 {item.extra.get('spec_version', '?')}，修订 {item.extra.get('revision', '?')}）")
            if item.detail:
                lines.append(f"  - 内容：{item.detail}")
        lines.append("")
        lines.append("## 2. 需要修改的代码")
        lines.append("")
        for item in self.code:
            lines.append(f"- `{item.source_path}` → {item.identifier}  ")
            lines.append(f"  - 签名：{item.extra.get('signature', '')}")
            lines.append(f"  - 行号：{item.extra.get('line_start', '?')}-{item.extra.get('line_end', '?')}")
        lines.append("")
        lines.append("## 3. 用于验证的测试")
        lines.append("")
        for item in self.tests:
            role = "目标测试" if item.extra.get("role") == "target" else "回归测试"
            lines.append(f"- [{role}] `{item.source_path}`::{item.identifier}  ")
            if item.detail:
                lines.append(f"  - 说明：{item.detail}")
        lines.append("")
        lines.append("## 4. 任务状态（PowerContext）")
        lines.append("")
        lines.append(f"- 已完成事项：{len(self.state.done)} 条")
        for text in self.state.done:
            lines.append(f"  - {text}")
        lines.append(f"- 待办事项：{len(self.state.todo)} 条")
        for text in self.state.todo:
            lines.append(f"  - {text}")
        lines.append(f"- 已有验证结果：{len(self.state.verifications)} 条")
        for text in self.state.verifications:
            lines.append(f"  - {text}")
        lines.append("")
        return "\n".join(lines)


def _extract_spec_ids(text: str) -> list[str]:
    seen: list[str] = []
    for match in SPEC_ID_RE.findall(text or ""):
        if match not in seen:
            seen.append(match)
    return seen


def _assert_sources_exist(items: list[ContextItem], root: Path) -> None:
    missing = [item.source_path for item in items if not (root / item.source_path).exists()]
    if missing:
        raise FileNotFoundError(f"上下文引用了不存在的来源：{missing}")


def build_context(
    *,
    task: str,
    store: MaterialStore,
    state: TaskState,
    root: Path,
    max_specs: int = 6,
    max_code: int = 8,
    max_tests: int = 24,
) -> DevelopmentContext:
    """从资料库与任务状态组装开发上下文。"""

    task_spec_ids = _extract_spec_ids(task)
    task_tokens = set(tokenize(task))

    # 第一轮：按任务描述检索。
    first = store.search(task, limit=40)
    spec_entries = list(first["spec_entries"])

    # 第二轮：把命中的规格条目文本并入查询，提高代码 / 测试召回。
    expanded = task
    for entry in spec_entries[:4]:
        expanded = f"{expanded}\n{entry['entry_id']} {entry['title']} {entry['body']}"
    second = store.search(expanded, limit=60)

    documents = {doc["path"]: doc for doc in second["documents"]}
    symbols = second["symbols"]

    # ---- 规格条目 ----
    base_scores: dict[str, float] = {}
    for entry in first["spec_entries"] + second["spec_entries"]:
        base_scores[entry["entry_id"]] = max(base_scores.get(entry["entry_id"], 0.0), entry["score"])
    spec_scores: dict[str, float] = {
        entry_id: base + (100.0 if entry_id in task_spec_ids else 0.0)
        for entry_id, base in base_scores.items()
    }

    merged_specs: dict[str, dict[str, Any]] = {}
    for entry in first["spec_entries"] + second["spec_entries"]:
        merged_specs[entry["entry_id"]] = entry

    spec_items: list[ContextItem] = []
    for entry_id, score in sorted(spec_scores.items(), key=lambda kv: kv[1], reverse=True)[:max_specs]:
        entry = merged_specs.get(entry_id)
        if entry is None:
            continue
        spec_items.append(
            ContextItem(
                kind="spec",
                identifier=entry_id,
                title=entry["title"],
                source_path=entry["path"],
                detail=entry["body"],
                score=score,
                extra={
                    "spec_version": entry["version"],
                    "revision": entry["revision"],
                    "doc_id": entry["doc_id"],
                    "task_targeted": entry_id in task_spec_ids,
                },
            )
        )

    # ---- 代码文件与符号 ----
    code_docs = [doc for doc in documents.values() if doc["kind"] == "code"]
    code_docs.sort(key=lambda doc: doc["score"], reverse=True)

    symbols_by_path: dict[str, list[dict[str, Any]]] = {}
    for symbol in symbols:
        symbols_by_path.setdefault(symbol["path"], []).append(symbol)

    code_items: list[ContextItem] = []
    for doc in code_docs[:max_code]:
        path = doc["path"]
        file_symbols = symbols_by_path.get(path, [])
        ranked = sorted(file_symbols, key=lambda sym: _symbol_score(sym, task_tokens, task_spec_ids), reverse=True)
        for symbol in ranked[:4]:
            symbol_score = _symbol_score(symbol, task_tokens, task_spec_ids)
            cited = [s for s in (symbol.get("cited_specs") or "").split(",") if s]
            code_items.append(
                ContextItem(
                    kind="code",
                    identifier=symbol["name"],
                    title=f"{symbol['kind']} {symbol['name']}",
                    source_path=path,
                    detail=symbol["signature"],
                    score=doc["score"] + symbol_score,
                    extra={
                        "signature": symbol["signature"],
                        "symbol_kind": symbol["kind"],
                        "line_start": symbol["line_start"],
                        "line_end": symbol["line_end"],
                        "cited_specs": cited,
                        "task_targeted": bool(set(cited) & set(task_spec_ids)),
                        "content": symbol["content"],
                    },
                )
            )

    code_items.sort(key=lambda item: item.score, reverse=True)

    # ---- 测试 ----
    test_docs = [doc for doc in documents.values() if doc["kind"] == "test"]
    test_docs.sort(key=lambda doc: doc["score"], reverse=True)

    test_items: list[ContextItem] = []
    for doc in test_docs:
        path = doc["path"]
        for symbol in symbols_by_path.get(path, []):
            if not symbol["name"].startswith("test"):
                # 只保留测试函数，辅助函数（如 make_order）不是验证用例。
                continue
            cited = [s for s in (symbol.get("cited_specs") or "").split(",") if s]
            is_target = bool(set(cited) & set(task_spec_ids))
            test_items.append(
                ContextItem(
                    kind="test",
                    identifier=symbol["name"],
                    title=symbol["name"],
                    source_path=path,
                    detail=_docstring_of(symbol),
                    score=doc["score"] + (TARGET_SPEC_HIT * 100 if is_target else 0.0),
                    extra={
                        "role": "target" if is_target else "regression",
                        "cited_specs": cited,
                        "line_start": symbol["line_start"],
                        "line_end": symbol["line_end"],
                    },
                )
            )
    test_items.sort(key=lambda item: item.score, reverse=True)
    test_items = test_items[:max_tests]
    test_items.sort(key=lambda item: (item.extra["role"] != "target", item.source_path, item.identifier))

    all_items = spec_items + code_items + test_items
    _assert_sources_exist(all_items, root)

    return DevelopmentContext(
        task=task,
        task_spec_ids=task_spec_ids,
        specs=spec_items,
        code=code_items,
        tests=test_items,
        state=state,
        generated_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    )


def _docstring_of(symbol: dict[str, Any]) -> str:
    content = symbol.get("content") or ""
    lines = content.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(('"""', "'''")):
            return stripped.strip("\"'").strip()
    return ""


def _symbol_score(symbol: dict[str, Any], task_tokens: set[str], task_spec_ids: list[str]) -> float:
    """符号与任务的匹配得分。"""

    score = 0.0
    name_tokens = set(tokenize(symbol["name"]))
    if name_tokens & task_tokens:
        score += 3.0 * len(name_tokens & task_tokens)
    content_tokens = set(tokenize(symbol.get("content") or ""))
    score += 0.5 * len(content_tokens & task_tokens)
    cited = [s for s in (symbol.get("cited_specs") or "").split(",") if s]
    score += 5.0 * len(set(cited) & set(task_spec_ids))
    return score
