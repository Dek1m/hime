# Hime — Proxy Management API

Сервис управления HTTP/SOCKS5 прокси для поисковых запросов. Загружает прокси с GitHub, проверяет работоспособность и предоставляет REST API для агентов и серверов.

![Python](https://img.shields.io/badge/python-3.11+-blue)
![Version](https://img.shields.io/badge/version-0.6.0-green)
![License](https://img.shields.io/badge/license-MIT-yellow)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-teal)

## Быстрый старт

```bash
git clone https://github.com/Dek1m/hime.git
cd hime
pip install -e .

# Загрузить прокси
hime source seed
hime load

# Запустить API
hime serve --port=8008
```

## CLI

```bash
# Источники прокси
hime source list                    # все источники
hime source add <url> --type http   # добавить
hime source remove <uuid>           # удалить
hime source enable/disable <uuid>   # включить/выключить
hime source seed                    # засеять из конфига (25 источников)

# Загрузка прокси
hime load                           # загрузка из БД источников
hime load --check                   # + проверка работоспособности

# Управление прокси
hime proxy list                     # все прокси
hime proxy list --status=active     # фильтр по статусу
hime proxy list --type=socks5       # фильтр по типу
hime proxy check                    # проверка всех

# Статистика
hime stats

# API-сервер
hime serve --host=0.0.0.0 --port=8008
```

## REST API

Базовый URL: `http://localhost:8008/api/v1`

### Прокси

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/health` | Health check |
| `GET` | `/proxies` | Список прокси (фильтры: status, type, source, sort) |
| `GET` | `/proxies/{uuid}` | Один прокси |
| `GET` | `/proxies/next` | Следующий рабочий (LRU) |
| `POST` | `/proxies/check` | Запуск проверки (non-blocking) |
| `POST` | `/proxies/load` | Загрузка с GitHub (non-blocking) |
| `GET` | `/check/status` | Прогресс проверки |
| `GET` | `/tasks` | Активные фоновые задачи |
| `GET` | `/stats` | Статистика |

### Источники

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/sources` | Все источники |
| `POST` | `/sources` | Добавить источник |
| `PATCH` | `/sources/{uuid}` | Включить/выключить |
| `DELETE` | `/sources/{uuid}` | Удалить |
| `POST` | `/sources/seed` | Засеять из конфига |

### Сервисы

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/services` | Все сервисы |
| `GET` | `/services/{uuid}` | Один сервис |
| `POST` | `/services` | Создать сервис |
| `PATCH` | `/services/{uuid}` | Обновить сервис |
| `DELETE` | `/services/{uuid}` | Удалить сервис |

### Кеш и Fetch

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/cache/stats` | Статистика кеша (hit/miss) |
| `POST` | `/fetch` | Универсальный HTTP fetch с парсингом и vector cache |

### Параметры фильтрации

| Параметр | Описание |
|----------|----------|
| `status` | `active`, `dead`, `unknown` |
| `type` | `http`, `https`, `socks5` |
| `source` | Подстрока для поиска по источнику |
| `sort` | `latency`, `last_check`, `last_working` |
| `limit` | Лимит (1-1000, по умолчанию 100) |
| `offset` | Смещение для пагинации |

## Конфигурация

| Переменная | Дефолт | Описание |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | URL Redis |
| `SQLITE_PATH` | `db/proxies.db` | Путь к SQLite |
| `LOG_LEVEL` | `INFO` | Уровень логирования |
| `CHECK_INTERVAL` | `60` | Интервал проверки (сек) |
| `HEALTH_CHECK_TIMEOUT` | `5.0` | Таймаут проверки (сек) |
| `MAX_FAILURES` | `3` | Макс. ошибок до dead |
| `MAX_CONCURRENT` | `100` | Макс. одновременных запросов |
| `REQUEST_TIMEOUT` | `15.0` | Таймаут HTTP запроса |
| `CACHE_TTL` | `3600` | Время кеша (сек) |
| `PROXY_REUSE_TIMEOUT` | `120` | LRU timeout (сек) |
| `EMBEDDING_URL` | `http://10.0.0.21:8080/v1` | Embedding API URL |
| `EMBEDDING_MODEL` | `qwen3-embedding-8b` | Модель embedding |
| `EMBEDDING_DIMENSION` | `4096` | Размерность вектора |

## Docker

```yaml
# docker-compose-block.yml (добавить в общий compose)
services:
  hime:
    build:
      context: ./hime
      dockerfile: Dockerfile
    image: hime:latest
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

## Архитектура

```
hime/
├── api/              REST API (FastAPI)
│   ├── app.py        FastAPI + lifespan
│   ├── routes.py     Эндпоинты
│   └── schemas.py    Pydantic-модели
├── cache/            Redis cache + Vector search
│   ├── __init__.py   SearchCache (UUID, cosine similarity)
│   └── embedding.py  EmbeddingClient (Qwen3, 4096-dim)
├── proxy/            Менеджер прокси
│   ├── __init__.py   ProxyData, ProxyType, ProxyStatus
│   ├── manager.py    ProxyManager (LRU, health-check, rate-limit)
│   └── loader.py     Загрузка из БД источников
├── scraper/          HTTP-клиент + парсер
│   ├── fetcher.py    Универсальный fetcher с парсингом
│   └── google_parser.py
├── storage/          SQLite
│   └── __init__.py   ProxyStore (proxies, proxy_sources, services)
├── cli/              CLI (typer + rich)
├── config.py         Конфигурация (pydantic-settings)
├── Dockerfile        Multi-stage build
└── docker-compose-block.yml
```

## Источники прокси (25)

| Источник | Тип |
|---|---|
| gfpcom/free-proxy-list | http, socks5 |
| TheSpeedX/SOCKS-List | http, socks5 |
| ShiftyTR/Proxy-List | http, https |
| monosans/proxy-list | http, socks5 |
| clarketm/proxy-list | http |
| vmheaven/VMHeaven | http, https, socks5 |
| hproxy-com/free-proxy-list | http, https, socks5 |
| ProxyScrape | http, https, socks5 |
| proxifly/free-proxy-list | http, socks5 |
| hookzof/socks5_list | socks5 |
| vakhov/fresh-proxy-list | http, socks5 |
| stormsia/proxy-list | http, socks5 |

**Итого: ~494K прокси** (включая gfpcom — 956K прокси)

## Лицензия

MIT