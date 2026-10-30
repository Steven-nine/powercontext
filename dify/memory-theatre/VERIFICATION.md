# 验证样例与实际运行结果

以下全部是**真实执行**的结果：真实 Dify 1.9.2（`langgenius/dify-api:1.9.2` 容器）+ 真实 PowerContext 1.4.1
（SQLite）+ 本仓库的 Code Executor。**没有 mock、没有外部模型、没有预先灌好的数据。**
运行时间：2026-10-30 22:40–22:50 (+08:00)，主机为 Windows 11 + WSL2 Ubuntu 24.04。

复现命令见 [README.md §7](README.md#7-验证)。

---

## 1. 初始条件

- 一个**全新玩家标识**（每次运行自动生成，例如 `theatre-player-61c0dbca`），对应一个**空的** PowerContext scope。
- Dify 应用已导入并发布，DSL 的 `POWERCONTEXT_URL` 指向 `http://127.0.0.1:8124`。
- 频道：`surreal`（荒诞喜剧）。
- 重复本样例不需要清理数据库：换一个新 `player_id` 就是一条全新的故事线。

## 2. 样例 A：四幕主线路（`scripts/verify.py`）

| 顺序 | 输入 | 预期 | 实际输出（节选） |
| --- | --- | --- | --- |
| 1 | `A 调查移动的出口` | 第 1 幕；信任 1 / 混乱 0 / 硬币 3；没有任何历史记忆 | `第 1 幕 · 荒诞城门`／`阿舟，这是你们第一次见面，阿铁把你的名字写在了会自己逃跑的登记簿上。`／`状态：信任 1 / 混乱 0 / 硬币 3` |
| 2 | `B 整蛊鸽子议会` | 第 2 幕；混乱 +1；**引用上一幕** | `阿舟，门卫阿铁还记得你上一幕干的事：'A 调查移动的出口'。`／`状态：信任 1 / 混乱 1 / 硬币 3` |
| 3 | `C 和门卫协商` | 第 3 幕；信任 +2、硬币 −1；**门卫翻旧账** | `而且阿铁翻起了旧账：'上回你干的那事——B 整蛊鸽子议会——我到现在还记着。'`／`状态：信任 3 / 混乱 1 / 硬币 2` |
| 4 | `C 再次协商` | 第 4 幕；信任 5 → **达成结局【门卫合伙人】** | `达成结局【门卫合伙人】：阿铁把备用钥匙塞进你手里，说从今天起你替他值班。`／`状态：信任 5 / 混乱 1 / 硬币 1` |

每一步都自动断言并打印 `[ok]`：

```
[ok] 幕次推进到第 1 幕          [ok] 本幕记忆写入后可读回        [ok] 读回命中数 1 ≥ 已发生幕数 1
[ok] 第一幕没有历史记忆        [ok] 第 2 幕复用了上一幕记忆      [ok] 第二幕被识别为整蛊（门卫记仇）
[ok] 第 3 幕复用了上一幕记忆    [ok] 第三幕门卫翻旧账（引用上一幕的恶作剧）
[ok] 第 4 幕复用了上一幕记忆    [ok] 第四幕达成成就【门卫合伙人】
```

## 3. 样例 B：记忆回执（证明"真的写进数据库了"）

每一幕的 Workflow 输出都带一个 `receipt`，它由**工作流的第 9–11 个节点**产生：
写入 → 再次检索 → 比对文本。实测第 4 幕的回执：

```json
{
  "scope_id": "scp_7xsszncjzq8qr36w2h7q20qb8v",
  "memory_artifact": {
    "artifact_id": "art_1b11185352394b6c903dd83eded9f1ec",
    "revision": 1,
    "family": "atomic-memory",
    "kind": "decision",
    "state": "active"
  },
  "read_back_hits": 5,
  "read_back_verified": true,
  "round": {
    "turn": 5, "trust": 6, "chaos": 1, "coins": 1,
    "action_kind": "investigate", "channel": "surreal",
    "history_found": 4, "history_hits": 4,
    "recalled_previous": true, "grudge_used": false, "motto_used": false,
    "ending": "达成结局【门卫合伙人】：…", "player_id": "theatre-player-61c0dbca"
  }
}
```

字段含义：

- `scope_id` —— 该玩家在 PowerContext 里的**记忆空间**（`POST /v1/scopes` 返回，幂等键 `memory-theatre-<player_id>`）；
- `memory_artifact.artifact_id` —— 本幕写入的记忆条目 ID（`POST /v1/memory/remember` 返回）；
- `read_back_verified: true` —— 写入后**再次检索**能在 PowerContext 里找到完全相同的那条记忆；
- `round.history_found / history_hits` —— 本幕开始时检索到的历史条数（0 → 1 → 2 → 3 → 4）。

## 4. 样例 C：换服务重启后继续玩（`scripts/verify.py --resume`）

操作：停掉 PowerContext 进程 → 用同一个 SQLite 文件重新启动 → `docker restart arcade-api` 重启 Dify。

实际结果（重启后的第 5 幕）：

```
第 5 幕 · 荒诞城门
阿舟，门卫阿铁还记得你上一幕干的事：'C 再次协商'。
▸ 你的行动：A 调查重启后仍在移动的出口
…
状态：信任 6 / 混乱 1 / 硬币 1
[ok] 重启后仍能续玩到第 5 幕
[ok] 重启后写入的记忆仍能读回
```

回执里 `history_found: 4`、`read_back_hits: 5`，说明**记忆在两次服务重启后完整存活**。

## 5. 样例 D：玩家隔离

用另一个玩家标识跑第一幕：

```
第 1 幕 · 荒诞城门
路人甲，这是你们第一次见面，阿铁把你的名字写在了会自己逃跑的登记簿上。
状态：信任 0 / 混乱 1 / 硬币 3
[ok] 新玩家没有任何历史记忆
[ok] 新玩家使用不同的记忆空间
```

两个玩家的 `scope_id` 不同，互不串台。

## 6. 样例 E：直接查 PowerContext（原始数据）

`scripts/verify.py` 最后一步直接调用 `POST /v1/memory/search`，把数据库里的原始条目导出到
`evidence/dify-real-workflow.json` 的 `powerContextMemory` 字段：

```json
{
  "scopeId": "scp_…",
  "mode": "text",
  "hitCount": 4,
  "hits": [
    {"artifact_id": "art_…", "revision": 1, "kind": "decision", "text_head": "记忆剧场\n{\"message\": \"A 调查移动的出口\", …"}
  ]
}
```

可以直接看到：每一条记忆的正文都以 `记忆剧场` 标签开头，后面跟着这一幕的 `message / answer / state` JSON。

## 7. 样例 F：规则引擎单元测试

```bash
python3 tests/test_rules.py
# Ran 11 tests in 0.002s — OK
```

覆盖：首幕无历史、整蛊被记仇、下一幕翻旧账、自由行动变口头禅、协商扣币加信任、
两个结局、三个频道、8192 字节上限、异常状态码与空动作。

## 8. 样例 G：网页体验

`python3 scripts/serve.py` 后打开 <http://127.0.0.1:8787>：

1. 右侧「记忆回执」面板实时显示幕次、信任/混乱/硬币、历史命中数、记忆空间 ID、记忆条目 ID、读回校验结果；
2. 右侧「门卫的笔记本」列出**直接从 PowerContext 查回来的记忆条目**（`art_…` 条目 ID + 正文），
   点「刷新」或每次行动后自动刷新——这里看到的就是数据库里真实存在的东西；
3. 点击 `B 整蛊鸽子议会` → 页面出现门卫的回应，回执出现 `art_…` 与 `读回校验 通过（1 条）`；
4. 再点一次 `C 和门卫协商` → 台词里出现「翻起了旧账」，回执的「复用上一幕」变为「是」；
5. 点「清空画面，保留记忆」→ 画面清空但身份不变，再点一次按钮仍能接着第 3 幕；
6. 点「换个新身份」→ 重新回到「第 1 幕」，且历史命中数为 0（隔离生效）。

`GET /api/health` 返回 Dify 与 PowerContext 的连通性：

```json
{"ok": true,
 "dify": {"configured": true, "status": 200, "step": "finished"},
 "powerContext": {"url": "http://127.0.0.1:8124", "status": 200}}
```

`GET /api/memories?playerId=<玩家标识>` 直接查 PowerContext 并返回条目列表（实测 5 条）：

```json
{"ok": true, "scope_id": "scp_7xsszncjzq8qr36w2h7q20qb8v", "mode": "text", "count": 5,
 "entries": [{"artifact_id": "art_6321827520154aa7afe37d6aafcbe556", "revision": 1,
              "kind": "decision", "state": "active",
              "text": "记忆剧场\n{\"message\": \"A 调查移动的出口\", \"answer\": \"第 1 幕 · 荒诞城门…"}]}
```

页面截图见 `evidence/ui-desktop.png`（1440×1000）与 `evidence/ui-mobile.png`（390×844，
无横向溢出），由 `scripts/capture-ui.py` 用 Playwright + 本机 Edge 真实操作生成，页面脚本报错数为 0。

## 9. 原始证据文件

| 文件 | 内容 |
| --- | --- |
| `evidence/dify-import.json` | 真实 Console API 导入结果（`import: completed`）、发布结果（`publish: success`）、应用 ID、**提交的 DSL 的 SHA256** |
| `evidence/dify-real-workflow.json` | 4 幕 + 隔离玩家 + 重启续玩 + 直接查询 PowerContext 的原始条目，每幕都带 Dify `workflow_run_id` |
| `evidence/dify-node-executions.json` | 从 Dify 的 PostgreSQL `workflow_node_executions` 表导出的 **72 个节点执行**（6 次运行 × 12 节点），全部 `succeeded` |

`dify-node-executions.json` 的单条记录形如：

```json
{"run_id": "…", "index": 6, "node_id": "rules", "node_type": "code",
 "status": "succeeded",
 "inputs": "{\"search_json\": \"{\\\"mode\\\":\\\"text\\\",\\\"hits\\\":[]}\", \"status_code\": 200, …}",
 "outputs": "{\"answer\": \"第 1 幕 · 荒诞城门…\", \"save_text\": \"记忆剧场\\n{…}\", \"meta\": \"{…}\"}",
 "error": ""}
```

可据此核对"哪一步调用了 PowerContext、返回了什么、规则引擎算出了什么"。

## 10. 边界与未覆盖项

- **没有接入真实外部模型**：本作品默认路径是"规则驱动 + 真实记忆"，不依赖任何模型账号；
  因此"AI 生成"部分由规则引擎承担，作品定位是"可离线复现的互动剧场"。
- `dify-sandbox:0.2.12` 的 Python runner 在 WSL2 上不可用（§6.2），本仓库改用自带 Code Executor；
  在普通 Linux 主机上可直接用官方沙箱，DSL 无需任何改动。
- 本文件只记录**实际跑出来的结果**，不包含未执行的假设。
