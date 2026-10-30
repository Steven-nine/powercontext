# 证据清单

运行 `scripts/demo.sh` 或 `DRY_RUN=1 bash scripts/demo.sh` 后，本目录的 `logs/` 记录以下材料：

| 文件 | 证明内容 |
| --- | --- |
| `before.log` | 修改前目标测试失败、回归测试通过（含命令输出与退出码） |
| `after.log` | 修改后全部测试通过 |
| `context-before.json` / `context-after.json` | 上下文包内容与来源路径 |
| `context-for-minimax.json` / `prompt-for-minimax.md` | 实际交给 MiniMax 的上下文与提示词 |
| `mcode-stream.json` | MiniMax Code 的运行记录（真实执行时生成） |
| `mcode-final.json` | MiniMax Code 最终消息与结果（真实执行时生成） |
| `code.diff` | 代码修改差异 |
| `pc-restart.txt` | PowerContext 保存状态、重启服务后读取成功 |
| `seekdb-query.txt` | seekdb 检索结果（来源路径与命中内容） |
| `before-dryrun.log` / `after-dryrun.log` | 无额度时用参考补丁验证流水线的记录 |

`patches/min_total.patch` 是参考补丁，仅用于无 MiniMax 额度时验证流水线，不作为最终修改证据。
