# 验证样例（VERIFICATION）

本页给出可复核的端到端样例：初始数据、输入、操作步骤、预期结果，以及
seekdb 与 PowerContext 各自在结果中的可见证据。

脚本：`scripts/verify_demo.py`　输出：`docs/verification-log.txt`（运行时生成，已 gitignore）

---

## 1. 初始数据

`data/samples/` 下 6 篇原创中文语料（带 YAML front matter）：

| 文件 | 标题 | 类型 | 年份 | 主题 |
| --- | --- | --- | --- | --- |
| `rag-foundations.md` | RAG 基础：检索增强生成的工作流 | paper | 2024 | RAG、检索、生成 |
| `hybrid-retrieval.md` | 混合检索：向量通道与全文通道的融合 | paper | 2025 | 混合检索、RRF |
| `chunking.md` | 文本切片策略与重叠控制 | note | 2024 | 切片、overlap |
| `agent-memory.md` | 智能体的长期记忆与跨会话复用 | paper | 2025 | 记忆、持久化 |
| `rag-evaluation.md` | RAG 系统评测指标 | note | 2023 | 评测、忠实度 |
| `embedding-selection.md` | 向量模型选型 | note | 2025 | embedding、维度 |

初始状态：

- seekdb：空库，首次运行自动创建 `papermind` 数据库与 `docs` / `chunks` collection。
- PowerContext：空 Scope；应用首次提问时为 `demo-user` 创建 `papermind · demo-user`。
- 无任何历史偏好，因此第一轮回答不会出现"按你的偏好……"之类内容。

## 2. 操作步骤

前置：PowerContext 已在 `127.0.0.1:8123` 启动，`.env` 已填真实 `DASHSCOPE_API_KEY`。

```bash
python -m scripts.seed          # 导入 6 篇语料
python -m scripts.verify_demo   # 三次提问 + 记忆复用 + 7 项检查
```

也可以在页面上复现同样的流程（见第 5 节）。

## 3. 输入与预期结果

### Q1（无历史记忆）

> 混合检索里向量通道和全文通道分别擅长什么？RRF 的 k 一般取多少？

**预期**

1. 答案只依据检索片段，对"向量通道擅长语义近似、全文通道擅长精确术语/数字"给出对照说明，
   RRF 的 `k` 取 60（与示例语料一致），关键论断带 `[n]`。
2. 引用列表包含《混合检索：向量通道与全文通道的融合》。
3. 检索追踪中：
   - `mode` 为 `hybrid_search · vector KNN + fulltext (IK) + RRF`；
   - `vector_route` 与 `fulltext_route` 各自非空，且两者的命中不完全相同
     （这正是混合检索存在的意义）；
   - `fused` 为 RRF 融合后的最终 6 条。
4. 记忆：命中 0 条；回答后回写 1 条 `working_note`。

**技术证据**：`vector_route` 由 seekdb HNSW 向量索引产生，`fulltext_route` 由 IK 全文索引产生，
`fused` 由 seekdb 内部的 RRF 计算，应用侧只做展示——说明检索确实发生在数据库内。

### Q2（表达长期偏好）

> 以后回答请先给结论，再给依据，控制在 400 字以内。

**预期**

1. 识别为偏好表达，写入一条 `preference` 记忆，正文为整句请求。
2. 本轮仍照常回答（该句本身是元指令，允许检索结果为空或很少）。
3. 「长期记忆」面板的 `written` 中出现 `kind = preference`。

**技术证据**：`POST /v1/memory/remember` 返回的 `records[].artifact.artifact_id` 可在
PowerContext Dashboard 中查到，说明记忆落在 PowerContext 而非应用内存。

### Q3（复用记忆）

> 请按我的回答偏好来：文档切片重叠一般设多少？

**预期**

