#!/usr/bin/env bash
#
# Restore the demo code and remove local runtime data.

set -euo pipefail
cd "$(dirname "$0")/.."

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git checkout -- demo-app/src/orders.py
fi
rm -rf .data demo-app/.mmcontext demo-app/.pytest_cache
echo "Demo reset."
