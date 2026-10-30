# Development task

add min_total filter to list orders

# Applicable specification

## specs/orders.md

# Orders Service Specification

## R1 Status filter

`list_orders(status=None)` returns every order when `status` is `None`, and
only orders whose status equals the argument otherwise.

## R2 Stable order

Results keep the insertion order of the source list.

## R3 Unknown status

An unknown status returns an empty list.

## R4 Minimum total filter

`list_orders(status=None, min_total=None)` also filters by `total >= min_total`
when `min_total` is not `None`. Status and minimum total combine with logical
AND. `total_revenue` keeps its current signature and behavior.

# Files to inspect

- `src/orders.py`: def list_orders(status=None)

# Tests that define done

- `tests/test_orders.py`: def test_all_orders()

# Progress

Done: context package built from seekdb sources
Todo: apply the code change; run target and regression tests
Verification: none

# Previous task state

{
  "task": "add min_total filter to list orders",
  "status": "context-built",
  "sources": [
    "specs/orders.md",
    "src/orders.py",
    "tests/test_orders.py"
  ],
  "context_file": "/home/leonado/projects/pc-mm/minimax/demo-app/.mmcontext/context.json",
  "updated_at": "2026-10-30T05:32:42.871934+00:00",
  "done": [
    "context package built from seekdb sources"
  ],
  "todo": [
    "apply the code change",
    "run target and regression tests"
  ],
  "verification": []
}

# Constraints

- Modify only files under `src/`.
- Keep the existing public API and all existing tests passing.
- Run `python -m pytest -q tests` before finishing.
