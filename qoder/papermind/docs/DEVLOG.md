# Qoder 开发记录（DEVLOG）

- **Qoder 账号 UID**：`01a18b11-02fd-79c2-ada8-c9e6fc6b9b9b`
- **开发日期**：2026-10-30
- **代码仓库**：基于 `oceanbase/powercontext` 分支 `2026-competition-ecosystem`，代码位于 `qoder/papermind`
- **使用方式**：Qoder IDE Agent（本会话）负责技术调研、方案取舍、代码编写、脚本调试与文档生成；
  所有涉及外部服务的实际操作（安装、启动、验证）在本地 WSL2 中执行并由本人确认。

---

## 1. 为什么做 PaperMind

比赛要求"让学习、科研和工作更高效"，且必须让指定技术在功能中实际发挥作用。
文献研读有两类真实痛点：

1. **找不到**：只按关键词搜不到同义表述；只按向量搜又会漏掉精确术语、数字、公式编号。
2. **记不住**：每次会话都要重新交代语言、篇幅、关注点；上次确认的结论下次要重新推一遍。

因此选择"混合检索 + 长期记忆"这一组合：seekdb 解决第 1 点，PowerContext 解决第 2 点。
这也是完成速度最快的方向：不需要训练模型、不需要前端框架、不依赖 GPU。

## 2. 时间线（同一工作日内）

| 阶段 | 工作内容 | 产出 |
| --- | --- | --- |
| 调研 | 阅读 PowerContext 官方文档（安装、配置、HTTP API、Scope/记忆模型）与 pyseekdb 文档/源码 | 确定接口形态：`/v1/scopes`、`/v1/memory/remember`、`/v1/atomic-memory/search`、`/v1/context/prepare`；确认 `hybrid_search` 与 RRF 参数 |
| 选型 | 对比"只用 seekdb""只用 PowerContext""两者结合" | 选择两者结合，理由：单独任一方都无法同时覆盖"证据可追溯"与"偏好可复用" |
| 骨架 | 建立 `app/` 模块划分与 `.env` 配置 | `config.py` / `ingest.py` / `store.py` / `memory.py` / `llm.py` / `retrieval.py` / `service.py` / `main.py` |
| 检索 | 用 `pyseekdb` 建立 `docs` / `chunks`，配置 HNSW（cosine, 1024）+ IK 全文索引，调用 `hybrid_search` | 冒烟脚本验证：向量与全文两路都能命中，RRF 结果合理，`year` / `source_type` 过滤生效 |
| 记忆 | 封装 Scope 缓存、remember / search / prepare / list | 冒烟验证：创建 Scope、写入记忆、关键词检索、prepare 返回 ready |
| 应用 | FastAPI 路由 + 原生前端（资料库 / 对话 / 检索追踪 / 记忆面板） | 三栏界面，引用可点击定位，状态灯显示三项依赖 |
| 验证 | `scripts/seed.py` 与 `scripts/verify_demo.py` | 三次提问 + 7 项自动检查 + 日志落盘 |
| 文档 | README / RUNBOOK / VERIFICATION / 本记录 | 提交材料 |

## 3. 关键决策与原因

1. **通义千问 + text-embedding-v3（DashScope，OpenAI 兼容）**
   国内网络可直接访问、同时提供对话与 embedding、维度 1024 与 pyseekdb 默认 HNSW 配置匹配。
2. **seekdb 嵌入式优先，Docker 兜底**
   嵌入式零部署，适合评审快速复现；但 `pylibseekdb` 仅支持 Linux/macOS，
   因此 RUNBOOK 给出 Windows + Docker（`oceanbase/seekdb:latest`，2881）的等价路径。
3. **PowerContext 独立进程，端口 8123**
   默认 8000 在本机被其他服务占用；没有去杀陌生进程，而是显式改端口并写进配置示例，
   避免"跑起来靠运气"。
4. **记忆检索传关键词而不是整句**
   实测整句中文"回答风格偏好"在文本检索下为空，而"回答""检索增强生成"能命中。
   原因是 PowerContext 文本检索按词项匹配。因此在 `service.ask` 中先用 jieba 抽关键词
   （`app/retrieval.py::extract_keywords`）再查记忆，稳定性明显提升。
5. **记忆模式默认 `text`，向量记忆作为可选增强**
   未配置 embedding 时 `mode: hybrid` 会让 Server 返回 internal_error；
   为保证"评审不开任何模型也能跑通记忆"，默认 text，向量记忆通过 `config/powercontext.env` 开启。
6. **前端不引入构建链**
   评审环境 Node 版本不确定，使用原生 HTML/CSS/JS，`uvicorn` 单进程即可提供页面。
