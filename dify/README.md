# dify/ —— 本目录的资产说明

| 子目录 | 内容 | 状态 |
| --- | --- | --- |
| [`memory-theatre/`](memory-theatre/) | 《记忆剧场 · 门卫阿铁》：Dify 1.9.2 Workflow + PowerContext 记忆层 + 零依赖网页入口 | 可运行，已完成真实联调 |

## 《记忆剧场》一句话

门卫阿铁会记住旅人对他干过的每一件坏事——整蛊过他，下一幕他就翻旧账；随口一句话，他当成口头禅一直念叨。
Dify 负责 12 个节点的流程编排，PowerContext 负责"记住"这件事本身，记忆落库后可跨服务重启存活。

- 运行说明：[memory-theatre/README.md](memory-theatre/README.md)
- 验证样例与实际结果：[memory-theatre/VERIFICATION.md](memory-theatre/VERIFICATION.md)
- 节点与协议细节：[memory-theatre/TECHNICAL_NOTE.md](memory-theatre/TECHNICAL_NOTE.md)
- 提交用的 Dify DSL：[memory-theatre/dsl/memory-theatre-workflow.yml](memory-theatre/dsl/memory-theatre-workflow.yml)

## 快速验证（Linux / WSL2）

```bash
cd dify/memory-theatre
bash scripts/start-dify-local.sh          # 真实 Dify（Docker）
bash scripts/start-powercontext.sh        # 真实 PowerContext
python3 scripts/configure-local.py --initialize   # 导入 DSL + 发布 + 生成应用 Key
python3 scripts/verify.py                 # 4 幕主线路 + 玩家隔离 + 写后读回
python3 scripts/serve.py                  # 打开 http://127.0.0.1:8787 开玩
```
