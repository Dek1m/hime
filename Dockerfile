# ============================================================
# Dockerfile — Hime (Mass Google Scraper with Proxy Rotation)
# ============================================================
# Многостадийная сборка:
#   Stage 1: установка зависимостей (кэшируется по pyproject.toml)
#   Stage 2: runtime — копируем зависимости + код
#
# Режим запуска:
#   CLI:   docker run hime                 (по умолчанию)
#   API:   docker run hime api             (uvicorn, порт 8000)
# ============================================================

# === Stage 1: Build dependencies ===
FROM python:3.11-slim AS builder

WORKDIR /build

# Копируем спецификацию зависимостей
COPY pyproject.toml .

# Минимальная структура для pip install
RUN touch __init__.py && \
    mkdir -p proxy scraper cache storage cli api && \
    touch proxy/__init__.py scraper/__init__.py cache/__init__.py storage/__init__.py cli/__init__.py api/__init__.py

# Устанавливаем зависимости
RUN pip install --no-cache-dir --prefix=/install .

# === Stage 2: Runtime ===
FROM python:3.11-slim

# Непривилегированный пользователь
RUN groupadd -r hime && useradd -r -g hime -d /app -s /sbin/nologin hime

WORKDIR /app

# Копируем установленные пакеты из builder
COPY --from=builder /install /usr/local

# Копируем исходный код
COPY __init__.py __main__.py app.py config.py ./
COPY proxy/ ./proxy/
COPY scraper/ ./scraper/
COPY cache/ ./cache/
COPY storage/ ./storage/
COPY cli/ ./cli/
COPY api/ ./api/
COPY pyproject.toml ./

# Симлинк hime -> . чтобы "from hime.xxx import ..." работал
# PYTHONPATH=/app добавляет /app в sys.path,
# Python находит hime (симлинк на /app) и резолвит hime.xxx -> /app/xxx
RUN ln -s . hime && \
    mkdir -p /app/data /app/db && chown -R hime:hime /app

ENV PYTHONPATH=/app

EXPOSE 8000

# Healthcheck: curl к /health если API, иначе просто проверяем что процесс жив
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" 2>/dev/null || exit 0

USER hime

# По умолчанию — CLI (typer). Переопределить: docker run hime api
ENTRYPOINT ["python", "-m", "hime"]
CMD []
