# ADR 0008: A public demo with lived-in history

**Status:** accepted · **Date:** 2026-11-15

## Context
The demo is shared by every visitor and must look like a shop that has been trading: weeks of sales, returns, transfers, a count, stock running low, winter pieces that stopped selling. It runs on free plans: Render (a tenth of a CPU, 512 MB) and Neon.

## Decision
- `manage.py seed_demo` writes the history **through the real services**, so the demo can only contain what the rules allow. The ledger is append-only (ADR 0001), so instead of backdating rows the seed lives through the weeks on a **simulated clock** (`timezone.now` patched to a clock that only moves forward). Both stores' days are interleaved by time, because the average cost is company-wide and the ledger must take events in the order they happened; a test checks the demo ledger is chronological. Randomness has a fixed seed.
- The reset (`--reset`, refused unless `DEMO_MODE` or `DEBUG`) runs nightly from **GitHub Actions against the database**, not inside the API: it takes a minute or two on a full CPU and would take more than ten on the API instance.
- The sign-in page offers the demo accounts; the shared accounts and locations can't be deactivated, demoted or have their passwords changed, so one visitor can't lock the others out.
- In `DEMO_MODE` passwords are hashed with 100k PBKDF2 iterations instead of 1.5M: at 0.1 CPU the default made each sign-in and each manager approval take about six seconds. The demo's passwords are published and its data is fictional, so the cost protected nothing there; a real deployment keeps the default.

## Consequences
- Anything a visitor does lasts until 03:00 São Paulo time; the reset also signs everyone out.
- The API sleeps after 15 idle minutes on the free plan: the first request of a visit takes about a minute.
