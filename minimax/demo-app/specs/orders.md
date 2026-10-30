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
