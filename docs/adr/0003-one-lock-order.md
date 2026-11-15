# ADR 0003: One global lock order

**Status:** accepted · **Date:** 2026-11-01

## Context
Two tills selling the last piece, a receipt landing while a sale runs, a count applied while the store sells: correctness depends on row locks, and locks taken in different orders deadlock.

## Decision
- Every service locks in the same order: `CashSession → Approval → Sale → DocumentSequence → SkuCost → StockLevel → StoreCredit`, each set sorted by key, with `SELECT … FOR UPDATE OF self`.
- `FOR UPDATE` can't lock a row that doesn't exist yet, so missing balance rows are created first (`bulk_create(ignore_conflicts=True)`) and then locked.
- Checks that depend on state (stock available, store credit balance, what's left to return) run **after** the lock.
- Race tests run two threads behind a `Barrier`, with `lock_timeout` so a deadlock fails the test instead of hanging CI. Mutation tests (removing a lock) confirm each race test fails without it.

## Consequences
- No sale can oversell, no receipt can double the average, no credit can be spent twice, and sale numbers have no gaps or repeats.
- A new service that touches stock must follow the order; `post_entry` takes the stock part of it, so most of them can't get it wrong.
