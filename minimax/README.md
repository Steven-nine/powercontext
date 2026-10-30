# MiniMax 赛题作品：规有所依的 SDD 上下文模块

面向「规有所依，面向软件持续演进的 SDD 上下文管理系统」的可复现最小作品。上下文模块根据开发任务，从 seekdb 中检索当前有效的规格、相关代码和测试，交给 MiniMax Code 完成一次真实代码修改，并用 PowerContext 持久化任务状态。

## 目录结构

```text
minimax/
  src/mmctx/            上下文模块（CLI）
  demo-app/             业务示例工程（规格、代码、测试）
  scripts/              安装、演示、自检脚本
  evidence/             验收证据（日志、补丁、说明）
  pyproject.toml
```

## 环境要求

- Linux x86_64 或 WSL2，Python 3.12，`uv`
- PowerContext Server（默认 `http://127.0.0.1:8000`）
- MiniMax Code CLI（`mcode`，用于真实代码修改）

本作品使用 seekdb 嵌入式模式（`pylibseekdb`），不需要单独部署数据库服务；PowerContext 只使用显式记忆能力，因此不需要配置生成或向量模型。

## 安装与启动

```bash
bash scripts/setup.sh
```

启动 PowerContext Server（在任意 PowerContext 检出目录）：

```bash
uv run powercontext config init --template -o .env
uv run powercontext server run --env-file .env
```

确认服务就绪：

```bash
uv run powercontext ready
```

## 验证样例

任务：为订单服务增加最小金额过滤（`min_total`，包含边界），同时保持既有行为。

- 规格：`demo-app/specs/orders.md`（R1–R4）
- 代码：`demo-app/src/orders.py`
- 测试：`demo-app/tests/test_orders.py`（5 个回归测试 + 2 个目标测试）

步骤：

```bash
# 1. 导入规格/代码/测试到 seekdb
uv run mmctx ingest --root demo-app

# 2. 根据任务检索并生成上下文包（同时写入 PowerContext 任务状态）
uv run mmctx context --task "add min_total filter to list orders" --root demo-app

# 3. 修改前运行测试：目标测试应失败
uv run mmctx test --root demo-app --label before

# 4. 交给 MiniMax Code 完成修改
bash scripts/demo.sh

# 5. 修改后运行测试并保存状态
uv run mmctx test --root demo-app --label after
```

没有 MiniMax 额度时可用参考补丁验证流水线：

```bash
DRY_RUN=1 bash scripts/demo.sh
```

### 预期结果

- 修改前：`test_filter_min_total` 与 `test_filter_status_and_min_total` 因缺少参数失败，其余 5 个回归测试通过。
- 修改后：7 个测试全部通过。
- 上下文包包含 `specs/orders.md`、`src/orders.py`、`tests/test_orders.py` 及各自来源路径。

### 重置方法

```bash
bash scripts/clean.sh
```

PowerContext 默认把状态存于 `~/.local/share/powercontext/powercontext.db`；停止服务后删除该文件即可从空状态重新验证。已从空库验证一次「保存 → 重启 → 读取」流程，见 `evidence/logs/pc-empty-start.txt`。

## 验收项对照

| 必做项 | 实现方式 | 证据 |
| --- | --- | --- |
| 能够运行 | `scripts/setup.sh` + `scripts/demo.sh`，不依赖未交付的本地状态 | `evidence/logs/` |
| MiniMax 实际参与 | `mcode exec` 读取上下文包并修改 `src/orders.py` | `evidence/logs/mcode-stream.json`、`code.diff` |
| 上下文正确 | FTS 检索规格/代码/测试；重新 ingest 后使用更新后的规格 | `context-before.json`、`context-spec-update.json` |
| 数据库实际参与 | 文档与索引存于 seekdb，`mmctx query` 返回来源 | `evidence/logs/seekdb-query.txt` |
| 状态能够复用 | PowerContext 记忆保存任务状态，重启后读取 | `evidence/logs/pc-restart.txt` |
| 代码修改有效 | 修改前目标测试失败，修改后全部通过 | `before.log`、`after.log` |
| 交给 MiniMax 的上下文 | 上下文包与提示词原样留档 | `context-for-minimax.json`、`prompt-for-minimax.md` |

## 已知限制

- 检索使用 seekdb 全文索引与 LIKE 兜底，未启用向量检索。
- PowerContext 仅启用显式记忆，不启用模型抽取。
- 示例工程为最小可验证规模，评审可在干净环境按上述步骤复现。
