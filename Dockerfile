# ============================================================
# Dockerfile — Hime (Mass Google Scraper with Proxy Rotation)
# ============================================================
# Многостадийная сборка:
#   Stage 1: установка зависимостей (кэшируется по pyproject.toml)
#   Stage 2: runtime — минимальный образ, непривилегированный пользователь
#
# Структура проекта: пакет лежит в КОРНЕ (рядом с pyproject.toml).
# Код копируется напрямую, без подпапки hime/.
# ============================================================

# === Stage 1: Build dependencies ===
FROM python:3.11-slim AS builder

WORKDIR /build

# Копируем спецификацию зависимостей (кэш ломается только при изменении pyproject.toml)
COPY pyproject.toml .

# Минимальная структура для pip install.
# setuptools требует хотя бы один __init__.py, чтобы "увидеть" пакет.
# Мы создаём заглушки — реальный код скопируется на stage 2.
RUN touch __init__.py && \
    mkdir -p proxy scraper cache storage cli && \
    touch proxy/__init__.py scraper/__init__.py cache/__init__.py storage/__init__.py cli/__init__.py

# Устанавливаем зависимости в изолированный префикс
RUN pip install --no-cache-dir --prefix=/install .

# === Stage 2: Runtime ===
FROM python:3.11-slim

# Непривилегированный пользователь
RUN groupadd -r hime && useradd -r -g hime -d /app -s /sbin/nologin hime

WORKDIR /app

# Копируем установленные пакеты из builder
COPY --from=builder /install /usr/local

# Копируем исходный код — подпакеты и модули из корня
COPY proxy/ ./proxy/
COPY scraper/ ./scraper/
COPY cache/ ./cache/
COPY storage/ ./storage/
COPY cli/ ./cli/
COPY __init__.py __main__.py app.py config.py ./

# Том для SQLite (data/ монтируется снаружи через docker-compose)
RUN mkdir -p /app/data && chown -R hime:hime /app

USER hime

ENTRYPOINT ["python", "-m", "hime"]
