# 记忆剧场 · 门卫阿铁（Memory Theatre）

> 一个由 **Dify 编排**的即兴荒诞剧场。门卫阿铁值班三百年，最擅长的事是**记住旅人对他做过的每一件坏事**——
> 你整蛊过他，他就在下一幕翻旧账；你随口一句话，他会当成口头禅一直念叨。
> 全部记忆由 **PowerContext** 持久化：**重启 Dify、重启 PowerContext、甚至换一台机器，只要还在同一个库，
> 他都还记得你**。

```
┌──────────────┐   POST /v1/workflows/run    ┌─────────────────────────────┐
│ 网页 / API   │ ───────────────────────────► │ Dify 1.9.2 Workflow（12 节点）│
│ scripts/     │ ◄─────────────────────────── │ start→code→http→code→…→end   │
│ serve.py     │      answer + 记忆回执         └──────┬───────────────┬──────┘
└──────────────┘                                        │ HTTP          │ Code
                                                         ▼               ▼
                                              ┌──────────────────┐  ┌──────────────────┐
                                              │ PowerContext 1.4 │  │ Code Executor    │
                                              │ scope / memory  │  │ （规则引擎执行）  │
                                              └──────────────────┘  └──────────────────┘
```

---

## 1. 作品创意与玩法

**世界观**：城门口有一扇永远在移动的出口。门卫「阿铁」在这里站了三百年，鸽子议会掌握着全城的话语权。
玩家是路过的旅人，用一句话决定自己这一幕要做什么。

**三种行动**（也可自由输入，规则引擎会归类）：

| 输入 | 行动 | 效果 |
| --- | --- | --- |
| `A 调查…` | 调查 | 信任 +1 |
| `B 整蛊…` | 整蛊 | 混乱 +1，**门卫记仇** |
| `C 和门卫协商` | 协商 | 硬币 −1，信任 +2 |
| 其它自由文本 | 自由行动 | 混乱 +1，**门卫会把你的第一句自由行动当成口头禅** |

**三个结局**：信任 ≥ 5 →【门卫合伙人】；混乱 ≥ 5 →【混乱市长】；硬币耗尽且信任 < 2 →【被城门除名】；
第 12 幕 →【长夜未央】。

**三个频道**：荒诞喜剧（默认）/ 午夜悬疑 / 赛博朋克，同一套规则、三套场景与事件文本。

**记忆怎么"看得见"**（这是本作品的核心验证点）：

1. **记得上一幕**——第 2 幕起，台词会直接引用你上一幕干的事；
2. **记仇**——你整蛊过门卫，下一幕他会翻旧账，原话奉还；
3. **口头禅**——你写的第一句自由行动，之后会被他反复念叨；
4. **跨进程**——以上全部来自 PowerContext 里真实落库的记忆条目，重启服务后依然成立；
5. **写后读回**——工作流最后一个节点会把刚写入的记忆再检索一次，读不到就让整轮失败；
6. **能翻账本**——网页右侧的「门卫的笔记本」直接列出 PowerContext 里的原始条目
   （`art_…` 条目 ID + 正文），不是前端自造的记录。

---

## 2. 技术分工

| 组件 | 角色 | 在流程中的实际作用 |
| --- | --- | --- |
| **Dify 1.9.2**（必选） | 核心编排 | 12 个节点的 Workflow：接收输入 → 生成 scope 请求 → 读记忆 → 跑规则引擎 → 写记忆 → 读回校验 → 输出剧情与回执 |
| **PowerContext 1.4.1**（必选） | 记忆与上下文 | `POST /v1/scopes` 建玩家记忆空间、`POST /v1/memory/search` 检索历史、`POST /v1/memory/remember` 落库；Dify 直连，不经过任何自建网关 |
| **Code Executor**（本仓库自带） | 执行 Dify Code 节点 | 实现 Dify 1.9 的 `/v1/sandbox/run` 协议，让规则引擎在 WSL2 / Linux / Windows 都能运行（见 §6.2） |
| **网页入口**（可选） | 体验界面 | `scripts/serve.py` + `ui/index.html`，零依赖、无需构建；也可以完全不用，直接调 Dify API |

> 本作品指定的指定技术组合是 **Dify + PowerContext**。题目允许二选一，也允许同时使用 seekdb；
> 本作品把 PowerContext 作为"记忆大脑"，并额外支持把 PowerContext 的持久层换成 **seekdb**（§6.3）。

