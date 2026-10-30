# 运行说明（RUNBOOK）

本文覆盖两种运行环境：

- **A. WSL2 / Linux / macOS（推荐）**：seekdb 嵌入式模式，零外部依赖。
- **B. Windows 原生**：PowerContext 标记为 experimental，seekdb 走 Docker，其余步骤相同。

> 所有命令都在仓库内的 `qoder/papermind` 目录下执行，除非特别说明。

---

## 0. 前置条件

| 项目 | 要求 |
| --- | --- |
| Python | 3.11+ |
| uv | 包管理器，安装见 <https://docs.astral.sh/uv/> |
| PowerContext | 1.4.1（`uv tool install` 安装） |
| DashScope API Key | 阿里云百炼控制台获取，模型 `qwen-plus` + `text-embedding-v3` |
| 端口 | 8080（应用）、8123（PowerContext） |

## 1. 安装 PowerContext（只做一次）

```bash
uv tool install --force "powercontext[cli,server]==1.4.1"
powercontext --version
```

比赛要求可基于源码分支安装：

```bash
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@2026-competition-ecosystem"
```

## 2. 准备配置

```bash
cp .env.example .env
cp config/powercontext.env.example config/powercontext.env
```

编辑 `./.env`：

```dotenv
DASHSCOPE_API_KEY=sk-你的真实key        # 必填
# 其余保持默认即可：SEEKDB_MODE=embedded、POWERCONTEXT_URL=http://127.0.0.1:8123
# 没有 Key 也想先跑通界面：设 EMBEDDING_BACKEND=local（本地哈希向量，回答降级为证据清单）
```

> **WSL 注意**：如果仓库放在 `C:` / `D:` 盘（WSL 中是 `/mnt/c`、`/mnt/d`），
> 嵌入式 seekdb 无法在挂载盘上建库。此时把数据目录指到 Linux 原生路径：
>
> ```dotenv
> DATA_DIR=/home/你的用户名/.papermind/data
> SEEKDB_PATH=/home/你的用户名/.papermind/data/seekdb
> ```
>
> 或用第 3 节的 Docker + `SEEKDB_MODE=server`。

编辑 `./config/powercontext.env`（可选，启用向量记忆）：

```dotenv
OPENAI_API_KEY=sk-你的真实key
POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_MODEL=openai:text-embedding-v3
POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_DIMENSION=1024
POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_PROFILE_ID=dashscope-text-embedding-v3-1024
POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_NORMALIZATION=unit
```

不启用时保持注释状态即可：记忆仍可按词项检索与注入，只是没有语义近义召回。

两个文件都已在 `.gitignore` 中排除，不要提交真实 key。

校验配置：

```bash
powercontext config validate --env-file config/powercontext.env
```

## 3. 安装应用依赖

**WSL / Linux / macOS（嵌入式 seekdb）**

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

**Windows 原生（Docker seekdb）**

```powershell
python -m venv .venv-win
.\.venv-win\Scripts\activate
pip install -e .
docker run -d --name seekdb -p 2881:2881 oceanbase/seekdb:latest
```

然后修改 `.env`：

```dotenv
SEEKDB_MODE=server
SEEKDB_HOST=127.0.0.1
SEEKDB_PORT=2881
SEEKDB_USER=root
SEEKDB_PASSWORD=
```

## 4. 启动 PowerContext（终端 A）

```bash
powercontext server run --env-file config/powercontext.env
```

看到监听 `127.0.0.1:8123` 即可。另开终端确认：

```bash
curl -fsS http://127.0.0.1:8123/health/live
```

可选：浏览器打开 `http://127.0.0.1:8123/dashboard/home` 查看记忆原始数据。

## 5. 导入示例资料（终端 B）

```bash
source .venv/bin/activate      # Windows: .\.venv-win\Scripts\activate
python -m scripts.seed
```

输出形如（每篇的切片数取决于篇幅与 `CHUNK_SIZE`）：

```
✓ 《RAG 基础：检索增强生成的工作流》 6 片 · 已写入 PowerContext
...
完成：6 篇文档 / N 片新增；库内共 6 篇 / N 片。
```

首次运行会自动创建 seekdb 数据库 `papermind` 与两个 collection。

