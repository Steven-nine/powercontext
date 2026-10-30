"""开发助手循环：上下文 → MiniMax → 补丁 → 应用 → 测试。

这一层把三件事串起来：

1. 用 :mod:`sddctx.context` 组装的上下文调用 MiniMax（OpenAI 兼容接口）；
2. 把 MiniMax 产出的 unified diff 应用到业务工程；
3. 运行目标测试与回归测试，失败则把错误反馈给 MiniMax 重试。

每一步都会写入 PowerContext（任务状态）并留下开发记录。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .config import Settings
from .context import DevelopmentContext
from .diffutil import PatchError, apply_unified_diff
from .minimax_client import ChatResult, MiniMaxClient
from .state import TaskStateStore

SYSTEM_PROMPT = (
    "你是一名资深 Python 工程师，正在执行一次规格驱动开发（SDD）任务。"
    "你会收到：适用的规格条目、需要修改的代码文件与符号、以及用于验证的测试。"
    "请严格按规格实现，并且只修改必要的代码。"
    "输出必须是一个标准的 unified diff（以 `diff --git a/... b/...` 开头），"
    "不要输出任何解释性文字、Markdown 代码围栏或额外文件。"
)

_FENCE_RE = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.DOTALL)


@dataclass
class TestRun:
    """一次测试执行的结果。"""

    command: list[str]
    exit_code: int
    stdout: str
    passed: bool

    def summary(self) -> str:
        tail = "\n".join(self.stdout.strip().splitlines()[-20:])
        return f"$ {' '.join(self.command)}\nexit={self.exit_code}\n{tail}"


@dataclass
class Attempt:
    """一次尝试（调用 MiniMax → 打补丁 → 跑测试）的完整记录。"""

    index: int
    call_id: str
    response_id: str
    model: str
    usage: dict[str, Any]
    patch: str
    applied: list[dict[str, str]] = field(default_factory=list)
    apply_error: str = ""
    test: TestRun | None = None
    accepted: bool = False


def extract_patch(response_text: str) -> str:
    """从模型回复中提取 unified diff。"""

    text = response_text or ""
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1)
    start = text.find("diff --git ")
    if start == -1:
        start = text.find("--- ")
    if start == -1:
        return ""
    body = text[start:]
    lines = body.splitlines()
    collected: list[str] = []
    for line in lines:
        if line.startswith("diff --git ") or line.startswith(("--- ", "+++ ", "@@", "index ", "new file mode", "deleted file mode", "similarity index", "rename ")):
            collected.append(line)
        elif collected and line[:1] in {" ", "+", "-", "\\"}:
            collected.append(line)
        elif collected and line.strip() == "":
            continue
        elif collected:
            break
    return "\n".join(collected).strip() + "\n"


def build_prompt(context: DevelopmentContext, root: Path, feedback: str = "", path_prefix: str = "minimax") -> str:
    """把开发上下文渲染成给 MiniMax 的提示词。"""

    parts: list[str] = []
    parts.append(f"# 开发任务\n\n{context.task}\n")
    parts.append(f"任务点名的规格条目：{', '.join(context.task_spec_ids) or '（无）'}\n")

    parts.append("\n# 适用的规格条目\n")
    for item in context.specs:
        parts.append(f"## {item.identifier} {item.title}\n来源：{item.source_path}（规格版本 {item.extra.get('spec_version', '?')}）\n")
        parts.append(item.detail + "\n")

    code_paths: list[str] = []
    for item in context.code:
        if item.source_path not in code_paths:
            code_paths.append(item.source_path)
    parts.append("\n# 需要修改的代码\n")
    for path in code_paths:
        file_path = root / path
        if not file_path.exists():
            continue
        parts.append(f"## {path}\n```python\n{file_path.read_text(encoding='utf-8')}\n```\n")
    target_paths: list[str] = []
    regression_paths: list[str] = []
    for item in context.tests:
        target = item.extra.get("role") == "target"
        bucket = target_paths if target else regression_paths
        if item.source_path not in bucket:
            bucket.append(item.source_path)
    parts.append("\n# 用于验证的测试\n")
    for path in target_paths + regression_paths:
        file_path = root / path
        if not file_path.exists():
            continue
        role = "目标测试" if path in target_paths else "回归测试"
        parts.append(f"## {path}（{role}）\n```python\n{file_path.read_text(encoding='utf-8')}\n```\n")

    parts.append("\n# 已有任务状态\n")
    state = context.state
    parts.append(f"- 已完成：{state.done or '（无）'}\n")
    parts.append(f"- 待办：{state.todo or '（无）'}\n")
    parts.append(f"- 已有验证结果：{state.verifications or '（无）'}\n")

    parts.append(
        "\n# 输出要求\n"
        "请实现上述规格，使目标测试全部通过，同时保证回归测试继续通过。\n"
        "只输出 unified diff，路径相对于仓库根目录（例如 "
        f"`diff --git a/{path_prefix}/business/shopcalc/pricing.py b/{path_prefix}/business/shopcalc/pricing.py`）。\n"
    )
    if feedback:
        parts.append(f"\n# 上一次尝试失败，请修正\n\n{feedback}\n")
    return "\n".join(parts)


def run_pytest(root: Path, node_ids: Sequence[str] | None = None) -> TestRun:
    """在业务工程目录中执行 pytest。"""

    business_dir = root / "business"
    command = [sys.executable, "-m", "pytest", "-q", "--no-header", "-rA"]
    command.extend(node_ids or [])
    completed = subprocess.run(
        command,
        cwd=str(business_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout = (completed.stdout or "") + (completed.stderr or "")
    return TestRun(
        command=command,
        exit_code=completed.returncode,
        stdout=stdout,
        passed=completed.returncode == 0,
    )


def _snapshot(paths: Sequence[Path]) -> dict[Path, str | None]:
    return {path: (path.read_text(encoding="utf-8") if path.exists() else None) for path in paths}


def _restore(snapshot: dict[Path, str | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            if path.exists():
                path.unlink()
        else:
            path.write_text(content, encoding="utf-8", newline="\n")


class DeveloperAgent:
    """把上下文交给 MiniMax 并驱动一次真实代码修改。"""

    def __init__(self, *, settings: Settings, task: str, task_id: str) -> None:
        self.settings = settings
        self.task = task
        self.task_id = task_id
        self.client = MiniMaxClient(
            base_url=settings.minimax_base_url,
            api_key=settings.minimax_api_key,
            model=settings.minimax_model,
            max_completion_tokens=settings.minimax_max_tokens,
            reasoning_effort=settings.minimax_reasoning_effort,
            log_path=settings.logs_dir / "minimax_calls.jsonl",
        )
        self.state = TaskStateStore(state_db_path=settings.state_db_path, task_id=task_id)

    async def run(self, context: DevelopmentContext, *, max_attempts: int = 3) -> list[Attempt]:
        """执行开发助手循环，返回每次尝试的记录。"""

        root = self.settings.root
        patch_base = self.settings.repo_root
        attempts: list[Attempt] = []
        feedback = ""

        for index in range(1, max_attempts + 1):
            prompt = build_prompt(context, root, feedback, self.settings.path_prefix)
            result: ChatResult = self.client.chat([{"role": "user", "content": prompt}])

            attempt = Attempt(
                index=index,
                call_id=result.call_id,
                response_id=result.response_id,
                model=result.model,
                usage=result.usage,
                patch=extract_patch(result.content),
            )
            if not attempt.patch:
                attempt.apply_error = "模型回复中没有找到 unified diff"
                attempts.append(attempt)
                feedback = attempt.apply_error
                await self.state.remember([("todo", f"第 {index} 次尝试未产出补丁，需要重试")])
                continue

            touched = [
                patch_base / line.split(" b/")[-1].strip()
                for line in attempt.patch.splitlines()
                if line.startswith("diff --git ")
            ]
            snapshot = _snapshot(touched)
            try:
                attempt.applied = apply_unified_diff(attempt.patch, patch_base)
            except PatchError as exc:
                attempt.apply_error = str(exc)
                attempts.append(attempt)
                feedback = f"补丁无法应用：{exc}"
                await self.state.remember([("todo", f"第 {index} 次尝试补丁应用失败：{exc}")])
                continue

            attempt.test = run_pytest(root)
            attempt.accepted = attempt.test.passed
            attempts.append(attempt)

            if attempt.accepted:
                await self.state.remember(
                    [
                        ("completed", f"MiniMax 第 {index} 次尝试产出补丁并通过全部测试"),
                        ("verification", f"pytest 全量测试通过（exit={attempt.test.exit_code}）"),
                    ]
                )
                await self.state.checkpoint(
                    objective=self.task,
                    state=[
                        f"已按 {', '.join(context.task_spec_ids) or '规格'} 修改 "
                        + ", ".join(item["path"] for item in attempt.applied),
                        f"目标测试与回归测试全部通过（exit={attempt.test.exit_code}）",
                    ],
                    next_action="提交代码差异与验证记录",
                    disposition="complete",
                )
                break

            _restore(snapshot)
            feedback = f"补丁已应用但测试未通过：\n{attempt.test.summary()}"
            await self.state.remember([("todo", f"第 {index} 次尝试测试失败，需要继续修正")])

        return attempts


def copy_snapshot_tree(source: Path, destination: Path) -> None:
    """把目录复制成快照（生成"修改前 / 修改后"代码快照）。"""

    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
