# ADR 0001: Stock is an append-only ledger

**Status:** accepted · **Date:** 2026-11-01

## Context
A store's stock is touched by purchases, sales, returns, transfers, counts and corrections, from several tills at once. A balance column that each feature updates in place can't answer "why is this number what it is?", and an edit can't be undone without losing the edit itself.

## Decision
- Every change is a `StockEntry` (what happened, who, why, approved by whom) with `StockMovement` lines: SKU, location, quantity delta, value delta, unit cost and the balance after it.
- Both tables are **append-only, enforced by PostgreSQL**: a trigger rejects UPDATE and DELETE whatever the path (ORM, admin, raw SQL). A mistake is corrected by another entry: a reversal, an adjustment, a count.
- `StockLevel` (SKU × location) and `SkuCost` (SKU) are projections updated in the same transaction. `CHECK (quantity >= 0)` is the last line of defence; the services refuse first, reporting every shortage at once.
- Every write goes through one function, `stock.services.post_entry`. Integrity checks (`manage.py check_stock`, and after every stock test) prove that each projection equals the sum of its ledger.
- Goods in transit and written-off goods are locations too (`TRANSITO`, `PERDAS`): nothing leaves the books silently.

## Consequences
- Stock and its value at any past moment are a `SUM` over the ledger: the valuation report needs no snapshots.
- History can't be backdated, which the demo seed has to respect (see ADR 0008).
- The ledger grows with every sale; a future archive would roll old movements into an opening balance entry.
