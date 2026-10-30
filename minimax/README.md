# MiniMax × OceanBase · 规有所依 —— 面向软件持续演进的 SDD 上下文管理系统

本目录是本次赛题的完整作品：围绕**规格驱动开发（SDD）**实现了一个**工程上下文模块**，
把「规格 / 代码 / 测试」组织成可复用的开发上下文，用 **MiniMax** 完成一次真实的代码修改，
并用 **seekdb / OceanBase** 与 **PowerContext** 分别承担「资料存储检索」与「任务状态复用」。

| 技术 | 在本次任务中承担的作用 | 接入方式与版本 |
|---|---|---|
| **MiniMax** | 依据检索到的上下文生成 unified diff，实际修改了 `business/shopcalc/pricing.py` | HTTP API（OpenAI 兼容），`POST https://api.minimax.cn/v1/chat/completions`，模型 `MiniMax-M3.1-Flash` |
| **seekdb / OceanBase** | 保存规格、代码、测试全文与倒排索引；检索结果直接决定上下文内容 | MySQL 协议，`pymysql` 直连 `127.0.0.1:2881`，服务版本 `5.7.25-OceanBase seekdb-v1.4.0.0` |
| **PowerContext** | 保存工作契约、Memory 条目、Handoff 里程碑与任务结论；模块重启后读回复用 | Python SDK（`powercontext[builtin]==1.2.0`），内置 relational 后端（SQLite 文件） |

> 目录：`minimax/` 全部资产均位于本目录内，与仓库其它参赛者目录（`gaode/`、`dify/`、`qoder/`、`stepfun/`）互不影响。

---

## 1. 目录结构

```
minimax/
├── README.md                    # 本文件：运行说明
├── requirements.txt             # 运行依赖（含版本）
├── .env.example                 # 配置示例（全部为占位值，不含真实凭据）
├── pytest.ini                   # sddctx 模块自身的测试配置
├── sddctx/                      # ★ 上下文管理模块（Python 包）
│   ├── config.py                #   配置装配（环境变量 / 缓存目录）
│   ├── store.py                 #   seekdb 资料库：表结构、写入、BM25 检索
│   ├── ingest.py                #   规格 / 代码 / 测试解析与导入
│   ├── context.py               #   开发上下文组装（规格 / 代码 / 测试 / 状态）
│   ├── minimax_client.py        #   MiniMax OpenAI 兼容客户端 + 开发记录
│   ├── diffutil.py              #   unified diff 解析与应用
│   ├── agent.py                 #   开发助手循环：上下文 → MiniMax → 补丁 → 测试
│   ├── state.py                 #   PowerContext 任务状态存储
│   └── cli.py                   #   命令行入口
├── business/                    # ★ 业务工程（订单结算与优惠计算）
│   ├── shopcalc/{models,discounts,pricing}.py
│   └── tests/{test_pricing,test_discounts,test_shipping}.py
├── baseline/business/            # ★ 修改前代码快照（验证样例的"重置"来源）
├── specs/                       # ★ 规格（SDD 输入）
│   ├── settlement_spec.md               # 当前版本 v1.2（新增 SPEC-SHIP-002）
│   └── versions/settlement_spec.v1.1.md # 历史版本 v1.1（用于"规格更新"演示）
├── scripts/
│   ├── run_verification.py       # ★ 端到端验证脚本（一条命令复现全部证据）
│   └── setup_env.sh              # Linux 环境准备脚本
├── tests/test_sddctx.py          # sddctx 模块自身的单元测试（11 条）
├── docs/
│   ├── 技术说明.md               # 一页技术说明
│   ├── 验证样例.md               # 任务 / 规格 / 数据 / 步骤 / 预期结果 / 重置
│   └── 技术使用记录.md           # MiniMax / 数据库 / PowerContext 使用记录
└── artifacts/                   # ★ 评审证据（由验证脚本生成）
    ├── diff/before_after.patch         # 修改前 → 修改后的完整差异
    ├── diff/minimax_generated.patch    # MiniMax 原始产出的补丁
    ├── snapshots/after/                # 修改后代码快照
    └── logs/                           # 测试日志 / 上下文 / 数据库查询 / 开发记录
```

---

## 2. 依赖与版本

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.12.15（支持 3.11–3.14） | PowerContext 要求 `>=3.11,<4.0` |
| powercontext | `powercontext[builtin]==1.2.0` | 任务状态存储；本模块使用 `runtime.memory` / `runtime.work` / `runtime.handoff` 接口 |
| pymysql | `>=1.2,<1.2.1` | 连接 seekdb（纯 Python，Windows / Linux 通用） |
| requests | `>=2.31,<3` | 调用 MiniMax HTTP API |
| pytest | `>=8,<10` | 业务工程与模块自身的测试 |
| seekdb | `1.4.0`（`5.7.25-OceanBase seekdb-v1.4.0.0`） | 资料库，监听 `127.0.0.1:2881` |

### 安装

