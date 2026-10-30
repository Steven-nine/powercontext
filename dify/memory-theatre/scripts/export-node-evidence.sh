#!/usr/bin/env bash
# 从 Dify 的 PostgreSQL 导出最近若干次 Workflow 的节点执行记录，作为运行证据。
#
#   bash scripts/export-node-evidence.sh [运行次数，默认 6]
#
# 导出内容只包含节点状态、耗时与截断后的输入输出，不导出可能带凭据的
# headers / process_data。
set -euo pipefail
cd "$(dirname "$0")/.."

RUNS="${1:-6}"
CONTAINER="${DIFY_PG_CONTAINER:-arcade-postgres}"
OUT="evidence/dify-node-executions.json"

docker exec "$CONTAINER" psql -U postgres -p 5433 -d dify -Atc \
  "select json_build_object(
      'run_id', e.workflow_run_id,
      'index', e.index,
      'node_id', e.node_id,
      'node_type', e.node_type,
      'title', e.title,
      'status', e.status,
      'elapsed_seconds', round(extract(epoch from (e.created_at - e.created_at))::numeric, 3),
      'inputs', left(e.inputs::text, 400),
      'outputs', left(e.outputs::text, 400),
      'error', left(coalesce(e.error, ''), 300)
   )::text
   from workflow_node_executions e
   where e.workflow_run_id in (
       select workflow_run_id from (
           select workflow_run_id, max(created_at) as last_at
           from workflow_node_executions
           group by workflow_run_id
           order by last_at desc
           limit $RUNS
       ) recent
   )
   order by e.created_at desc, e.index" >/tmp/theatre-node-executions.jsonl

mkdir -p evidence
python3 - <<'PY'
import json
import pathlib
from collections import OrderedDict

source = pathlib.Path("/tmp/theatre-node-executions.jsonl")
runs = OrderedDict()
for line in source.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    record = json.loads(line)
    run_id = record.pop("run_id")
    runs.setdefault(run_id, []).append(record)

payload = {
    "runtime": "Dify 1.9.2 (langgenius/dify-api) + PostgreSQL 15",
    "source": "workflow_node_executions 表（只导出状态/耗时/截断的输入输出）",
    "runCount": len(runs),
    "nodeCount": sum(len(nodes) for nodes in runs.values()),
    "runs": [
        {"run_id": run_id, "nodes": nodes}
        for run_id, nodes in runs.items()
    ],
}
out = pathlib.Path("evidence/dify-node-executions.json")
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("wrote", out, "runs:", len(runs), "nodes:", payload["nodeCount"])
PY