---

## 3. 目录结构

```
dify/memory-theatre/
├── README.md                     本文件（运行说明）
├── VERIFICATION.md               验证样例、预期表现与实际运行结果
├── TECHNICAL_NOTE.md             工作流节点、记忆协议与设计取舍
├── dsl/
│   ├── memory-theatre-workflow.yml   ★ 提交用的 Dify DSL（12 节点 Workflow）
│   └── theatre_rules.py              规则引擎源码（被嵌入 Code 节点，也被单测覆盖）
├── scripts/
│   ├── start-dify-local.sh       启动最小 Dify（Docker，host network）
│   ├── start-powercontext.sh     启动 PowerContext（SQLite / seekdb 两种后端）
│   ├── code_executor.py          Dify Code 节点的本地执行器
│   ├── configure-local.py        导入 DSL → 发布 → 生成应用 API Key → 写 .env
│   ├── build_dsl.py              由 theatre_rules.py 重新生成 DSL
│   ├── serve.py                  网页入口 + Dify 代理
│   ├── verify.py                 端到端验证（4 幕 + 隔离 + 重启续玩）
│   └── export-node-evidence.sh   从 Dify 的 PostgreSQL 导出节点执行记录
├── ui/index.html                 单文件前端（无需 npm / 构建）
├── tests/test_rules.py           规则引擎单元测试（11 项，纯标准库）
└── evidence/                     实际运行证据（JSON）
```

---

## 4. 环境与版本

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Dify API | `langgenius/dify-api:1.9.2` | 官方镜像；DSL 版本 0.4.0 |
| PostgreSQL / Redis | 15-alpine / 6-alpine | Dify 自身依赖 |
| Dify Sandbox | `langgenius/dify-sandbox:0.2.12` | 官方沙箱；**在 WSL2 上 Python runner 不可用**，见 §6.2 |
| Code Executor | 本仓库自带 | 纯标准库，实现同一套协议 |
| PowerContext | `powercontext[cli,server]==1.4.1` | PyPI；SQLite / seekdb 两种持久层 |
| Python | 3.9+（含 3.12 实测） | 运行脚本、规则引擎、网页代理 |
| Docker Engine | 24+ | 仅 Dify 部分需要；Windows 用 WSL2 |

资源建议：可用内存 ≥ 6 GB，磁盘 ≥ 10 GB（镜像约 2 GB）。首次启动需要联网拉取镜像与 PyPI 包；
**启动完成后，本作品默认路径不需要任何外部模型、API Key 或外网访问**。

---

## 5. 快速开始（Linux / WSL2）

### 5.1 启动 Dify

```bash
cd dify/memory-theatre
bash scripts/start-dify-local.sh
```

脚本使用 host networking，依次拉起 4 个容器：
`arcade-postgres`（5433）、`arcade-redis`（6381）、`arcade-sandbox`（8194）、`arcade-api`（5001）。
随机凭据写在 `.runtime/dify.env`（已在 `.gitignore` 中），数据库与 Dify 存储保存在 Docker named volumes 里，重启即续用。

Docker Hub 不可达时可加镜像前缀：

```bash
ARCADE_IMAGE_PREFIX=docker.m.daocloud.io/ bash scripts/start-dify-local.sh
```

### 5.2 启动 PowerContext

```bash
bash scripts/start-powercontext.sh
# -> PowerContext ready: http://127.0.0.1:8124
```

数据文件在 `.runtime/powercontext/memory-theatre.sqlite3`；停止后再执行同一条命令即可续用（记忆不丢）。

### 5.3 启动 Code Executor（推荐，见 §6.2）

```bash
KEY=$(sed -n 's/^CODE_EXECUTION_API_KEY=//p' .runtime/dify.env)
CODE_EXECUTION_API_KEY="$KEY" CODE_EXECUTOR_PORT=8195 nohup python3 scripts/code_executor.py \
  >.runtime/code-executor.log 2>&1 &

docker rm -f arcade-api
docker run -d --name arcade-api --restart unless-stopped --network host \
  --env-file .runtime/dify.env -e MODE=api -e SERVER_WORKER_AMOUNT=1 \
  -e CODE_EXECUTION_ENDPOINT=http://127.0.0.1:8195 \
  -v arcade-storage:/app/api/storage langgenius/dify-api:1.9.2
```

