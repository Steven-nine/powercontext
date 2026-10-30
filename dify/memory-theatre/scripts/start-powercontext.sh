#!/usr/bin/env bash
# 启动本作品专用的 PowerContext 实例（默认 SQLite，后台运行）。
#
#   THEATRE_PC_PORT       监听端口，默认 8124
#   THEATRE_PC_DB         sqlite（默认）| seekdb-embedded
#   THEATRE_PC_DIR        运行目录，默认 ./.runtime/powercontext
#   THEATRE_PC_BIN        powercontext 可执行文件，默认 `powercontext`
#
# 说明：PowerContext 的 HTTP API 是本作品的持久层，Dify 通过
# {{#env.POWERCONTEXT_URL#}} 直连，不经过任何自建网关。
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${THEATRE_PC_PORT:-8124}"
DB="${THEATRE_PC_DB:-sqlite}"
RUNTIME="${THEATRE_PC_DIR:-$(pwd)/.runtime/powercontext}"
BIN="${THEATRE_PC_BIN:-powercontext}"

if ! command -v "$BIN" >/dev/null 2>&1; then
  echo "找不到 powercontext 可执行文件，请先安装： pip install 'powercontext[cli,server]==1.4.1'" >&2
  exit 1
fi

mkdir -p "$RUNTIME"
cd "$RUNTIME"

ENV_FILE="$RUNTIME/powercontext.env"
if [ ! -f "$ENV_FILE" ]; then
  {
    echo "POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1"
    echo "POWERCONTEXT_SERVER_HTTP_PORT=${PORT}"
    echo "POWERCONTEXT_SERVER_ACCESS_MODE=disabled"
    echo "POWERCONTEXT_SERVER_DASHBOARD_ENABLED=false"
    echo "POWERCONTEXT_SERVER_LOGGING_LEVEL=INFO"
    if [ "$DB" = "seekdb-embedded" ]; then
      # 需要 PowerContext 附带的 seekdb binding；未满足时启动会报
      # "The embedded seekdb binding is unavailable."（详见 README §6.3）
      echo "POWERCONTEXT_SERVER_DATABASE_KIND=seekdb"
      echo "POWERCONTEXT_SERVER_DATABASE_PATH=${RUNTIME}/seekdb-data"
    else
      echo "POWERCONTEXT_SERVER_DATABASE_KIND=sqlite"
      echo "POWERCONTEXT_SERVER_DATABASE_URL=sqlite+aiosqlite:///${RUNTIME}/memory-theatre.sqlite3"
    fi
  } >"$ENV_FILE"
  echo "wrote $ENV_FILE"
fi

if [ -f "$RUNTIME/powercontext.pid" ] && kill -0 "$(cat "$RUNTIME/powercontext.pid")" 2>/dev/null; then
  echo "PowerContext 已在运行（pid $(cat "$RUNTIME/powercontext.pid")）"
else
  nohup "$BIN" server run --env-file "$ENV_FILE" >"$RUNTIME/powercontext.log" 2>&1 &
  echo $! >"$RUNTIME/powercontext.pid"
  echo "started PowerContext (pid $!), log: $RUNTIME/powercontext.log"
fi

for _ in $(seq 1 60); do
  if curl -sf -m 3 "http://127.0.0.1:${PORT}/health/ready" >/dev/null 2>&1; then
    echo "PowerContext ready: http://127.0.0.1:${PORT}"
    curl -sS -m 5 "http://127.0.0.1:${PORT}/v1/server-info" | head -c 400
    echo
    exit 0
  fi
  sleep 1
done

echo "PowerContext 没有在 60 秒内就绪，请查看 $RUNTIME/powercontext.log" >&2
tail -30 "$RUNTIME/powercontext.log" >&2 || true
exit 1
