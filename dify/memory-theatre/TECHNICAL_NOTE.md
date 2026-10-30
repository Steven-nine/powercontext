# 技术说明：节点、协议与取舍

## 1. Workflow 拓扑（12 个节点，线性）

```
start(玩家输入)
  → scope_req      (code)   拼装 POST /v1/scopes 的请求体
  → scope_create   (http)   POST {PC}/v1/scopes          幂等键 memory-theatre-<player_id>
  → scope_parse    (code)   取 scope_id，拼装检索请求体
  → search         (http)   POST {PC}/v1/memory/search   {scope_id, query:"记忆剧场", limit:50}
  → rules          (code)   规则引擎：还原状态 → 结算行动 → 生成台词 + 待写入记忆
  → remember_req   (code)   拼装写入请求体
  → remember       (http)   POST {PC}/v1/memory/remember  {scope_id, kind:"decision", text}
  → verify_req     (code)   校验写入响应（changed / records / artifact_id）
  → verify_read    (http)   POST {PC}/v1/memory/search   读回校验
  → receipt        (code)   比对读回文本，产出记忆回执
  → end            ���出 answer + receipt
```

`{PC}` = DSL 里的环境变量 `POWERCONTEXT_URL`（导入时由 `configure-local.py` 注入实际地址）。
**Dify 直连 PowerContext，中间没有任何自建网关或代理**，因此链路短、可审计、少一个故障点。

### 节点职责

| 节点 | 类型 | 输入 | 输出 | 为什么这样切分 |
| --- | --- | --- | --- | --- |
| `scope_req` | code | player_id | scope_body | 幂等键必须和 player_id 绑定，才能让同一个玩家复用同一个 scope |
| `scope_parse` | code | body, status_code | scope_id, search_body | 把 HTTP 响应转成下一步需要的变量；非 2xx 直接报错 |
| `rules` | code | 检索结果 + 玩家输入 | answer, save_text, meta | 规则引擎的完整源码就是 `dsl/theatre_rules.py`，被原样嵌入 |
| `verify_req` | code | 写入响应 | verify_body, saved | 先确认"写成功"，再决定要不要读回 |
| `receipt` | code | 读回结果 + 本幕文本 | receipt | **写后读回**：文本逐字相等才算数，否则整轮失败 |

### 输出条数必须与 schema 一致

Dify 1.9 的 Code 节点会校验 `len(声明的 outputs) == len(返回的 dict)`，多一个键就会报
`Not all output parameters are validated.`。因此 `theatre_rules.py` 的返回值与
`build_dsl.py` 里的 `outputs` 声明严格一一对应（`answer` / `save_text` / `meta`），
改动规则时**必须同时改这两处**，或直接跑 `python3 scripts/build_dsl.py` 重新生成。

## 2. 记忆协议（PowerContext 1.4.1）

| 步骤 | 接口 | 请求 | 本作品用到的返回字段 |
| --- | --- | --- | --- |
| 建记忆空间 | `POST /v1/scopes` | `{title, summary, idempotency_key}` | `scope_id` |
| 检索历史 | `POST /v1/memory/search` | `{scope_id, query, limit}` | `hits[].memory.text`（1.4.x 结构） |
| 写入记忆 | `POST /v1/memory/remember` | `{scope_id, kind, text}` | `changed`、`records[].artifact` |
| 读回校验 | `POST /v1/memory/search` | 同上 | `hits[].memory.text` 与写入文本逐字比对 |

要点：

- **幂等**：`idempotency_key = "memory-theatre-" + player_id`，同一个玩家反复调用 `POST /v1/scopes`
  始终返回同一个 `scope_id`（实测第 1 次与第 2 次均为 `scp_3mrqbvep47d949et9g1ryk0pxx`），
  所以工作流可以无状态地每幕重建 scope。
- **检索用标签而不是语义**：`query` 固定为 `记忆剧场`，每条记忆正文也以 `记忆剧场\n` 开头，
  于是全文检索能稳定命中本作品的全部历史（实测 `mode: "text"`）。
- **8192 字节上限**：PowerContext 单条记忆上限 8192 UTF-8 字节，超限返回 422。
  规则引擎在写入前自己检查，并把超长文本显式拒绝（而不是静默截断）。
- **记忆条目形态**：`{"message": 玩家这一句, "answer": 本幕台词, "state": {...}, "channel": ..., "kind": ...}`，
  `state` 里保存 `turn/trust/chaos/coins/grudge/motto`，下一幕从这里恢复。

### 状态是怎么"复原"的

规则引擎不信任客户端传来的任何状态：每一幕都从检索到的历史里挑 `state.turn` 最大的一条作为当前状态，
再叠加本幕行动。因此：

- 状态只存在于 PowerContext，**不在浏览器、不在 Dify 数据库里**；
- 删掉浏览器 localStorage、换台机器，只要 `player_id` 相同且 PowerContext 数据还在，就能接着玩。

## 3. 设计取舍

| 选择 | 原因 | 代价 |
| --- | --- | --- |
| 默认不接 LLM | 评审无需任何模型账号即可完整体验；记忆与规则行为可复现、可断言 | 台词是模板拼装，不是自由生成 |
| 直连 PowerContext，不做网关 | 少一个组件、少一层鉴权，链路更容易被评审核对 | 需要 Dify 容器能访问 PowerContext 地址 |
| 自带 Code Executor | 官方沙箱在 WSL2 上不可用；自带实现让"换机器复现"成立 | 多一个进程；只适合本机演示 |
| 记忆用标签全文检索 | 不依赖 embedding 服务，零模型即可检索 | 语义检索能力没有用到 |
| 状态存在记忆条目里 | 单一数据源，重启后天然恢复 | 记忆条目会随幕数变长，受 8192 字节限制 |

## 4. 可扩展点

- **接真实模型**：把 `rules` 节点换成 LLM 节点，保留 `scope_parse` / `search` / `remember` / `verify_read`，
  让模型只负责生成台词、状态仍由 code 节点结算——这样既有生成能力又有确定性。
- **多玩家/多角色**：把 `player_id` 换成 `(player_id, role)` 组合即可派生多条记忆线。
- **知识库**：PowerContext 的记忆检索支持 `mode: vector/hybrid`（需要 embedding 服务），
  接入后同一套流程即可做语义检索。
- **换数据库**：PowerContext 支持 SQLite / 内嵌 seekdb / OceanBase（外部服务需 MySQL 用户租户）。
