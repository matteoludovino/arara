# Arara

Inventory, purchasing and point of sale for small clothing and shoe stores: products in a
size × color grid, several stores and warehouses, transfers, physical counts, a cash register
and reports.

> Work in progress.

## Stack
Django 6.1 · Django REST Framework · PostgreSQL 16 · React (coming) · uv

## Local development
```bash
docker compose up -d                     # PostgreSQL on :5436
cd backend
cp .env.example .env
uv sync
uv run python manage.py migrate
uv run python manage.py runserver 8010   # API on http://localhost:8010/api, docs on /api/docs/
```

## Checks
```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy .
uv run pytest                            # against the PostgreSQL above
```
