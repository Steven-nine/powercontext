#!/usr/bin/env bash
#
# Prepare the mmctx virtual environment and report PowerContext availability.

set -euo pipefail
cd "$(dirname "$0")/.."

uv sync --extra dev

if command -v powercontext >/dev/null 2>&1; then
  echo "PowerContext CLI: $(command -v powercontext)"
else
  echo "PowerContext CLI is not on PATH."
  echo "Start the server from a PowerContext checkout, for example:"
  echo "  uv run powercontext server run --env-file .env"
fi

echo "Next: bash scripts/selfcheck.sh"
