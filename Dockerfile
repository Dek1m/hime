# ============================================================
# Dockerfile — Hime (Mass Google Scraper with Proxy Rotation)
# ============================================================
# Многостадийная сборка:
#   Stage 1: установка зависимостей (кэшируется по pyproject.toml)
#   Stage 2: runtime — копируем зависимости + код, устанавливаем hime
# ============================================================

# === Stage 1: Build dependencies ===
FROM python:3.11-slim AS builder

WORKDIR /build

# Копируем спецификацию зависимостей
COPY pyproject.toml .

# Минимальная структура для pip install
RUN touch __init__.py && \
    mkdir -p proxy scraper cache storage cli && \
    touch proxy/__init__.py scraper/__init__.py cache/__init__.py storage/__init__.py cli/__init__.py

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
COPY pyproject.toml ./

# Устанавливаем пакет hime в site-packages (чтобы import работал)
RUN pip install --no-cache-dir --no-deps .

# Том для SQLite (data/ монтируется снаружи через docker-compose)
RUN mkdir -p /app/data && chown -R hime:hime /app

USER hime

ENTRYPOINT ["python", "-m", "hime"]
