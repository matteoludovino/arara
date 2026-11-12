# Arara

Inventory, purchasing and point of sale for small clothing and shoe stores: products in a
size × color grid, several stores and warehouses, transfers, physical counts, a cash register
and reports.

> Work in progress.

## Stack
Django 6.1 · Django REST Framework · PostgreSQL 16 · React 19 · TanStack Query · Tailwind 4 · Vite · uv

## Local development
```bash
docker compose up -d                     # PostgreSQL on :5436
cd backend
cp .env.example .env
uv sync
uv run python manage.py migrate
uv run python manage.py seed_demo        # a demo shop with weeks of history (password: arara-demo-2026)
uv run python manage.py runserver 8010   # API on http://localhost:8010/api, docs on /api/docs/

cd ../frontend
npm install
npm run dev                              # http://localhost:5174 (proxies /api to :8010)
```

Demo accounts (all `@arara.test`): `marta` owner, `rafael` and `lia` managers, `bia`, `davi`
and `caio` cashiers, `joao` stockist.

## Checks
```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy .
uv run pytest                            # against the PostgreSQL above

cd ../frontend
npm run lint && npm run typecheck && npm test && npm run build
```
