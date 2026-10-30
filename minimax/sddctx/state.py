"""基于 PowerContext 的任务状态存储。

模块把一次 SDD 任务的进展写入 PowerContext：

* **Work contract**：任务目标、范围、完成判据；
* **Memory 条目**：已完成事项、待办事项、已有验证结果；
* **Handoff 里程碑**：每个阶段的检查点（可跨进程读取）；
* **Task outcome**：本次尝试的结论与逐项检查结果。

状态写入 SQLite 持久化的 PowerContext 实例（PowerContext 内置 relational 后端），
进程重启后用同一个 ``external_id`` 绑定键即可读回。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    RememberMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeBindingKey, ScopeDraft
from powercontext.builtin.work import (
    CreateWorkContract,
    CurrentWorkHandoff,
    HandoffCurrentWork,
    RecordTaskOutcome,
    TaskCheck,
    TaskOutcome,
    WorkClaim,
    WorkContract,
)

#: 任务在 PowerContext 中的绑定命名空间。
BINDING_INTEGRATION = "competition"
BINDING_KIND = "minimax-sdd"


@dataclass
class TaskState:
    """从 PowerContext 读回的任务状态快照。"""

    scope_id: str
    objective: str = ""
    done: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    verifications: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    latest_handoff: dict[str, Any] = field(default_factory=dict)
    continuity_events: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "objective": self.objective,
            "done": self.done,
            "todo": self.todo,
            "verifications": self.verifications,
            "decisions": self.decisions,
            "facts": self.facts,
            "latest_handoff": self.latest_handoff,
            "continuity_events": self.continuity_events,
        }


class TaskStateStore:
    """PowerContext 任务状态存储。"""

    def __init__(self, *, state_db_path: Path, task_id: str, integration: str = BINDING_INTEGRATION) -> None:
        self.state_db_path = Path(state_db_path)
        self.task_id = task_id
        self.integration = integration
        self.state_db_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- 内部工具

    def _config(self) -> BuiltinConfig:
        url = f"sqlite+aiosqlite:///{self.state_db_path.as_posix()}"
        return BuiltinConfig(database=SQLiteConfig(url=url))

    def _binding_key(self) -> ScopeBindingKey:
        return ScopeBindingKey(integration=self.integration, kind=BINDING_KIND, external_id=self.task_id)

    @staticmethod
    def _memory_app(runtime):
        """返回 Memory 应用；本模块依赖 ``powercontext==1.2.0`` 的 ``runtime.memory`` 接口。"""

        memory = getattr(runtime, "memory", None)
        if memory is None:
            raise RuntimeError(
                "当前安装的 powercontext 不提供 runtime.memory 接口；"
                "请按 requirements.txt 安装 powercontext[builtin]==1.2.0。"
            )
        return memory

    async def _resolve_scope(self, runtime) -> str:
        """按绑定键解析 Scope；不存在时创建并绑定。"""

        try:
            resolved = await runtime.scopes.resolve_binding(binding_keys=(self._binding_key(),))
            return resolved.scope_id
        except Exception:  # noqa: BLE001 - 绑定不存在时创建新的 scope
            scope = await runtime.scopes.create(
                ScopeDraft(
                    title=f"minimax-sdd:{self.task_id}",
                    summary=f"SDD 上下文管理任务 {self.task_id}",
                    idempotency_key=f"minimax-sdd:{self.task_id}",
                )
            )
            await runtime.scopes.bind(self._binding_key(), scope.scope_id)
            return scope.scope_id

    # ------------------------------------------------------------- 写入接口

    async def ensure_scope(self) -> str:
        """确保 Scope 存在（供上下文组装阶段读取状态）。"""

        async with open_builtin_runtime(self._config()) as runtime:
            return await self._resolve_scope(runtime)

    async def record_contract(
        self,
        *,
        objective: str,
        in_scope: Sequence[str],
        completion_criteria: Sequence[str],
        facts: Sequence[str] = (),
    ) -> str:
        """写入工作契约（任务目标、范围、完成判据）。"""

        async with open_builtin_runtime(self._config()) as runtime:
            scope_id = await self._resolve_scope(runtime)
            await runtime.work.for_scope(scope_id).create_contract(
                CreateWorkContract(
                    source_id=f"{self.task_id}:contract",
                    contract=WorkContract(
                        objective=objective,
                        in_scope=tuple(in_scope),
                        completion_criteria=tuple(completion_criteria),
                        facts=tuple(WorkClaim(text=text) for text in facts),
                    ),
                )
            )
            return scope_id

    async def remember(self, entries: Sequence[tuple[str, str]]) -> None:
        """写入 Memory 条目（kind, text）。"""

        if not entries:
            return
        async with open_builtin_runtime(self._config()) as runtime:
            scope_id = await self._resolve_scope(runtime)
            await self._memory_app(runtime).for_scope(scope_id).remember(
                RememberMemoryRequest(
                    entries=tuple(MemoryEntryInput(kind=kind, text=text) for kind, text in entries)
                )
            )

    async def checkpoint(
        self,
        *,
        objective: str,
        state: Sequence[str],
        next_action: str,
        disposition: str = "continuable",
        omissions: Sequence[str] = (),
    ) -> None:
        """提交一个 Handoff 里程碑（可跨进程读回）。"""

        async with open_builtin_runtime(self._config()) as runtime:
            scope_id = await self._resolve_scope(runtime)
            prepared = await runtime.work.for_scope(scope_id).handoff_current(
                HandoffCurrentWork(
                    source_id=f"{self.task_id}:handoff:{len(state)}:{abs(hash(next_action)) % 10**8}",
                    handoff=CurrentWorkHandoff(
                        objective=objective,
                        state=tuple(WorkClaim(text=text) for text in state),
                        disposition=disposition,
                        next_action=WorkClaim(text=next_action),
                        omissions=tuple(omissions),
                    ),
                )
            )
            await runtime.handoff.for_scope(scope_id).commit(prepared.handoff)

    async def record_outcome(
        self,
        *,
        objective: str,
        status: str,
        summary: str,
        observations: Sequence[str],
        checks: Sequence[tuple[str, str, str]] = (),
        remaining_work: Sequence[str] = (),
    ) -> None:
        """记录本次任务尝试的结论。"""

        async with open_builtin_runtime(self._config()) as runtime:
            scope_id = await self._resolve_scope(runtime)
            await runtime.work.for_scope(scope_id).record_outcome(
                RecordTaskOutcome(
                    source_id=f"{self.task_id}:outcome:{abs(hash(summary)) % 10**8}",
                    outcome=TaskOutcome(
                        objective=objective,
                        status=status,
                        summary=summary,
                        observations=tuple(WorkClaim(text=text) for text in observations),
                        checks=tuple(
                            TaskCheck(name=name, status=check_status, details=details)
                            for name, check_status, details in checks
                        ),
                        remaining_work=tuple(remaining_work),
                    ),
                )
            )

    async def capture_source(self, source_id: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        """把一段原始证据（上下文、补丁、测试输出）作为 Source 留档。"""

        async with open_builtin_runtime(self._config()) as runtime:
            scope_id = await self._resolve_scope(runtime)
            await runtime.sources.for_scope(scope_id).capture(
                CaptureSource(source_id=source_id, content=content, metadata=metadata or {})
            )

    # ------------------------------------------------------------- 读取接口

    async def load(self) -> TaskState:
        """读回任务状态（进程重启后依然可用）。"""

        async with open_builtin_runtime(self._config()) as runtime:
            scope_id = await self._resolve_scope(runtime)
            state = TaskState(scope_id=scope_id)

            page = await self._memory_app(runtime).for_scope(scope_id).list()
            for entry in page.entries:
                kind = entry.entry.kind
                text = entry.entry.text
                if kind == "todo":
                    state.todo.append(text)
                elif kind == "completed":
                    state.done.append(text)
                elif kind == "verification":
                    state.verifications.append(text)
                elif kind == "decision":
                    state.decisions.append(text)
                else:
                    state.facts.append(text)

            try:
                resolution = await runtime.handoff.for_scope(scope_id).continue_latest()
            except Exception:  # noqa: BLE001 - 尚无里程碑
                resolution = None
            if resolution is not None and resolution.content is not None:
                content = resolution.content
                state.latest_handoff = {
                    "objective": content.objective,
                    "disposition": content.disposition,
                    "state": [claim.text for claim in content.state],
                    "next_action": content.next_action.text if content.next_action else "",
                    "omissions": list(content.omissions),
                    "status": getattr(resolution, "status", ""),
                }
                state.objective = content.objective

            try:
                continuity = await runtime.work.for_scope(scope_id).continuity()
                state.continuity_events = len(continuity.events)
            except Exception:  # noqa: BLE001
                state.continuity_events = 0

            return state

    async def dump(self) -> str:
        """返回可读的状态摘要。"""

        state = await self.load()
        return json.dumps(state.to_dict(), ensure_ascii=False, indent=2)


def run_sync(coro):
    """在同步上下文中执行协程（CLI 使用）。"""

    return asyncio.run(coro)