```bash
cd minimax
python -m venv .venv                      # 或 uv venv .venv
# Windows:
.venv\Scripts\activate
# Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

> 内网环境可指定镜像源，例如 `pip install -r requirements.txt -i https://mirrors.ustc.edu.cn/pypi/simple`。

---

## 3. 准备 seekdb（资料库）

本作品使用 **seekdb**（OceanBase 的轻量数据库，MySQL 协议）作为工程资料库。

```bash
# Linux / WSL2：安装并启动官方 seekdb deb
dpkg -i seekdb_1.4.0-100000212026082616_ubuntu24.04_amd64.deb
systemctl enable --now seekdb

# 验证：监听 2881，root 空密码可连
mysql -h127.0.0.1 -P2881 -uroot -e "SELECT VERSION(), @@port;"
```

Windows 侧直接用 MySQL 协议访问 WSL2 里的 seekdb 即可（`127.0.0.1:2881`）。

模块启动时会自动建库建表（幂等）：

```sql
CREATE DATABASE IF NOT EXISTS sdd_ctx DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
```

表结构：`sdd_doc`（资料）、`sdd_doc_revision`（修订历史）、`sdd_spec_entry`（规格条目）、
`sdd_symbol`（代码符号）、`sdd_term`（倒排索引）。

---

## 4. 配置

复制 `.env.example` 并按需修改（**不要提交真实凭据**）：

| 环境变量 | 默认值 | 含义 |
|---|---|---|
| `MINIMAX_API_KEY` | （必填） | MiniMax API Key，中国大陆站为 `https://api.minimax.cn/v1` |
| `SDDCTX_MINIMAX_BASE_URL` | `https://api.minimax.cn/v1` | MiniMax 接口地址 |
| `SDDCTX_MINIMAX_MODEL` | `MiniMax-M3.1-Flash` | 模型名 |
| `SDDCTX_DB_HOST` / `SDDCTX_DB_PORT` | `127.0.0.1` / `2881` | seekdb 地址 |
| `SDDCTX_DB_USER` / `SDDCTX_DB_PASSWORD` | `root` / 空 | seekdb 账号 |
| `SDDCTX_DB_NAME` | `sdd_ctx` | 资料库名 |
| `SDDCTX_CACHE_DIR` | Windows `D:\DeepSeek缓存\minimax-sdd`；其他 `~/.cache/minimax-sdd` | 缓存 / 状态目录 |
| `SDDCTX_STATE_DB` | `<SDDCTX_CACHE_DIR>/state/powercontext.db` | PowerContext 状态库文件 |
| `SDDCTX_ARTIFACTS_DIR` | `<minimax>/artifacts` | 证据产物目录 |

> **缓存数据位置**：按要求，pip / uv 缓存、PowerContext 状态库与运行日志默认落在 **D 盘** 的
> `D:\DeepSeek缓存\minimax-sdd\`（`cache/`、`state/`、`logs/`）。Linux 下回退到 `~/.cache/minimax-sdd`。

---

## 5. 调用入口

命令行入口：`python -m sddctx <子命令>`（工作目录为 `minimax/`）。

| 子命令 | 输入 | 输出 | 说明 |
|---|---|---|---|
| `ingest` | 工作区路径 | 导入清单（stdout / JSON） | 把规格、代码、测试写入 seekdb 并建索引 |
| `context` | `--task "<任务描述>"` | 开发上下文（Markdown / JSON） | 定位规格条目、代码符号、测试、任务状态 |
| `modify` | `--task "<任务描述>"` | 补丁 + 测试结论 | 调用 MiniMax 完成一次真实代码修改并跑测试 |
| `state show` | `--task-id <任务编号>` | 任务状态 | 从 PowerContext 读回已完成 / 待办 / 验证结果 |
| `state reset` | `--task-id <任务编号>` | — | 清空任务状态（验证样例重置用） |
| `db stats` | — | 资料库统计 | 查看各表行数与文档修订 |
| `db sql "<SQL>"` | SQL | JSON | 执行只读查询（生成数据库查询记录） |
| `test` | 可选节点 ID | pytest 输出 | 运行业务工程测试 |

### 典型用法

```bash
cd minimax
export MINIMAX_API_KEY=<你的 key>

# 1) 导入工程资料到 seekdb
python -m sddctx ingest --reset

# 2) 查看本次任务适用的开发上下文
python -m sddctx context --task "实现 SPEC-SHIP-002 偏远地区运费规则 shipping_fee：新疆、西藏、内蒙古订单固定收取 ¥20 运费，且优先于满 99 免运费规则" --task-id ship-002

# 3) 用 MiniMax 完成一次真实代码修改（应用补丁并跑测试）
python -m sddctx modify --task "实现 SPEC-SHIP-002 偏远地区运费规则 shipping_fee：…" --task-id ship-002 --patch-out artifacts/diff/minimax_generated.patch

