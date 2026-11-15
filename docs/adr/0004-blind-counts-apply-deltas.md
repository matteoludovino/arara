# ADR 0004: Blind counts that apply deltas

**Status:** accepted · **Date:** 2026-11-04

## Context
A physical count takes hours and the store keeps selling. "Set the balance to what was counted" erases the sales made between the count of a shelf and the end of the count; showing the counter the expected number biases the count towards it.

## Decision
- The count is **blind**: the person counting enters code, quantity and area, and never sees the system quantity.
- When a SKU is first counted, the system quantity is read **under lock** and stored with the entry. Applying adds `counted − system_at_entry` to the current balance: a delta, never an overwrite, so sales made during the count are kept.
- A SKU that moved while being counted, or whose difference exceeds the tolerance, is flagged for recount. SKUs in scope that nobody counted are resolved explicitly by the manager: keep the balance, or zero it.
- Only one active count per location; review and apply belong to the manager.

## Consequences
- The store doesn't close for inventory. Differences become count-adjustment entries in the ledger, with who applied them.