7. **降级路径全部可见**
   没有 key、没有 PowerContext、seekdb 连不上时，界面用状态灯和错误文案说明原因，
   而不是静默失败或返回假数据。
8. **新增零凭据本地向量后端（`EMBEDDING_BACKEND=local`）**
   评审未必持有 DashScope Key。本地哈希向量（字符 n-gram → 384 维、L2 归一化）让
   HNSW + IK + RRF 的完整链路可以离线跑通；两套维度使用不同 collection（`*_local`），
   互不干扰。真实语义效果仍以 DashScope 模式为准。
9. **长期偏好每轮固定注入**
   只靠关键词检索会漏掉不含本轮词的偏好。改为用 `kind=preference` 列表把生效偏好
   全部取出（去重、最多 5 条），放在记忆上下文最前面；问题相关的历史结论仍由
   `atomic-memory/search` + `context/prepare` 提供。

## 4. 开发中遇到并修复的问题

| 问题 | 现象 | 修复 |
| --- | --- | --- |
| 嵌入式 seekdb 未建库 | `Unknown database 'papermind'` | `store.py::_ensure_database`：嵌入式用 `AdminClient.create_database`，server 模式用 `CREATE DATABASE IF NOT EXISTS`（库名正则校验） |
| 向量维度被默认 embedding 覆盖 | 建 collection 时报 4 vs 384 维度不匹配 | 创建 `Schema` 时 `VectorIndexConfig` 显式传入 `embedding_function`，并以 `EMBEDDING_DIM=1024` 统一 |
| PowerContext 端口冲突 | 启动报 `address already in use`，8000 上是无关服务 | 改用 8123，同步 `.env` / 示例配置 / 文档 |
| 记忆整句检索为空 | `atomic-memory/search` 返回空 | 改为关键词检索（见决策 4） |
| `hybrid` 记忆模式报错 | Server internal_error | 默认 `mode: text`；文档说明启用 embedding 后再用语义模式 |
| PDF 被读取两次 | 早期 `parse_document` 对同一文件重复解析 | 只读一次，再按后缀选择解析分支 |
| WSL 临时目录被回收 | `/tmp` 脚本丢失 | 脚本移入工作区，通过 `/mnt/...` 调用 |
| Windows 换行符破坏脚本 | bash 报 `$'\r'` | 统一以 `\n` 写入脚本 |
| 占位 Key 被当成真实 Key | 用 `.env.example` 的占位值启动，调用模型返回 401 | `has_llm` 识别 `sk-replace` 前缀并按未配置处理 |
| WSL 下嵌入式 seekdb 打不开库 | `seekdb_open failed: code=-1` | 挂载盘（`/mnt/*`）不支持其文件语义：代码给出明确报错，RUNBOOK 要求把数据目录指到 Linux 原生路径，或改用 Docker |
| 偏好未进入注入上下文 | 关键词检索只命中了 `working_note` | 增加 `kind=preference` 列表查询，偏好固定排在最前 |

## 5. Qoder 在本项目中的具体作用

- **调研**：抓取并归纳 PowerContext 官方文档与 pyseekdb 源码中的 API 签名，避免凭记忆写错参数。
- **方案**：给出"混合检索 + 长期记忆"的分工边界，并解释 RRF 参数与过滤条件的落点。
- **编码**：生成全部后端模块、前端三份静态文件、两个脚本；保持模块间只通过 `service` 编排。
- **调试**：根据报错定位到"未建库""维度覆盖""端口占用""分词检索"四个根因，并给出最小修复。
- **文档**：生成 README / RUNBOOK / VERIFICATION，并核对命令与实际参数名
  （例如 `POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_*` 的完整前缀）。

人工确认的部分：

- 真实 API Key 只写入本地 `.env`，仓库内全部为占位符。
- 未使用截图中出现的任何访问令牌；发现该令牌疑似真实凭据时已提示吊销。
- 端口 8000 上的陌生服务保持原样，不做任何终止操作。

## 6. 可复核的提交物

| 材料 | 位置 |
| --- | --- |
| 代码 | 本目录（`qoder/papermind`） |
| 运行说明 | `README.md`、`docs/RUNBOOK.md` |
| 验证样例（含初始数据 / 输入 / 步骤 / 预期结果 / 技术作用） | `docs/VERIFICATION.md`、运行时生成 `docs/verification-log.txt` |
| 开发记录（含 UID） | 本文件 |
| 项目网站 | <https://papermind-3hxelpzw5at.qoder.website>（Qoder Sites 发布，任何人可访问） |
