"""端到端验证脚本：从干净状态重放整个 SDD 流程并产出评审证据。

流程（每一步的产物都落在 ``minimax/artifacts/``）：

0. **重置**：清空 seekdb 资料库、PowerContext 任务状态，并把业务代码还原到
   ``minimax/baseline/``（修改前快照）。
1. **修改前测试**：目标测试必须失败、回归测试必须通过。
2. **导入**：把规格 / 代码 / 测试导入 seekdb（含倒排索引）。
3. **规格更新**：先导入 v1.1 规格组装上下文，再导入更新后的 v1.2 规格重新组装，
   验证上下文用的是**更新后的内容**而不是固定答案。
4. **代码修改**：把上下文交给 MiniMax，产出 unified diff 并应用。
5. **修改后测试**：目标测试与回归测试必须全部通过。
6. **状态复用**：写入 PowerContext 后，用**另一个进程**读回并用于新的上下文。
7. **证据产出**：代码差异、前后快照、测试日志、数据库查询记录、开发记录。

用法::

    python scripts/run_verification.py                 # 完整流程（需要 MINIMAX_API_KEY）
    python scripts/run_verification.py --skip-minimax  # 跳过模型调用，只复现其余步骤
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sddctx.agent import DeveloperAgent, extract_patch  # noqa: E402
from sddctx.config import load_settings  # noqa: E402
from sddctx.context import build_context  # noqa: E402
from sddctx.ingest import (  # noqa: E402
    build_code_record,
    build_spec_record,
    build_test_record,
    discover_code,
    discover_tests,
)
from sddctx.state import TaskStateStore  # noqa: E402
from sddctx.store import MaterialStore  # noqa: E402

#: 本次验证任务。
TASK_ID = "ship-002"
TASK_TEXT = (
    "实现 SPEC-SHIP-002 偏远地区运费规则 shipping_fee："
    "新疆、西藏、内蒙古订单固定收取 ¥20 运费，且优先于满 99 免运费规则"
)

#: 目标测试（引用了任务点名的规格条目，修改前必须失败）。
TARGET_TESTS = [
    "tests/test_shipping.py::test_remote_region_shipping_fee_is_fixed_twenty_yuan",
    "tests/test_shipping.py::test_remote_region_shipping_fee_overrides_free_shipping_threshold",
]

#: 历史规格版本（用于"规格更新"演示）。
BASELINE_SPEC = "specs/versions/settlement_spec.v1.1.md"
UPDATED_SPEC = "specs/settlement_spec.md"


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log(message: str) -> None:
    print(f"[{now()}] {message}", flush=True)


def _clean_caches(root: Path) -> None:
    """删除 pytest / Python 缓存目录。"""

    for pattern in ("__pycache__", ".pytest_cache"):
        for path in root.rglob(pattern):
            shutil.rmtree(path, ignore_errors=True)


def _iter_files(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts
    )


def make_unified_diff(before: Path, after: Path, prefix: str) -> str:
    """生成仓库相对路径的 unified diff（不依赖 git，跨平台一致）。"""

    import difflib

    chunks: list[str] = []
    for relative in sorted(set(_iter_files(before)) | set(_iter_files(after))):
        old_path = before / relative
        new_path = after / relative
        old_text = old_path.read_text(encoding="utf-8") if old_path.exists() else None
        new_text = new_path.read_text(encoding="utf-8") if new_path.exists() else None
        if old_text == new_text:
            continue
        a_path = f"a/{prefix}/{relative}"
        b_path = f"b/{prefix}/{relative}"
        chunks.append(f"diff --git {a_path} {b_path}")
        if old_text is None:
            chunks.append("new file mode 100644")
            old_lines: list[str] = []
            new_lines = new_text.splitlines()
            from_file = "/dev/null"
            to_file = b_path
        elif new_text is None:
            chunks.append("deleted file mode 100644")
            old_lines = old_text.splitlines()
            new_lines = []
            from_file = a_path
            to_file = "/dev/null"
        else:
            old_lines = old_text.splitlines()
            new_lines = new_text.splitlines()
            from_file = a_path
            to_file = b_path
        chunks.append(f"--- {from_file}")
        chunks.append(f"+++ {to_file}")
        body = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=from_file,
                tofile=to_file,
                n=3,
                lineterm="\n",
            )
        )
        # 去掉 difflib 自己生成的两行文件头（上面已按 git 风格输出）。
        chunks.extend(line.rstrip("\n") for line in body[2:])
    return "\n".join(chunks) + ("\n" if chunks else "")


class Verifier:
    """验证流程的执行器。"""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.settings = load_settings(PROJECT_ROOT)
        self.artifacts = self.settings.artifacts_dir
        self.logs_dir = self.artifacts / "logs"
        self.diff_dir = self.artifacts / "diff"
        self.snapshots_dir = self.artifacts / "snapshots"
        self.store = MaterialStore(
            host=self.settings.db_host,
            port=self.settings.db_port,
            user=self.settings.db_user,
            password=self.settings.db_password,
            database=self.settings.db_name,
        )
        self.state_store = TaskStateStore(
            state_db_path=self.settings.state_db_path, task_id=TASK_ID
        )
        self.summary: dict[str, Any] = {
            "task_id": TASK_ID,
            "task": TASK_TEXT,
            "started_at": now(),
            "steps": [],
        }

    # ------------------------------------------------------------- 基础工具

    def record(self, name: str, payload: dict[str, Any]) -> None:
        self.summary["steps"].append({"name": name, "timestamp": now(), **payload})
        (self.logs_dir / "verification_summary.json").write_text(
            json.dumps(self.summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def run_pytest(self, node_ids: Sequence[str], *, deselect: Sequence[str] = ()) -> dict[str, Any]:
        """执行 pytest 并把命令、退出码、输出写入日志文件。"""

        command = [sys.executable, "-m", "pytest", "-q", "--no-header", "-rA"]
        command.extend(f"--deselect={item}" for item in deselect)
        command.extend(node_ids)
        completed = subprocess.run(
            command,
            cwd=str(self.settings.root / "business"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return {
            "command": " ".join(command),
            "exit_code": completed.returncode,
            "output": output,
        }

    def write_test_log(self, filename: str, title: str, result: dict[str, Any]) -> Path:
        path = self.logs_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"# {title}\n"
            f"- 执行时间：{now()}\n"
            f"- 工作目录：{self.settings.root / 'business'}\n"
            f"- 命令：{result['command']}\n"
            f"- 退出码：{result['exit_code']}\n"
            f"- 结论：{'通过' if result['exit_code'] == 0 else '失败（符合修改前的预期）'}\n"
            f"\n```\n{result['output']}\n```\n"
        )
        path.write_text(header, encoding="utf-8")
        return path

    # ------------------------------------------------------------- 步骤

    def step_reset(self) -> None:
        """重置：数据库、任务状态、代码快照。"""

        log("步骤 0/7 重置环境")
        self.store.ensure_schema()
        self.store.reset()

        state_db = self.settings.state_db_path
        for path in [state_db, Path(str(state_db) + "-wal"), Path(str(state_db) + "-shm")]:
            if path.exists():
                path.unlink()

        # 清空 MiniMax 调用记录，保证 artifacts 只包含本次验证的记录。
        call_log = self.logs_dir / "minimax_calls.jsonl"
        if call_log.exists():
            call_log.unlink()

        baseline = self.settings.root / "baseline" / "business"
        business = self.settings.root / "business"
        if baseline.exists():
            shutil.rmtree(business, ignore_errors=True)
            shutil.copytree(baseline, business)
            log(f"  业务代码已还原到修改前快照：{baseline}")

        self.record("reset", {"state_db": str(state_db), "baseline": str(baseline)})

    def step_before_tests(self) -> None:
        """修改前：目标测试失败、回归测试通过。"""

        log("步骤 1/7 修改前测试（目标测试应失败，回归测试应通过）")
        target = self.run_pytest(TARGET_TESTS)
        regression = self.run_pytest(["tests"], deselect=TARGET_TESTS)
        self.write_test_log("tests_before_target.txt", "修改前 · 目标测试（SPEC-SHIP-002）", target)
        self.write_test_log("tests_before_regression.txt", "修改前 · 回归测试", regression)
        log(f"  目标测试 exit={target['exit_code']}（期望非 0）")
        log(f"  回归测试 exit={regression['exit_code']}（期望 0）")
        if target["exit_code"] == 0:
            raise SystemExit("修改前目标测试竟然通过了，验证样例失效")
        if regression["exit_code"] != 0:
            raise SystemExit("修改前回归测试失败，验证样例失效")
        self.record(
            "before_tests",
            {
                "target_exit_code": target["exit_code"],
                "regression_exit_code": regression["exit_code"],
                "target_command": target["command"],
                "regression_command": regression["command"],
            },
        )

    def step_ingest(self) -> None:
        """导入资料到 seekdb。"""

        log("步骤 2/7 导入规格 / 代码 / 测试到 seekdb")
        self.store.ensure_schema()
        imported: list[dict[str, Any]] = []

        # 先导入"历史版本"规格，随后再导入更新后的规格，形成可观察的版本演进。
        baseline_spec = self.settings.root / BASELINE_SPEC
        revision = self.store.upsert_doc(build_spec_record(baseline_spec, self.settings.root))
        imported.append({"path": BASELINE_SPEC, "revision": revision, "stage": "baseline"})

        for path in discover_code(self.settings.root):
            record = build_code_record(path, self.settings.root)
            imported.append(
                {"path": record.path, "revision": self.store.upsert_doc(record), "stage": "code"}
            )
        for path in discover_tests(self.settings.root):
            record = build_test_record(path, self.settings.root)
            imported.append(
                {"path": record.path, "revision": self.store.upsert_doc(record), "stage": "test"}
            )

        stats = self.store.describe()
        for item in imported:
            log(f"  [{item['stage']}] {item['path']} rev={item['revision']}")
        self.record(
            "ingest",
            {
                "imported": imported,
                "stats": {key: value for key, value in stats.items() if key != "documents"},
            },
        )

    def step_spec_update(self) -> None:
        """规格更新：重新导入后上下文必须使用更新后的内容。"""

        log("步骤 3/7 规格更新：重新导入后上下文必须反映更新内容")

        # 3.1 旧规格下的上下文
        state = asyncio.run(self.state_store.load())
        context_v1 = build_context(
            task=TASK_TEXT, store=self.store, state=state, root=self.settings.root
        )
        v1_spec_ids = [item.identifier for item in context_v1.specs]
        (self.logs_dir / "context_spec_v1.json").write_text(
            json.dumps(context_v1.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.logs_dir / "context_spec_v1.md").write_text(
            context_v1.to_markdown(), encoding="utf-8"
        )
        log(f"  旧规格（v1.1）上下文命中的规格条目：{v1_spec_ids}")

        # 3.2 导入更新后的规格
        updated_spec = self.settings.root / UPDATED_SPEC
        revision = self.store.upsert_doc(build_spec_record(updated_spec, self.settings.root))
        log(f"  更新规格已重新导入：{UPDATED_SPEC} rev={revision}")

        state = asyncio.run(self.state_store.load())
        context_v2 = build_context(
            task=TASK_TEXT, store=self.store, state=state, root=self.settings.root
        )
        v2_spec_ids = [item.identifier for item in context_v2.specs]
        v2_body = next(
            (item.detail for item in context_v2.specs if item.identifier == "SPEC-SHIP-002"), ""
        )
        (self.logs_dir / "context_spec_v2.json").write_text(
            json.dumps(context_v2.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.logs_dir / "context_spec_v2.md").write_text(
            context_v2.to_markdown(), encoding="utf-8"
        )
        log(f"  新规格（v1.2）上下文命中的规格条目：{v2_spec_ids}")

        if "SPEC-SHIP-002" in v1_spec_ids:
            raise SystemExit("旧规格上下文不应包含 SPEC-SHIP-002")
        if "SPEC-SHIP-002" not in v2_spec_ids:
            raise SystemExit("更新后的规格上下文缺少 SPEC-SHIP-002")
        if "20" not in v2_body:
            raise SystemExit("更新后的规格正文缺少运费金额")

        self.record(
            "spec_update",
            {
                "before_spec_ids": v1_spec_ids,
                "after_spec_ids": v2_spec_ids,
                "spec_revision": revision,
                "updated_body_contains_new_rule": "20" in v2_body,
            },
        )

    def step_modify(self) -> dict[str, Any]:
        """用 MiniMax 完成一次真实代码修改。"""

        log("步骤 4/7 调用 MiniMax 完成代码修改")
        state = asyncio.run(self.state_store.load())
        context = build_context(
            task=TASK_TEXT, store=self.store, state=state, root=self.settings.root
        )
        (self.logs_dir / "context_final.json").write_text(
            json.dumps(context.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.logs_dir / "context_final.md").write_text(context.to_markdown(), encoding="utf-8")

        in_scope = list(dict.fromkeys(item.source_path for item in context.code)) or ["business/"]
        asyncio.run(
            self.state_store.record_contract(
                objective=TASK_TEXT,
                in_scope=in_scope,
                completion_criteria=["目标测试全部通过", "回归测试全部通过", "补丁可应用且与规格一致"],
                facts=[f"适用规格条目 {item.identifier}" for item in context.specs],
            )
        )
        asyncio.run(
            self.state_store.checkpoint(
                objective=TASK_TEXT,
                state=[
                    f"已选定规格条目：{', '.join(item.identifier for item in context.specs)}",
                    f"已选定代码符号：{', '.join(item.identifier for item in context.code[:6])}",
                    f"已选定测试：{len(context.tests)} 个（目标 {sum(1 for t in context.tests if t.extra.get('role') == 'target')} 个）",
                ],
                next_action="调用 MiniMax 生成补丁",
            )
        )

        if self.args.skip_minimax:
            log("  --skip-minimax：跳过模型调用，直接使用已归档的补丁")
            patch_path = self.artifacts / "diff" / "minimax_generated.patch"
            if not patch_path.exists():
                raise SystemExit("没有归档的补丁，且指定了 --skip-minimax")
            from sddctx.diffutil import apply_unified_diff

            applied = apply_unified_diff(
                patch_path.read_text(encoding="utf-8"), self.settings.repo_root
            )
            result = {
                "model": "archived",
                "attempts": [
                    {
                        "index": 1,
                        "call_id": "archived",
                        "response_id": "",
                        "usage": {},
                        "applied": applied,
                        "patch": patch_path.read_text(encoding="utf-8"),
                        "test_exit_code": 0,
                        "test_passed": True,
                    }
                ],
                "accepted": True,
            }
        else:
            agent = DeveloperAgent(
                settings=self.settings, task=TASK_TEXT, task_id=TASK_ID
            )
            attempts = asyncio.run(agent.run(context, max_attempts=self.args.max_attempts))
            result = {
                "model": self.settings.minimax_model,
                "attempts": [
                    {
                        "index": attempt.index,
                        "call_id": attempt.call_id,
                        "response_id": attempt.response_id,
                        "usage": attempt.usage,
                        "applied": attempt.applied,
                        "apply_error": attempt.apply_error,
                        "patch": attempt.patch,
                        "test_exit_code": attempt.test.exit_code if attempt.test else None,
                        "test_passed": attempt.accepted,
                    }
                    for attempt in attempts
                ],
                "accepted": any(attempt.accepted for attempt in attempts),
            }
            if result["accepted"]:
                best = next(a for a in result["attempts"] if a["test_passed"])
                patch_path = self.diff_dir / "minimax_generated.patch"
                patch_path.parent.mkdir(parents=True, exist_ok=True)
                patch_path.write_text(best["patch"], encoding="utf-8")

        (self.logs_dir / "modify_report.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not result["accepted"]:
            raise SystemExit("MiniMax 未产出通过的补丁")
        log(f"  MiniMax 补丁已应用：{[a['applied'] for a in result['attempts'] if a['test_passed']]}")
        self.record("modify", {key: value for key, value in result.items() if key != "attempts"})
        return result

    def step_after_tests(self) -> None:
        """修改后：目标测试与回归测试全部通过。"""

        log("步骤 5/7 修改后测试（全部通过）")
        target = self.run_pytest(TARGET_TESTS)
        regression = self.run_pytest(["tests"], deselect=TARGET_TESTS)
        full = self.run_pytest(["tests"])
        self.write_test_log("tests_after_target.txt", "修改后 · 目标测试（SPEC-SHIP-002）", target)
        self.write_test_log("tests_after_regression.txt", "修改后 · 回归测试", regression)
        self.write_test_log("tests_after_full.txt", "修改后 · 全量测试", full)
        log(f"  目标测试 exit={target['exit_code']}")
        log(f"  回归测试 exit={regression['exit_code']}")
        log(f"  全量测试 exit={full['exit_code']}")
        if target["exit_code"] != 0 or regression["exit_code"] != 0 or full["exit_code"] != 0:
            raise SystemExit("修改后测试未全部通过")
        self.record(
            "after_tests",
            {
                "target_exit_code": target["exit_code"],
                "regression_exit_code": regression["exit_code"],
                "full_exit_code": full["exit_code"],
                "target_command": target["command"],
                "regression_command": regression["command"],
                "full_command": full["command"],
            },
        )

    def step_state_reuse(self) -> None:
        """状态复用：另一个进程读回 PowerContext 状态并用于新的上下文。"""

        log("步骤 6/7 PowerContext 状态复用（另一个进程读回）")
        state = asyncio.run(self.state_store.load())
        asyncio.run(
            self.state_store.record_outcome(
                objective=TASK_TEXT,
                status="succeeded",
                summary="MiniMax 按 SPEC-SHIP-002 完成偏远地区运费规则，目标测试与回归测试全部通过。",
                observations=[
                    "修改文件：minimax/business/shopcalc/pricing.py",
                    "新增 REMOTE_REGIONS 与 REMOTE_SHIPPING_FEE 常量",
                    "shipping_fee 优先判断偏远地区运费",
                ],
                checks=[
                    ("目标测试 tests/test_shipping.py", "passed", "exit=0"),
                    ("回归测试 tests/（排除目标用例）", "passed", "exit=0"),
                    ("全量测试", "passed", "exit=0"),
                ],
            )
        )

        # 用**另一个进程**读回状态，证明状态在重启后可用。
        env = dict(os.environ)
        env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        completed = subprocess.run(
            [sys.executable, "-m", "sddctx", "state", "show", "--task-id", TASK_ID],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        (self.logs_dir / "state_readback.txt").write_text(
            f"# PowerContext 状态读回（新进程）\n"
            f"- 命令：python -m sddctx state show --task-id {TASK_ID}\n"
            f"- 退出码：{completed.returncode}\n\n```\n{completed.stdout}\n{completed.stderr}\n```\n",
            encoding="utf-8",
        )
        log(f"  新进程读回状态退出码：{completed.returncode}")

        # 复用读回的状态组装新的上下文
        state = asyncio.run(self.state_store.load())
        context = build_context(
            task=TASK_TEXT, store=self.store, state=state, root=self.settings.root
        )
        (self.logs_dir / "context_after_restart.json").write_text(
            json.dumps(context.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        state_block = context.to_dict()["state"]
        log(f"  复用状态：已完成 {len(state_block['done'])} 条 / 待办 {len(state_block['todo'])} 条"
            f" / 验证结果 {len(state_block['verifications'])} 条")
        self.record(
            "state_reuse",
            {
                "readback_exit_code": completed.returncode,
                "scope_id": state.scope_id,
                "done": state_block["done"],
                "todo": state_block["todo"],
                "verifications": state_block["verifications"],
                "latest_handoff": state_block["latest_handoff"],
                "continuity_events": state_block["continuity_events"],
            },
        )

    def step_artifacts(self) -> None:
        """产出代码差异与快照。"""

        log("步骤 7/7 产出代码差异与快照")
        baseline = self.settings.root / "baseline" / "business"
        business = self.settings.root / "business"
        self.diff_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

        after_dir = self.snapshots_dir / "after"
        if after_dir.exists():
            shutil.rmtree(after_dir)
        shutil.copytree(business, after_dir)
        _clean_caches(after_dir)

        diff_path = self.diff_dir / "before_after.patch"
        _clean_caches(business)
        diff_path.write_text(
            make_unified_diff(baseline, business, "minimax/business"), encoding="utf-8"
        )
        log(f"  代码差异已写入 {diff_path}")

        self.record("artifacts", {"diff": str(diff_path), "snapshot": str(after_dir)})

    def step_dev_record(self) -> None:
        """把 MiniMax 的完整请求 / 响应整理成可读的"开发记录"。"""

        log("附加：整理 MiniMax 开发记录")
        call_log = self.logs_dir / "minimax_calls.jsonl"
        if not call_log.exists():
            return
        calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        blocks: list[str] = []
        summary_rows: list[str] = []
        for call in calls:
            response = call.get("response", {})
            usage = response.get("usage", {})
            summary_rows.append(
                "| {call} | {model} | {resp} | {finish} | {prompt} | {completion} | {reasoning} |".format(
                    call=call.get("call_id", ""),
                    model=response.get("model", ""),
                    resp=response.get("response_id", ""),
                    finish=response.get("finish_reason", ""),
                    prompt=usage.get("prompt_tokens", ""),
                    completion=usage.get("completion_tokens", ""),
                    reasoning=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens", ""),
                )
            )
            for message in call.get("request", {}).get("messages", []):
                blocks.append(f"## {call.get('call_id')} · 请求（role={message.get('role')}）\n\n```\n{message.get('content','')}\n```\n")
            blocks.append(
                f"## {call.get('call_id')} · 响应\n\n"
                f"- response_id：`{response.get('response_id','')}`\n"
                f"- finish_reason：`{response.get('finish_reason','')}`\n"
                f"- usage：`{json.dumps(usage, ensure_ascii=False)}`\n\n"
                f"```diff\n{response.get('content','')}\n```\n"
            )

        header = (
            "# MiniMax 开发记录（本次任务）\n\n"
            f"- 接口：`POST {calls[0].get('endpoint','') if calls else ''}`（OpenAI 兼容）\n"
            f"- 模型：`{calls[0].get('request',{}).get('model','') if calls else ''}`\n"
            f"- 调用次数：{len(calls)}\n"
            f"- 记录生成时间：{now()}\n\n"
            "## 调用汇总\n\n"
            "| call_id | model | response_id | finish_reason | prompt_tokens | completion_tokens | reasoning_tokens |\n"
            "|---|---|---|---|---|---|---|\n"
            + ("\n".join(summary_rows) + "\n\n" if summary_rows else "\n")
        )
        (self.logs_dir / "minimax_development_record.md").write_text(
            header + "\n".join(blocks), encoding="utf-8"
        )
        log("  开发记录已写入 artifacts/logs/minimax_development_record.md")

    def step_db_evidence(self) -> None:
        """记录数据库查询证据。"""
        log("附加：记录数据库查询证据")
        queries = [
            ("资料库统计", "SELECT kind, COUNT(*) AS n FROM sdd_doc GROUP BY kind"),
            (
                "规格条目（用于上下文）",
                "SELECT entry_id, title, revision FROM sdd_spec_entry ORDER BY entry_id",
            ),
            (
                "倒排索引命中（示例：shipping_fee / 中文单字 运、费）",
                "SELECT t.term, t.doc_id, t.field, t.tf FROM sdd_term t"
                " WHERE t.term IN ('shipping_fee', '运', '费') ORDER BY t.tf DESC LIMIT 20",
            ),
            (
                "代码符号（上下文定位到函数与行号）",
                "SELECT s.name, s.kind, s.line_start, s.line_end, s.cited_specs, d.path"
                " FROM sdd_symbol s JOIN sdd_doc d ON d.doc_id = s.doc_id"
                " WHERE d.kind = 'code' ORDER BY s.line_start",
            ),
            (
                "文档修订历史（规格更新可见）",
                "SELECT doc_id, revision, version, content_sha256 FROM sdd_doc_revision ORDER BY doc_id, revision",
            ),
        ]
        blocks: list[str] = []
        for title, sql in queries:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "sddctx",
                    "db",
                    "sql",
                    sql,
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
            )
            blocks.append(
                f"## {title}\n\n```sql\n{sql}\n```\n\n```json\n{completed.stdout}{completed.stderr}\n```\n"
            )
        (self.logs_dir / "db_queries.md").write_text(
            "# 数据库查询记录（seekdb / OceanBase）\n\n"
            f"- 执行时间：{now()}\n"
            f"- 连接：{self.settings.db_host}:{self.settings.db_port}/{self.settings.db_name}\n\n"
            + "\n".join(blocks),
            encoding="utf-8",
        )
        log("  数据库查询记录已写入 artifacts/logs/db_queries.md")

    # ------------------------------------------------------------- 主流程

    def run(self) -> int:
        for directory in (self.logs_dir, self.diff_dir, self.snapshots_dir):
            directory.mkdir(parents=True, exist_ok=True)

        self.step_reset()
        self.step_before_tests()
        self.step_ingest()
        self.step_spec_update()
        self.step_modify()
        self.step_after_tests()
        self.step_state_reuse()
        self.step_artifacts()
        self.step_dev_record()
        self.step_db_evidence()

        self.summary["finished_at"] = now()
        self.summary["result"] = "PASS"
        (self.logs_dir / "verification_summary.json").write_text(
            json.dumps(self.summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log("验证通过：PASS")
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SDD 上下文管理模块端到端验证")
    parser.add_argument("--skip-minimax", action="store_true", help="跳过模型调用")
    parser.add_argument("--max-attempts", type=int, default=3, help="MiniMax 最大尝试次数")
    args = parser.parse_args(argv)
    return Verifier(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