> 如果你的 Dify Sandbox 一切正常（Linux 主机上官方沙箱可用），**可以跳过这一步**，
> 直接用官方 `arcade-sandbox`（`CODE_EXECUTION_ENDPOINT=http://127.0.0.1:8194`）。

### 5.4 导入 DSL、发布、生成应用 Key

```bash
python3 scripts/configure-local.py --initialize \
  --dify-url http://127.0.0.1:5001 \
  --powercontext-url http://127.0.0.1:8124
```

脚本会：

1. 通过 Dify 官方 Console API 初始化本地管理员并登录；
2. `POST /console/api/apps/imports`（`mode=yaml-content`）导入 `dsl/memory-theatre-workflow.yml`；
3. `POST /console/api/apps/{app_id}/workflows/publish` 发布；
4. `GET/POST /console/api/apps/{app_id}/api-keys` 创建应用 API Key；
5. 把 `DIFY_BASE_URL / DIFY_API_KEY / POWERCONTEXT_URL / DIFY_APP_ID` 写进 `.env`（**该文件不会提交**）；
6. 把导入与发布结果写进 `evidence/dify-import.json`。

导入时会把 DSL 里 `POWERCONTEXT_URL` 环境变量替换成 `--powercontext-url` 的值，
所以换一台机器只需改这个参数，不用手改 DSL。

### 5.5 启动网页并开玩

```bash
python3 scripts/serve.py
# 打开 http://127.0.0.1:8787
```

---

## 6. 其他接入方式与可选项

### 6.1 直接调 Dify API（不装网页）

```bash
curl -sS http://127.0.0.1:5001/v1/workflows/run \
  -H "Authorization: Bearer $DIFY_API_KEY" -H "Content-Type: application/json" \
  -d '{
    "inputs": {"player_id": "demo-001", "player_name": "阿舟",
               "action": "B 整蛊鸽子议会", "channel": "surreal"},
    "response_mode": "blocking", "user": "demo-001"}'
```

输出：

```json
{
  "data": {
    "outputs": {
      "answer": "第 1 幕 · 荒诞城门\n…",
      "receipt": "{\"scope_id\": \"scp_…\", \"memory_artifact\": {\"artifact_id\": \"art_…\"}, \"read_back_verified\": true, …}"
    }
  }
}
```

`receipt` 是字符串形式的 JSON，内容见 `VERIFICATION.md`。

### 6.2 为什么附带 Code Executor

官方 `dify-sandbox:0.2.12` 的 Python runner 是内嵌 CPython 的 `python.so`（带 seccomp 过滤器）。
在 **WSL2 内核**上它连 `import json` 都会被拒绝（EPERM），表现为 Dify Code 节点报
`Not all output parameters are validated.`；而在普通 Linux 主机上工作正常。
为了让「换一台机器就能跑」成立，本仓库附带 `scripts/code_executor.py`：
它用标准库实现 Dify 1.9 的 `POST /v1/sandbox/run` 协议（同样的 base64 inputs、`<<RESULT>>` 输出约定），
并限制只监听 `127.0.0.1`、需要 `X-Api-Key`、子进程有超时与内存上限。
**它只用于本地演示，不要当作多租户沙箱使用。**

### 6.3 PowerContext 的其它持久层（seekdb / OceanBase）

PowerContext 1.4.1 支持三种持久层，本作品默认用 **SQLite**（零依赖、随开随用）：

| 后端 | 配置 | 本机实测 |
| --- | --- | --- |
| SQLite | `POWERCONTEXT_SERVER_DATABASE_KIND=sqlite` + `..._DATABASE_URL=sqlite+aiosqlite:///<path>` | ✅ 已验证（本作品默认） |
| 内嵌 seekdb | `POWERCONTEXT_SERVER_DATABASE_KIND=seekdb` + `..._DATABASE_PATH=<dir>` | ❌ 本机启动失败：`MigrationError: backend_unavailable (The embedded seekdb binding is unavailable.)`，需要 PowerContext 附带的 seekdb binding |
| 外部 OceanBase / seekdb | `POWERCONTEXT_SERVER_DATABASE_KIND=oceanbase` + `..._DATABASE_URL=mysql+aoceanbase://root:@host:2881/db?charset=utf8mb4` | ❌ 对着本机的 seekdb 1.4.0（sys 租户）启动失败：`OceanBase maintenance requires a MySQL user tenant.`；有 **MySQL 用户租户**的 OceanBase/seekdb 可用 |

