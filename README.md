# Hime — Proxy Management API

Сервис управления HTTP/SOCKS5 прокси для поисковых запросов. Загружает прокси с GitHub, проверяет работоспособность и предоставляет REST API для агентов и серверов.

![Python](https://img.shields.io/badge/python-3.11+-blue)
![Version](https://img.shields.io/badge/version-0.1.0-green)
![License](https://img.shields.io/badge/license-MIT-yellow)

## Быстрый старт

### Установка

```bash
git clone https://github.com/your-org/hime.git
cd hime
pip install -e .
```

### Зависимости

- Python 3.11+
- Redis (кеш результатов поиска)

### Запуск

```bash
# Загрузить прокси с GitHub
hime load

# Запустить API-сервер
hime serve --host=0.0.0.0 --port=8000

# Проверить работоспособность
curl http://localhost:8000/health
```

## CLI команды

```bash
# Загрузка прокси
hime load                  # загрузка с GitHub
hime load --check          # загрузка + проверка работоспособности

# Управление прокси
hime proxy list                                    # все прокси
hime proxy list --status=active --type=socks5      # с фильтрами
hime proxy check                                   # проверка всех
hime proxy add --file=proxies.txt                  # загрузка из файла

# Поиск (Google через прокси)
hime search "query" --lang=ru --page=1

# API-сервер
hime serve --host=0.0.0.0 --port=8000

# Статистика
hime stats
```

## REST API

Базовый URL: `http://localhost:8000`

### Эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/health` | Health check |
| `GET` | `/proxies` | Список прокси с фильтрами |
| `GET` | `/proxies/{uuid}` | Один прокси по UUID |
| `GET` | `/proxies/next` | Следующий рабочий прокси (round-robin) |
| `POST` | `/proxies/check` | Запуск проверки (background) |
| `POST` | `/proxies/load` | Загрузка прокси с GitHub (background) |
| `GET` | `/stats` | Статистика по прокси |

### Параметры фильтрации (`GET /proxies`)

| Параметр | Тип | Описание |
|----------|-----|----------|
| `status` | string | `active`, `dead`, `unknown` |
| `type` | string | `http`, `https`, `socks5` |
| `source` | string | Подстрока для поиска по источнику |
| `limit` | int | Лимит (1-1000, по умолчанию 100) |
| `offset` | int | Смещение для пагинации |

### Примеры

```bash
# Health check
curl http://localhost:8000/health

# Список активных SOCKS5 прокси
curl "http://localhost:8000/proxies?status=active&type=socks5&limit=10"

# Следующий рабочий прокси
curl http://localhost:8000/proxies/next

# Запуск проверки
curl -X POST http://localhost:8000/proxies/check

# Статистика
curl http://localhost:8000/stats
```

## Конфигурация

Настройка через переменные окружения или файл `.env`:

```env
# Redis
REDIS_URL=redis://localhost:6379/0

# SQLite
SQLITE_PATH=db/proxies.db

# Scraper
MAX_CONCURRENT=100
REQUEST_TIMEOUT=15
SEARCH_DOMAIN=google.com
LANGUAGE=ru
USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0

# Proxy
CHECK_INTERVAL=60
RATE_LIMIT_RPM=12
HEALTH_CHECK_TIMEOUT=5
MAX_FAILURES=3

# Cache
CACHE_TTL=3600
CACHE_PREFIX=hime

# Logging
LOG_LEVEL=INFO
```

## Docker

### Сборка и запуск

```bash
# Сборка образа
docker build -t hime .

# CLI (по умолчанию)
docker run hime load

# API-сервер
docker run -p 8000:8000 hime api
```

### Docker Compose

```yaml
services:
  hime:
    build: ./hime
    command: ["api"]
    ports:
      - "8008:8000"
    volumes:
      - ./hime/data:/app/data
    environment:
      REDIS_URL: redis://redis:6379/0
      SQLITE_PATH: db/proxies.db
    depends_on:
      redis:
        condition: service_healthy
```

```bash
docker compose up -d --build
docker exec hime python -m hime load   # загрузить прокси
```

## Архитектура

```
hime/
├── api/              REST API (FastAPI)
│   ├── app.py        Создание FastAPI-приложения
│   ├── routes.py     Эндпоинты
│   └── schemas.py    Pydantic-модели ответов
├── proxy/            Менеджер прокси
│   ├── __init__.py   ProxyData, ProxyType, ProxyStatus
│   ├── manager.py    ProxyManager (round-robin, health-check)
│   └── loader.py     Загрузка с GitHub
├── scraper/          HTTP-клиент + парсер Google
├── cache/            Redis-кеш
├── storage/          SQLite-хранилище
├── cli/              CLI команды (typer + rich)
├── config.py         Конфигурация (pydantic-settings)
├── app.py            Оркестратор приложения
├── Dockerfile        Multi-stage build
└── pyproject.toml
```

### Поток данных

```
Клиент → API/CLI → ProxyManager → HttpClient → Google
                ↓                ↓
           ProxyStore        SearchCache
           (SQLite)          (Redis)
```

1. **Загрузка**: `hime load` → GitHub raw URL → парсинг → SQLite
2. **Проверка**: Health-check через прокси → обновление статуса в БД
3. **Запрос**: Клиент → round-robin выбор прокси → HTTP-запрос → кеш в Redis
4. **API**: REST-эндпоинты читают из SQLite, управляют ProxyManager

## Источники прокси

Проект загружает прокси из 7 GitHub-репозиториев:

- TheSpeedX/SOCKS-List (http, socks5)
- ShiftyTR/Proxy-List (http, https)
- monosans/proxy-list (http, socks5)
- clarketm/proxy-list (raw)

## Лицензия

MIT
