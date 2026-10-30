#!/usr/bin/env bash
#
# Verify the six acceptance items that the demo must demonstrate.

set -uo pipefail
cd "$(dirname "$0")/.."

failures=0

check() {
  local label="$1"
  local result="$2"
  if [ "$result" = "0" ]; then
    echo "PASS  $label"
  else
    echo "FAIL  $label"
    failures=$((failures + 1))
  fi
}

if uv run mmctx ingest --root demo-app >/dev/null; then
  check "1. documents ingested into seekdb" 0
else
  check "1. documents ingested into seekdb" 1
fi

hit_count=$(uv run mmctx query --text "min_total" --limit 5 | grep -c '"path"' || true)
[ "$hit_count" -ge 1 ] && check "2. seekdb retrieval returns sources" 0 || check "2. seekdb retrieval returns sources" 1

if uv run mmctx context --task "add min_total filter" --root demo-app >/dev/null; then
  check "3. context package written" 0
else
  check "3. context package written" 1
fi

if uv run mmctx state save --task "add min_total filter" --status "selfcheck" --phase verify >/dev/null \
  && uv run mmctx state load --query "add min_total filter" | grep -q '"status": "selfcheck"'; then
  check "4. PowerContext state saved and loaded" 0
else
  check "4. PowerContext state saved and loaded" 1
fi

if grep -q "failed" evidence/logs/before.log 2>/dev/null; then
  check "5. before-change target tests failed" 0
else
  check "5. before-change target tests failed" 1
fi

if uv run mmctx test --root demo-app --label selfcheck >/dev/null 2>&1; then
  check "6. current tests pass" 0
else
  check "6. current tests pass" 1
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "Self-check passed."
else
  echo "Self-check failed: $failures item(s)."
  exit 1
fi