也就是说：**本作品的"指定技术"落在 PowerContext 上**（题目允许二选一）。
若评测环境提供带用户租户的 OceanBase/seekdb，改上面两行环境变量即可把记忆搬到 seekdb 上，
工作流与 DSL 无需任何改动（PowerContext 的 HTTP 契约完全一致）。

> 附：本仓库作者的另一个环境里运行着独立的 seekdb 1.4.0 实例（端口 2881），
> 可用于 Dify 自身的数据库部署或素材检索，但它不是本作品记忆层的落点，故不在此计入技术分工。

### 6.4 PowerContext 鉴权

本作品默认 `POWERCONTEXT_SERVER_ACCESS_MODE=disabled`（本机演示）。
若要开启鉴权，请在 DSL 的 `environment_variables` 里增加 `POWERCONTEXT_TOKEN`（`value_type: secret`），
并在三个 HTTP 节点的头部加上 `Authorization:Bearer {{#env.POWERCONTEXT_TOKEN#}}`。

---

## 7. 验证

```bash
python3 tests/test_rules.py          # 规则引擎单测（11 项，不需要任何服务）
python3 scripts/verify.py             # 端到端：4 幕 + 玩家隔离 + 读回校验
# 重启服务之后：
python3 scripts/verify.py --resume   # 第 5 幕：证明记忆跨重启存活
bash scripts/export-node-evidence.sh  # 从 Dify PostgreSQL 导出节点执行记录
```

详细步骤、预期表现与实际输出见 **[VERIFICATION.md](VERIFICATION.md)**。

---

## 8. 已知限制

- 单机作品，没有账号体系：玩家标识保存在浏览器 localStorage，**换浏览器 = 换玩家**（记忆随之隔离）。
- 规则引擎只认「调查 / 整蛊 / 协商」三类意图与自由行动，不做自然语言理解；
  规则源码在 `dsl/theatre_rules.py`，改完跑 `python3 scripts/build_dsl.py` 重新生成 DSL 再导入。
- 一个玩家一次冒险最多 12 幕（`MAX_TURNS`），到顶后进入【长夜未央】结局。
- PowerContext 单条记忆上限 8192 UTF-8 字节，超长会被工作流显式拒绝（而不是静默截断）。
- PowerContext 检索一次最多取 50 条，历史再长也只回看最近 50 幕。
- `dify-sandbox` 与本仓库的 Code Executor 都不适合暴露到公网。

---

## 9. 故障排查

| 现象 | 原因与处理 |
| --- | --- |
| Code 节点报 `Not all output parameters are validated.` | Sandbox 的 Python runner 不可用（WSL2 常见）→ 按 §5.3 切到本仓库的 Code Executor |
| 导入后 HTTP 节点报 404/连接失败 | `POWERCONTEXT_URL` 不可达。容器用 host networking 时应填 `http://127.0.0.1:8124`；PowerContext 跑在 Windows 时填 `http://host.docker.internal:8124` |
| 记忆一直是空的 | 确认 PowerContext 进程在跑（`curl http://127.0.0.1:8124/health/ready`），且 `.env` 里的 `POWERCONTEXT_URL` 与之��致 |
| 每幕都从"第 1 幕"开始 | `player_id` 变了。记忆按 `player_id` 绑定；同一个 `player_id` 才会续上 |
| Windows 控制台打印中文报错 | `chcp 65001` 或 `set PYTHONIOENCODING=utf-8` |

---

## 10. 来源与改动

- 生态基线：`oceanbase/powercontext` 分支 `2026-competition-ecosystem`，本作品资产全部位于 `dify/` 目录。
- Dify / Dify Sandbox：官方公开镜像与协议，未修改源码。
- PowerContext：PyPI 官方包 `powercontext==1.4.1`，仅通过其公开 HTTP API 接入，未修改源码。
- 本目录内的源码（规则引擎、脚本、网页）为本作品原创；网页不依赖任何第三方前端库。
- 未复用任何第三方作品代码或数据；未包含任何真实 API Key / 密码（运行期凭据只写入被忽略的 `.env` 与 `.runtime/`）。
