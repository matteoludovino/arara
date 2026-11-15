# API image. Build from this directory: docker build -t arara-api .
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first: a code-only change reuses this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY . .
# The admin's static files, hashed and compressed for WhiteNoise.
RUN .venv/bin/python manage.py collectstatic --noinput

FROM python:3.14-slim
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 ENVIRONMENT=production
WORKDIR /app
COPY --from=build /app /app
RUN useradd --system --create-home arara
USER arara
EXPOSE 8000
# Migrations first: a deploy whose migration fails never serves traffic. Two workers fit the
# free plan's 512 MB; threads cover the time spent waiting on the database.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi --bind 0.0.0.0:${PORT:-8000} --workers 2 --threads 4 --timeout 60 --access-logfile -"]
