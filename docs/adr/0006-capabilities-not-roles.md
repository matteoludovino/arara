# ADR 0006: Capabilities, not roles, in the code

**Status:** accepted · **Date:** 2026-10-30

## Context
Four roles (owner, manager, cashier, stockist) and several stores. Checks like `if user.role == "manager"` spread across views drift apart and are hard to review.

## Decision
- Views and services ask for a **capability** (`pos.sell`, `costs.view`, `stock.count_apply`…), optionally at a location; one table maps roles to capabilities. The table is tested cell by cell.
- Every list is scoped to the locations the user works at (owners: all). A request for another store answers 403.
- Cost and margin are fields that only `costs.view` sees: serializers drop them for everyone else, so a cashier's API responses never carry them, not just their screens.

## Consequences
- Changing what a role may do is a one-line change in one file, visible in review.