## 6. 启动应用

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

打开 <http://127.0.0.1:8080>：

1. 顶部三个状态灯应全部为绿：seekdb / 记忆 / 模型。
2. 左侧资料库列出 6 篇示例；可按类型、年份过滤。
3. 中间提问框输入问题，回车；答案带 `[n]` 引用，点击引用会高亮左侧对应片段。
4. 右侧「检索追踪」查看本次关键词、过滤条件、RRF 融合结果、向量通道与全文通道各自的命中。
5. 右侧「长期记忆」查看命中、注入模型的上下文、本次回写；也可手动保存一条记忆。

## 7. 一次完整验证

```bash
python -m scripts.verify_demo
cat docs/verification-log.txt
```

预期 7 项全部 PASS，详见 [VERIFICATION.md](VERIFICATION.md)。

## 8. 重置与清理

```bash
# 只清空向量库（保留示例语料）
rm -rf data/seekdb

# 同时清空 PowerContext 记忆（默认数据目录）
rm -rf ~/.local/share/powercontext      # Linux / WSL
# macOS: ~/Library/Application Support/powercontext

# 同时清空用户与 Scope 缓存
rm -f data/scopes.json
```

重新执行第 5 步即可。

## 9. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `Unknown database 'papermind'` | 嵌入式 seekdb 首次使用需先建库 | 应用已自动建库（`app/store.py::_ensure_database`）；若手动脚本绕过应用，先运行一次 `python -m scripts.seed` |
| `seekdb_open failed: code=-1`（WSL） | 数据目录位于 `/mnt/...` 挂载盘 | 把 `DATA_DIR`、`SEEKDB_PATH` 指到 Linux 原生路径，或改用 `SEEKDB_MODE=server` + Docker |
| 顶部记忆灯为灰、记忆面板提示不可用 | PowerContext 未启动 | 按第 4 节启动；应用其余功能不受影响 |
| 启动 PowerContext 报 `address already in use` | 端口被占用 | 改 `POWERCONTEXT_SERVER_HTTP_PORT`，并同步 `.env` 的 `POWERCONTEXT_URL`。**不要**直接杀掉不认识的服务 |
| 向量维度不匹配（4 vs 384 / 1024） | collection 用了默认 embedding 维度 | 删除 `data/seekdb` 后重建，确保 `.env` 的 `EMBEDDING_DIM` 与模型一致（`text-embedding-v3` → 1024） |
| `status: degraded`、记忆检索只有 `fts` | 未配置或配置错了 Embedding | 检查 `config/powercontext.env` 的 `OPENAI_API_KEY` / `BASE_URL` / `PROFILE_ID`，`powercontext config validate` 后再启动 |
| 记忆检索整句搜不到 | PowerContext 文本检索按词项匹配，中文长句分词后命中差 | 应用已改为用 jieba 关键词检索（`app/service.py`）；手动调用 API 时也建议传关键词 |
| 记忆检索 `mode: hybrid` 报 internal_error | 未启用向量记忆 | 使用 `mode: text`（应用默认），或先完成向量记忆配置 |
| 页面显示"模型未配置" | `.env` 中 key 仍是占位值 | 填入真实 `DASHSCOPE_API_KEY` 后重启应用 |
| 导入 PDF 后 0 片 | PDF 是扫描件 / 加密 | 目前只索引可提取文本，扫描件需先 OCR |
| Windows 下 `pylibseekdb` 安装失败 | 嵌入式 seekdb 不支持 Windows | 使用第 3 节的 Docker + `SEEKDB_MODE=server` |

## 10. 接口速查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 三项依赖状态与库统计 |
| GET | `/api/documents` | 文档列表 |
| POST | `/api/documents/upload` | multipart 上传（pdf/md/txt） |
| POST | `/api/documents/text` | 直接粘贴文本建资料 |
| DELETE | `/api/documents/{doc_id}` | 删除文档及其切片 |
| POST | `/api/ask` | `{question, user_id, filters}` → 答案、引用、追踪、记忆 |
| GET | `/api/memory?user_id=` | 列出该用户的记忆 |
| POST | `/api/memory` | 手动写一条记忆 |

交互式文档：<http://127.0.0.1:8080/docs>
