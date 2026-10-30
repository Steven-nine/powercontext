#!/usr/bin/env bash
#
# Run the SDD demo end to end. Set DRY_RUN=1 to apply the reference patch
# instead of calling MiniMax Code.

set -euo pipefail
cd "$(dirname "$0")/.."

TASK="${TASK:-add min_total filter to list orders}"
DRY_RUN="${DRY_RUN:-0}"

uv run mmctx ingest --root demo-app
uv run mmctx context --task "$TASK" --root demo-app | tee evidence/logs/context-before.json
cp demo-app/.mmcontext/context.json evidence/logs/context-for-minimax.json
cp demo-app/.mmcontext/prompt.md evidence/logs/prompt-for-minimax.md
uv run mmctx state save --task "$TASK" --status "tests-failing" --phase before

if [ "$DRY_RUN" = "1" ]; then
  uv run mmctx test --root demo-app --label before-dryrun || true
  patch -p1 < evidence/patches/min_total.patch
  uv run mmctx test --root demo-app --label after-dryrun
  uv run mmctx state save --task "$TASK" --status "tests-passing-dryrun" --phase dryrun
else
  uv run mmctx test --root demo-app --label before || true
  mcode --version > evidence/logs/mcode-version.txt
  mcode exec --cwd demo-app --permission full --timeout 10m \
    --file demo-app/.mmcontext/prompt.md \
    --output-format json -o evidence/logs/mcode-final.json \
    "Read .mmcontext/prompt.md and implement the task. Run python -m pytest -q tests before finishing." \
    | tee evidence/logs/mcode-stream.json
  uv run mmctx test --root demo-app --label after
  uv run mmctx state save --task "$TASK" --status "tests-passing" --phase after \
    --done "context built from seekdb, code modified, tests run" \
    --todo "none" \
    --verification "pytest tests passed (evidence/logs/after.log)"
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git diff -- demo-app > evidence/logs/code.diff || true
  fi
fi

uv run mmctx context --task "$TASK" --root demo-app > evidence/logs/context-after.json
echo "Evidence written under evidence/logs."
