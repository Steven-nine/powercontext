# PaperMind · 文献与笔记研读助手

用 **seekdb 混合检索** 找证据，用 **PowerContext 长期记忆** 记住你的研究习惯，
让回答既有出处、又跨会话持续。

PaperMind 面向研究生、科研人员和需要长期读资料的人：导入 PDF / Markdown / 笔记，
提问时由 seekdb 在库内并行执行向量 KNN 与中文全文检索（IK），RRF 融合后把最相关的
片段交给通义千问作答，每个论断都带 `[n]` 引用；同时 PowerContext 在提问前注入
你的研究偏好与已确认结论，回答后回写本轮进展。换一个会话、换一天，偏好仍然生效。

> 本项目为 Qoder × OceanBase 比赛作品，基于
> [powercontext `2026-competition-ecosystem`](https://github.com/oceanbase/powercontext/tree/2026-competition-ecosystem)
> 分支开发，代码位于该分支的 `qoder/papermind` 目录。
> 项目网站（Qoder Sites，任何人可访问）：<https://papermind-3hxelpzw5at.qoder.website>

---

## 1. 指定技术如何真正发挥作用

| 技术 | 在流程中的位置 | 具体实现 |
| --- | --- | --- |
| **seekdb** | 每次提问的检索环节 | 两个 collection：`docs`（文档卡片）与 `chunks`（切片）。切片 collection 同时建立 HNSW 向量索引（`text-embedding-v3`，1024 维，cosine）与 IK 中文全文索引；`hybrid_search` 在数据库内部完成两路并行召回并用 RRF 融合，再用 `source_type` / `year` 结构化条件过滤。界面右侧「检索追踪」面板展示两路各自命中的片段，可直接核对融合结果 |
| **PowerContext** | 提问之前 / 回答之后 | 每个用户对应一个 Scope（`papermind · <user_id>`）。提问前调用 `/v1/atomic-memory/search` 与 `/v1/context/prepare`，把关键词命中的记忆（研究偏好、已确认结论、阅读进展）注入提示词；回答后把本轮结论以 `working_note` 写回，用户说「以后…」时额外写入 `preference`。导入新资料时写入 `fact`。界面「长期记忆」标签页展示命中、注入内容和本次回写 |

两者不是"装了但没用"：检索链路依赖 seekdb 的混合召回结果（`app/retrieval.py`），
提示词中的【长期记忆】段全部来自 PowerContext（`app/service.py`），
回答后的事实写入同样落在 PowerContext（`app/memory.py`）。

## 2. 架构

```
┌─────────────────────────── 浏览器（原生 HTML/CSS/JS） ───────────────────────────┐
│  资料库 + 过滤器       对话与引用卡片        检索追踪 / 长期记忆                     │
└───────────────┬──────────────────────────────────────────────────────────────────┘
                │ REST
┌───────────────▼──────────────── FastAPI（app/main.py）──────────────────────────┐
│  /api/documents*  导入、切分、索引        /api/ask  检索 + 记忆 + 生成            │
│  /api/memory*     记忆面板              /api/health 状态                          │
└───────┬───────────────────────────┬───────────────────────────┬──────────────────┘
        │                           │                           │
┌───────▼─────────┐      ┌──────────▼──────────┐     ┌──────────▼───────────────┐
│ ingest.py       │      │ retrieval.py        │     │ memory.py                │
│ 解析 / 分块     │      │ 关键词 + 过滤 + 融合 │     │ Scope / 记忆读写          │
└───────┬─────────┘      └──────────┬──────────┘     └──────────┬───────────────┘
        │                           │                           │
┌───────▼───────────────────────────▼──────────┐    ┌───────────▼───────────────┐
│ seekdb（嵌入式 / Server / Docker）            │    │ PowerContext Server :8123 │
│ 向量索引 + IK 全文索引 + RRF 混合检索          │    │ SQLite + 语义/文本记忆     │
└──────────────────────────────────────────────┘    └───────────────────────────┘
                     │                                          │
                     └──────────── 通义千问（DashScope，OpenAI 兼容）─────────────┘
```

回答生成只用检索到的片段；资料不足时模型被要求明确说明缺口，而不是编造。

## 3. 快速开始

完整步骤、Windows/WSL 差异与排错见 [docs/RUNBOOK.md](docs/RUNBOOK.md)。最短路径（Linux / WSL2）：

```bash
# 0) 依赖
uv tool install --force "powercontext[cli,server]==1.4.1"

# 1) 配置
cd repo/qoder/papermind
cp .env.example .env                                        # 填入 DASHSCOPE_API_KEY
cp config/powercontext.env.example config/powercontext.env  # 可选：启用向量记忆

# 2) 安装应用依赖
uv venv && uv pip install -e .

# 3) 启动 PowerContext（终端 A）
powercontext server run --env-file config/powercontext.env

# 4) 导入示例资料（终端 B）
python -m scripts.seed

# 5) 启动应用
uvicorn app.main:app --host 127.0.0.1 --port 8080
# 打开 http://127.0.0.1:8080
```

Windows 原生运行时把 seekdb 换成 Docker：`docker run -d --name seekdb -p 2881:2881 oceanbase/seekdb:latest`，
并在 `.env` 中设置 `SEEKDB_MODE=server`。WSL 下代码位于 `/mnt/...` 时，
需把 `DATA_DIR` / `SEEKDB_PATH` 指到 Linux 原生路径（见 RUNBOOK）。

**零凭据体验**：不配置 `DASHSCOPE_API_KEY`、把 `.env` 的 `EMBEDDING_BACKEND` 改为 `local`，
即可在本地哈希向量下跑通导入、混合检索、引用与记忆全流程；回答会降级为"证据清单"，
不会调用任何外部模型。

## 4. 可复核的验证

```bash
python -m scripts.verify_demo
```

脚本以 `demo-user` 身份连续执行三次提问：无记忆 → 表达偏好 → 复用偏好，
打印检索追踪、引用、记忆命中与回写，输出 7 项 PASS/FAIL，并写入 `docs/verification-log.txt`。
输入、步骤与预期结果见 [docs/VERIFICATION.md](docs/VERIFICATION.md)。

## 5. 目录结构

```
qoder/papermind/
├── app/
│   ├── config.py       # 环境变量配置（不写死凭据）
│   ├── embedding.py    # 向量后端：DashScope / 本地哈希（零凭据）
│   ├── ingest.py       # PDF / Markdown 解析、按标题切块、重叠控制
│   ├── store.py        # seekdb 连接、索引、混合检索
│   ├── retrieval.py    # 关键词抽取、过滤条件、通道诊断
│   ├── memory.py       # PowerContext Scope 与记忆读写
│   ├── llm.py          # DashScope 对话与记忆摘要
│   ├── service.py      # 导入 / 提问 / 记忆编排
│   ├── main.py         # FastAPI 路由
│   └── static/         # 前端页面
├── config/powercontext.env.example
├── data/samples/       # 6 篇原创示例语料（RAG / 检索 / 切片 / 记忆 / 评测 / 向量选型）
├── docs/
│   ├── RUNBOOK.md      # 运行与排错
│   ├── VERIFICATION.md # 验证样例
│   └── DEVLOG.md       # Qoder 开发记录
├── scripts/seed.py
├── scripts/verify_demo.py
├── .env.example
└── pyproject.toml
```

## 6. 配置与凭据

- 所有可调参数均在 `.env`，示例值见 `.env.example`；仓库内只有占位符。
- `.env`、`config/powercontext.env`、`data/seekdb/`、`data/uploads/`、`data/scopes.json`
  已被 `.gitignore` 排除，不会提交。
- 未配置 `DASHSCOPE_API_KEY` 时，检索与记忆仍然可用，回答降级为"只列证据"；
  未启动 PowerContext 时，对话与检索不受影响，记忆面板会明确显示不可用。

## 7. 已知限制

- `pyseekdb` 嵌入式模式仅支持 Linux / macOS；Windows 需使用 Docker 或 seekdb Server。
- PowerContext 在 Windows 上为 experimental，推荐在 WSL2 中运行。
- 论文 PDF 的图表与公式不做 OCR，仅索引可提取文本。
- 记忆检索默认使用关键词模式（`mode=text`）；启用 `config/powercontext.env` 中的
  embedding 配置后，PowerContext 自身可在语义检索中启用向量通道。
