# ADR 0005: Point of sale: numbering, retries, returns and the till

**Status:** accepted · **Date:** 2026-11-07

## Context
A till runs on shop Wi-Fi. A request can time out after the server committed it; the cashier presses again. Sale numbers are what customers and accountants see. Cash differences are where small losses hide.

## Decision
- **Idempotent sales:** the till generates a `client_request_id` per sale and keeps it across retries; the same id returns the sale already made (200 instead of 201).
- **Gapless numbering** per store from a locked `DocumentSequence`, taken at the end of the sale's transaction: a refused sale burns no number.
- The sale discount is spread over the lines (largest remainder, to the cent); above `POS_CASHIER_MAX_DISCOUNT_PERCENT` a manager approves **on the cashier's screen** with their own password. The approval is single-use, expires in minutes and is bound to requester, action and store; it never stores the credential.
- Cancelling undoes a whole sale, only within its till session. After that it is a **return**: partial, at any store, refunded at what was actually paid per unit, in cash from an open till or as a **store credit** (a ledger of its own, locked when spent). An exchange is a return to credit followed by a sale paid with it.
- **Blind closing:** the cashier enters the counted cash before seeing the expected amount; the difference is recorded and audited.

## Consequences
- The web till keeps one request id until a sale succeeds and its cart survives a page reload.
- Fiscal documents (NFC-e) are out of scope; the sale keeps what they need (items, prices, payments with installments and NSU) for a later 1:1 fiscal record.
