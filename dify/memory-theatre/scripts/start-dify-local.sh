#!/usr/bin/env bash
# 启动一套最小可用的真实 Dify（Linux / WSL2，需要 Docker Engine）。
#
# 只启动 4 个容器，全部使用 host networking：
#   arcade-postgres  PostgreSQL 15  127.0.0.1:5433
#   arcade-redis      Redis 6       127.0.0.1:6381
#   arcade-sandbox    Dify Sandbox  127.0.0.1:8194
#   arcade-api        Dify API      127.0.0.1:5001
#
# 不安装 Dify 的 Web 控制台前端；本作品的玩法入口是 Dify 的 Workflow API
# 与仓库内附带的单文件网页（scripts/serve.py）。
#
# 常用环境变量：
#   ARCADE_IMAGE_PREFIX   镜像前缀，例如 docker.m.daocloud.io/（默认直连 Docker Hub）
#   ARCADE_RUNTIME_DIR    运行期文件目录（默认 ./.runtime）
set -euo pipefail
cd "$(dirname "$0")/.."

RUNTIME_DIR="${ARCADE_RUNTIME_DIR:-$(pwd)/.runtime}"
mkdir -p "$RUNTIME_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "需要 Docker Engine（WSL2 内可用 apt install docker.io 快速安装）" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon 未运行，请先执行： sudo systemctl start docker" >&2
  exit 1
fi

ENV_FILE="$RUNTIME_DIR/dify.env"
if [ ! -f "$ENV_FILE" ]; then
  python3 - "$ENV_FILE" <<'PY'
import secrets
import sys
from pathlib import Path

target = Path(sys.argv[1])
password = secrets.token_hex(24)
target.write_text(
    f"""DB_HOST=127.0.0.1
DB_PORT=5433
DB_USERNAME=postgres
DB_PASSWORD={password}
DB_DATABASE=dify
POSTGRES_PASSWORD={password}
POSTGRES_DB=dify
REDIS_HOST=127.0.0.1
REDIS_PORT=6381
REDIS_PASSWORD=
CELERY_BROKER_URL=redis://127.0.0.1:6381/1
SECRET_KEY={secrets.token_hex(32)}
CODE_EXECUTION_ENDPOINT=http://127.0.0.1:8194
CODE_EXECUTION_API_KEY={secrets.token_hex(24)}
STORAGE_TYPE=local
STORAGE_LOCAL_PATH=storage
OPENDAL_SCHEME=fs
OPENDAL_FS_ROOT=storage
SSRF_PROXY_HTTP_URL=
SSRF_PROXY_HTTPS_URL=
PLUGIN_DAEMON_URL=http://127.0.0.1:5002
CHECK_UPDATE_URL=
MARKETPLACE_ENABLED=false
MIGRATION_ENABLED=true
""",
    encoding="utf-8",
)
target.chmod(0o600)
print("wrote", target)
PY
fi

PREFIX="${ARCADE_IMAGE_PREFIX:-}"
ensure_container() {
  local name="$1"
  shift
  if docker container inspect "$name" >/dev/null 2>&1; then
    docker start "$name" >/dev/null
  else
    docker run -d --name "$name" --restart unless-stopped --network host "$@" >/dev/null
  fi
}

ensure_container arcade-postgres --env-file "$ENV_FILE" -v arcade-postgres:/var/lib/postgresql/data \
  "${PREFIX}postgres:15-alpine" postgres -p 5433 -c listen_addresses=127.0.0.1
ensure_container arcade-redis "${PREFIX}redis:6-alpine" redis-server --port 6381 --bind 127.0.0.1

for _ in $(seq 1 30); do
  if docker exec arcade-postgres pg_isready -p 5433 -U postgres >/dev/null 2>&1; then break; fi
  sleep 1
done

# Code 节点的执行端点：
#   THEATRE_CODE_EXECUTOR=local   （默认）用本仓库自带的 Code Executor，任何内核都能跑
#   THEATRE_CODE_EXECUTOR=official 用官方 dify-sandbox 容器（普通 Linux 主机上可用）
CODE_EXECUTION_ENDPOINT_VALUE="http://127.0.0.1:8194"
EXECUTOR_MODE="${THEATRE_CODE_EXECUTOR:-local}"
if [ "$EXECUTOR_MODE" = "local" ]; then
  EXECUTOR_PORT="${CODE_EXECUTOR_PORT:-8195}"
  SANDBOX_KEY=$(sed -n 's/^CODE_EXECUTION_API_KEY=//p' "$ENV_FILE")
  if [ -f "$RUNTIME_DIR/code-executor.pid" ] && kill -0 "$(cat "$RUNTIME_DIR/code-executor.pid")" 2>/dev/null; then
    echo "Code Executor 已在运行（pid $(cat "$RUNTIME_DIR/code-executor.pid")）"
  else
    CODE_EXECUTION_API_KEY="$SANDBOX_KEY" CODE_EXECUTOR_PORT="$EXECUTOR_PORT" \
      nohup python3 scripts/code_executor.py >"$RUNTIME_DIR/code-executor.log" 2>&1 &
    echo $! >"$RUNTIME_DIR/code-executor.pid"
    echo "started bundled Code Executor on port $EXECUTOR_PORT (log: $RUNTIME_DIR/code-executor.log)"
  fi
  CODE_EXECUTION_ENDPOINT_VALUE="http://127.0.0.1:${EXECUTOR_PORT}"
else
  SANDBOX_KEY=$(sed -n 's/^CODE_EXECUTION_API_KEY=//p' "$ENV_FILE")
  ensure_container arcade-sandbox -e API_KEY="$SANDBOX_KEY" -e GIN_MODE=release -e ENABLE_NETWORK=true \
    "${PREFIX}langgenius/dify-sandbox:0.2.12"
fi

# Dify API 每次都用当前配置重建（数据都在 named volume 里，重建不会丢应用与数据库）
docker rm -f arcade-api >/dev/null 2>&1 || true
ensure_container arcade-api --env-file "$ENV_FILE" -e MODE=api -e SERVER_WORKER_AMOUNT=1 \
  -e CODE_EXECUTION_ENDPOINT="$CODE_EXECUTION_ENDPOINT_VALUE" \
  -v arcade-storage:/app/api/storage "${PREFIX}langgenius/dify-api:1.9.2"

python3 - <<'PY'
import json
import time
import urllib.request

for attempt in range(120):
    try:
        with urllib.request.urlopen("http://127.0.0.1:5001/console/api/setup", timeout=3) as response:
            print("Dify Console API ready, setup step =", json.load(response)["step"])
        break
    except Exception:  # noqa: BLE001
        time.sleep(1)
else:
    raise SystemExit("Dify 没有启动成功，请执行 docker logs --tail 100 arcade-api")
PY

cat <<'EOF'

Dify 已就绪。下一步：
  1) 启动 PowerContext： bash scripts/start-powercontext.sh
  2) 导入并发布 DSL：   python3 scripts/configure-local.py --initialize
  3) 体验网页：         python3 scripts/serve.py   (打开 http://127.0.0.1:8787)
EOF
