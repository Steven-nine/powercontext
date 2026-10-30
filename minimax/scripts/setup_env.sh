#!/usr/bin/env bash
# 准备 SDD 上下文管理模块的运行环境（Linux / WSL2 / macOS）。
#
#   ./scripts/setup_env.sh
#
# 做四件事：
#   1) 建立隔离的虚拟环境并安装 requirements.txt；
#   2) 检查 seekdb（MySQL 协议，127.0.0.1:2881）是否可达；
#   3) 打印缓存 / 状态目录（默认落在 D 盘缓存目录，Linux 下回退到 ~/.cache）；
#   4) 检查 MiniMax 凭据是否已配置。
set -euo pipefail

VENV_DIR="${VENV_DIR:-.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIP_INDEX_URL="${PIP_INDEX_URL:-}"
CACHE_DIR="${SDDCTX_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/minimax-sdd}"

cd "$PROJECT_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "python3 not found; install Python 3.11+ first (apt install python3 python3-venv)" >&2
  exit 1
fi

if [ ! -x "$VENV_DIR/bin/pip" ]; then
  if ! "$PYTHON_BIN" -m venv "$VENV_DIR" 2>/tmp/sddctx-venv.err; then
    echo "venv creation failed; on Debian/Ubuntu run: apt-get install -y python3-venv" >&2
    cat /tmp/sddctx-venv.err >&2
    exit 1
  fi
fi

PIP_ARGS=()
if [ -n "$PIP_INDEX_URL" ]; then
  PIP_ARGS+=(--index-url "$PIP_INDEX_URL")
fi

"$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel >/dev/null
"$VENV_DIR/bin/pip" install "${PIP_ARGS[@]}" -r requirements.txt

echo
echo "== 依赖版本 =="
"$VENV_DIR/bin/python" - <<'PY'
import powercontext, pymysql, pytest, requests
print("powercontext", getattr(powercontext, "__version__", "unknown"))
print("pymysql", pymysql.__version__)
print("pytest", pytest.__version__)
print("requests", requests.__version__)
PY

echo
echo "== seekdb 连通性 =="
if "$VENV_DIR/bin/python" - <<'PY'
import os, sys
import pymysql
host = os.environ.get("SDDCTX_DB_HOST", "127.0.0.1")
port = int(os.environ.get("SDDCTX_DB_PORT", "2881"))
user = os.environ.get("SDDCTX_DB_USER", "root")
password = os.environ.get("SDDCTX_DB_PASSWORD", "")
try:
    conn = pymysql.connect(host=host, port=port, user=user, password=password, connect_timeout=5)
    with conn, conn.cursor() as cur:
        cur.execute("SELECT VERSION(), @@port")
        version, running_port = cur.fetchone()
    print(f"OK  {host}:{running_port}  {version}")
except Exception as exc:  # noqa: BLE001
    print(f"FAIL {host}:{port} 不可连接：{exc}")
    sys.exit(1)
PY
then
  echo "   （模块启动时会自动建库 sdd_ctx 与表结构）"
else
  echo "   seekdb 未就绪：先启动 seekdb 服务，或设置 SDDCTX_DB_HOST / SDDCTX_DB_PORT。" >&2
fi

echo
echo "== 缓存与状态目录 =="
echo "   SDDCTX_CACHE_DIR=${CACHE_DIR}"
echo "   SDDCTX_STATE_DB=${SDDCTX_STATE_DB:-${CACHE_DIR}/state/powercontext.db}"

echo
echo "== MiniMax 凭据 =="
if [ -n "${MINIMAX_API_KEY:-}" ]; then
  echo "   MINIMAX_API_KEY 已设置"
else
  echo "   未设置 MINIMAX_API_KEY；代码修改步骤会被跳过（其余步骤仍可运行）。" >&2
  echo "   Key 申请：https://platform.minimax.cn/user-center/basic-information/interface-key" >&2
fi

echo
echo "environment ready: $VENV_DIR"
echo "下一步：export MINIMAX_API_KEY=<key> && .venv/bin/python scripts/run_verification.py"
