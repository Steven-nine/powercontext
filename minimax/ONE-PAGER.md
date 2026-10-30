# 一页技术说明

## 模块结构

```text
demo-app/specs|src|tests
        |
        | mmctx ingest
        v
seekdb (docs 表 + 全文索引)
        |
        | mmctx context --task
        v
.mmcontext/context.json + prompt.md
        |
        | mcode exec (MiniMax Code)
        v
demo-app/src/orders.py (代码修改)
        |
        | pytest
        v
evidence/logs (before/after 测试日志)
        |
        | mmctx state save / load
        v
PowerContext Server (显式记忆，重启后读取)
```

## 上下文选择方式

1. `ingest` 扫描 `specs/**/*.md`、`src/**/*.py`、`tests/**/*.py` 与 `AGENTS.md`，按类型写入 seekdb 并建立全文索引。
2. `context` 将任务文本切分为关键词，按规格、代码、测试三类分别检索，每类取前 3 条；全文匹配不足时使用 LIKE 兜底。
3. 输出包含每条的来源路径与原文，来源均为仓库中真实存在的文件；规格更新后重新 ingest，输出随之变化。

## 技术分工

| 技术 | 在任务中的实际作用 |
| --- | --- |
| MiniMax Code | 读取上下文包，修改 `demo-app/src/orders.py`，并运行测试 |
| seekdb | 存储规格/代码/测试文档与索引，检索结果用于构造上下文 |
| PowerContext | 保存任务状态（已完成、待办、来源、上下文文件），重启后读取并合并到后续上下文 |

## 验证样例

任务：为 `list_orders` 增加 `min_total` 过滤（包含边界），保持既有行为。

- 修改前：2 个目标测试失败，5 个回归测试通过。
- 修改后：7 个测试全部通过。
- 验收证据见 `evidence/logs/`。