# 4) 重启后读回任务状态
python -m sddctx state show --task-id ship-002
```

### 一条命令复现全部验收证据（推荐）

```bash
cd minimax
export MINIMAX_API_KEY=<你的 key>
python scripts/run_verification.py
```

脚本会**从干净状态**重放完整流程（重置 → 修改前测试 → 导入 → 规格更新 → MiniMax 修改 →
修改后测试 → 状态复用 → 产出证据），并在结束时打印 `验证通过：PASS`。
产物全部落在 `artifacts/`：

* `artifacts/logs/tests_before_target.txt` / `tests_before_regression.txt` — 修改前测试（命令、退出码、输出）
* `artifacts/logs/tests_after_target.txt` / `tests_after_regression.txt` / `tests_after_full.txt` — 修改后测试
* `artifacts/logs/context_spec_v1.*` / `context_spec_v2.*` — 规格更新前后的上下文
* `artifacts/logs/state_readback.txt` — **另一个进程**读回 PowerContext 状态
* `artifacts/logs/minimax_development_record.md` — MiniMax 完整请求 / 响应 / usage
* `artifacts/logs/db_queries.md` — 数据库查询记录
* `artifacts/diff/before_after.patch` — 修改前后的代码差异

没有 MiniMax Key 时可用 `--skip-minimax` 复现除模型调用外的其余步骤
（会直接应用已归档的 `artifacts/diff/minimax_generated.patch`）。

---

## 6. 测试命令

```bash
# 业务工程（订单结算）的目标测试与回归测试
cd minimax/business
pytest -q --no-header -rA \
  tests/test_shipping.py::test_remote_region_shipping_fee_is_fixed_twenty_yuan \
  tests/test_shipping.py::test_remote_region_shipping_fee_overrides_free_shipping_threshold
pytest -q --no-header -rA tests --deselect tests/test_shipping.py::test_remote_region_shipping_fee_is_fixed_twenty_yuan \
  --deselect tests/test_shipping.py::test_remote_region_shipping_fee_overrides_free_shipping_threshold
pytest -q --no-header -rA tests        # 全量

# sddctx 模块自身的单元测试
cd minimax
pytest -q --no-header -rA tests
```

---

## 7. 本次任务做了什么

**任务**：实现规格条目 `SPEC-SHIP-002`（偏远地区运费）——
新疆 / 西藏 / 内蒙古订单固定收取 ¥20 运费，且该规则**优先于** `SPEC-SHIP-001` 的满 ¥99 免运费规则。

| 阶段 | 结果 |
|---|---|
| 修改前 | 目标测试 **2 个用例（6 个参数化实例）失败**，失败原因为 `AssertionError: assert Decimal('8') == Decimal('20')`（真实功能缺失，非环境错误）；回归测试 **14 条全部通过** |
| MiniMax | 1 次调用即产出正确的 unified diff（`response_id=0733e29033ae12b7720b8ce5682e75ee`），仅改动 `business/shopcalc/pricing.py` |
| 修改后 | 目标测试、回归测试、全量测试 **退出码均为 0** |
| 状态复用 | 另一个进程通过 `python -m sddctx state show` 读回 PowerContext 状态并用于新的上下文组装 |

> MiniMax 的补丁与仓库中的最终代码一致，见 `artifacts/diff/before_after.patch`
> 与 `artifacts/diff/minimax_generated.patch`（两次输出仅注释措辞不同，均满足规格）。

---

## 8. 已知限制

1. **PowerContext 版本**：本模块使用 `powercontext==1.2.0` 的 `runtime.memory` 接口；
   `1.4.x` 已将该接口重构为 `runtime.atomic_memory`，升级后需同步改造 `sddctx/state.py`
   （模块会给出明确的报错提示，不会静默降级）。
2. **seekdb 不提供 `ob_compatibility_mode`**：PowerContext 的 `kind=oceanbase` 后端要求该变量为 `MYSQL`，
   因此本作品让 PowerContext 使用其内置 relational（SQLite）后端保存任务状态，
   而把**工程资料与检索索引**放在 seekdb 中。两种职责互不冲突。
3. **中文分词**：检索采用「英文按标识符切分 + 中文按字切分 + 规格编号精确匹配」的轻量方案，
   未引入额外分词依赖；规格条目通过 `SPEC-XXX-NNN` 精确匹配获得最高权重。
4. **补丁应用**：模型给出的 unified diff 行号可能有偏差，模块按上下文内容就近定位区块
   （与 `patch` / `git apply` 的偏移行为一致），定位失败时报错并把错误反馈给模型重试。
5. **MiniMax 区域**：默认使用中国大陆站 `api.minimax.cn`；全球站请设置
   `SDDCTX_MINIMAX_BASE_URL=https://api.minimax.io/v1` 并使用对应区域的 Key（Key 不可跨区域使用）。

---

## 9. 参考

* 赛题仓库与分支：<https://github.com/oceanbase/powercontext/tree/2026-competition-ecosystem>
* MiniMax 文本生成接口：<https://platform.minimax.cn/docs/api-reference/text-chat-openai.md>
* PowerContext 集成说明：仓库内 `docs/` 与 `powercontext-integration-guide.md`（PowerContext 公开 API）
* seekdb：OceanBase 生态的轻量数据库，MySQL 协议兼容
