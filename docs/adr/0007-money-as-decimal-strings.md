# ADR 0007: Money as decimal strings, cents in the browser

**Status:** accepted · **Date:** 2026-11-10

## Context
`0.1 + 0.2 != 0.3` in JavaScript. A till that adds prices in floating point eventually disagrees with the server by a cent, and the server rejects the payment.

## Decision
- The API sends and receives money as decimal strings (`"79.90"`), never JSON numbers. The server computes with `Decimal` and explicit `ROUND_HALF_UP`; costs carry four decimals.
- The browser converts to **integer cents** to add up a cart or a split payment, and back to a decimal string to send. It only previews: the server's totals are the ones that count.

## Consequences
- The till can split a bill across methods and show change exactly; a payment that doesn't add up to the cent is caught on screen before the server refuses it.
