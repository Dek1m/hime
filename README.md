# Hime — Proxy Management API

Сервис управления HTTP/SOCKS5 прокси для поисковых запросов. Загружает прокси с GitHub, проверяет работоспособность и предоставляет REST API для агентов и серверов.

![Python](https://img.shields.io/badge/python-3.11+-blue)
![Version](https://img.shields.io/badge/version-0.2.0-green)
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
hime source seed                    # засеять из конфига

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

Базовый URL: `http://localhost:8008`

### Прокси

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/health` | Health check |
| `GET` | `/proxies` | Список прокси (фильтры: status, type, source, sort) |
| `GET` | `/proxies/{uuid}` | Один прокси |
| `GET` | `/proxies/next` | Следующий рабочий (round-robin) |
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
│   ├── schemas.py    Pydantic-модели
│   └── state.py      AppState singleton
├── proxy/            Менеджер прокси
│   ├── __init__.py   ProxyData, ProxyType, ProxyStatus
│   ├── manager.py    ProxyManager + CheckProgress
│   └── loader.py     Загрузка из БД источников
├── storage/          SQLite
│   └── __init__.py   ProxyStore (proxies + proxy_sources)
├── cli/              CLI (typer + rich)
├── config.py         Конфигурация (pydantic-settings)
├── Dockerfile        Multi-stage build
└── docker-compose-block.yml
```

## Источники прокси (21)

| Источник | HTTP | SOCKS5 |
|---|---|---|
| vmheaven/VMHeaven | 5,298 | 369 |
| TheSpeedX/SOCKS-List | 2,863 | 703 |
| hproxy-com/free-proxy-list | 2,399 | 136 |
| vmheaven/https | 1,345 | — |
| ProxyScrape | 299 | 327 |
| hookzof/socks5_list | — | 418 |
| vakhov/fresh-proxy-list | 485 | — |
| monosans/proxy-list | 60 | 63 |
| stormsia/proxy-list | 28 | 11 |
| Остальные | — | — |

**Итого: ~15,000 прокси**

## Лицензия

MIT