1. 检索命中《文本切片策略与重叠控制》，答案给出重叠比例建议并带引用。
2. 记忆命中包含 Q1 / Q2 的 `working_note`。
3. `memory.preferences` 固定返回该用户的全部生效偏好，`memory_context` 首段即
   「【用户长期偏好】- 以后回答请先给结论，再给依据，控制在 400 字以内。」，
   随后才是 PowerContext `prepare` 返回的历史上下文——说明偏好跨轮次生效，
   且不依赖本轮提问是否恰好命中偏好文本。
4. 回答遵循"先结论后依据、400 字以内"。

**技术证据**：`prepared_context` 来自 PowerContext 的 `/v1/context/prepare`；
应用把它原样放进系统提示的【长期记忆】段，因此"偏好生效"可直接在响应里核对。

## 4. 脚本的 7 项检查

| # | 检查 | 通过条件 |
| --- | --- | --- |
| 1 | seekdb 已建立索引 | `documents > 0` |
| 2 | 混合检索返回引用 | Q1 引用数 > 0 |
| 3 | 向量通道有命中 | Q1 `trace.vector_route` 非空 |
| 4 | 全文通道有命中 | Q1 `trace.fulltext_route` 非空 |
| 5 | PowerContext 可用 | `/health/live` 200 |
| 6 | 偏好被写入记忆 | Q2 `written` 含 `kind = preference` |
| 7 | 后续提问复用偏好 | Q3 `memory.preferences` 非空，且 `memory_context` 含偏好原文（`400`） |

脚本退出码：全部通过 `0`，有失败 `2`；库为空时提示先执行 seed 并返回 `1`。

### 实测记录

运行 `python -m scripts.verify_demo` 后，终端输出同时写入 `docs/verification-log.txt`。
提交材料中附上该日志（含时间戳、seekdb 模式、三条问题的引用与追踪、7 项结论）即可复核。

日志首行会记录本次的向量后端与对话模型状态：

- `向量后端：dashscope（1024 维） · 对话模型：已配置`：完整模式，答案由通义千问生成。
- `向量后端：local（384 维） · 对话模型：未配置（降级为证据清单）`：零凭据模式，
  检索、引用、偏好注入、记忆回写全部照常，只是答案改为列出证据片段。
  该模式用于证明链路可跑通，不用于评价生成质量。

若日志中第 3、4 项任一为 FAIL，请先确认 `.env` 的 `EMBEDDING_DIM=1024`（local 模式为 384）
且没有残留旧库（`rm -rf data/seekdb` 后重新 seed）。

## 5. 页面复核清单

打开 <http://127.0.0.1:8080>，依次确认：

- [ ] 顶部 seekdb / 记忆 / 模型 三个灯为绿色（悬停可看错误原因）。
- [ ] 左侧 6 篇资料；按类型 `paper` 或年份 `2025` 过滤后列表变化，且随后提问的引用只来自过滤范围。
- [ ] 提问 Q1：答案中 `[n]` 可点击，点击后左侧对应文档高亮闪烁。
- [ ] 「检索追踪」能看到关键词、过滤条件、RRF 融合 Top、两路独立命中。
- [ ] 提问 Q2 后，右侧「长期记忆」出现新的 `preference` 条目。
- [ ] 提问 Q3 时，右侧「长期记忆」顶部固定展示「长期偏好 · 每轮生效」，
      「检索追踪」的注入上下文以【用户长期偏好】开头。
- [ ] 「导入」弹窗粘贴一段文本（标题+正文）后，资料库立即新增，且记忆页出现一条 `fact` 记录。

## 6. 失败样式的预期行为

| 场景 | 预期 |
| --- | --- |
| 未配置 `DASHSCOPE_API_KEY` | 状态灯提示模型不可用；提问返回"只列证据"的降级答案，引用仍完整 |
| PowerContext 未启动 | 状态灯红色；提问照常，`memory.error` 说明原因；记忆面板显示不可用 |
| seekdb 不可用 | `/api/health` 中 `seekdb.ok=false`；接口返回 503 且带排查提示 |
| 提问为空 / 超长 | 返回 400，不进入检索 |
| 不支持的文件格式 | 上传返回 400，列出支持的格式 |
