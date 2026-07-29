# Hime — Proxy Management API

## Статус
✅ Все задачи выполнены. Готов к деплою.

## Суть
Сервис управления прокси для поисковых запросов. Загружает HTTP/SOCKS5 прокси с GitHub, проверяет работоспособность, предоставляет REST API для агентов и серверов.

## Стек
- **Python 3.11+** + asyncio
- **FastAPI** + uvicorn — REST API
- **httpx[socks]** — HTTP/SOCKS5 прокси
- **selectolax** — парсинг HTML
- **Redis** — кеш на час
- **SQLite** — список прокси
- **pydantic-settings** — конфигурация
- **typer** + **rich** — CLI

## Архитектура

```
hime/
├── api/              # REST API (FastAPI)
│   ├── app.py        # FastAPI приложение
│   ├── routes.py     # Эндпоинты
│   └── schemas.py    # Pydantic модели
├── proxy/            # Менеджер прокси
│   ├── __init__.py   # ProxyData, ProxyType, ProxyStatus
│   ├── manager.py    # ProxyManager (round-robin, health-check)
│   └── loader.py     # Загрузка с GitHub
├── scraper/          # HTTP-клиент + парсер Google
├── cache/            # Redis
├── storage/          # SQLite
├── cli/              # CLI команды
├── Dockerfile        # Multi-stage build
├── docker-compose.yml # Локальная разработка
└── pyproject.toml
```

## Схема БД (proxies)

| Поле | Тип | Описание |
|------|-----|----------|
| uuid | TEXT PK | UUID4 |
| ip | TEXT | IP-адрес |
| port | INTEGER | Порт |
| type | TEXT | http/https/socks5 |
| status | TEXT | active/dead/unknown |
| last_check | REAL | Дата последней проверки |
| last_working | REAL | Дата последней работоспособности |
| added_at | TEXT | Дата добавления |
| last_used | REAL | Время последнего использования |
| source | TEXT | URL GitHub репозитория |
| failure_count | INTEGER | Счётчик ошибок |
| response_time | REAL | Время ответа (ms) |

## REST API

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/proxies` | Список прокси (фильтры: status, type, source) |
| GET | `/proxies/{uuid}` | Один прокси |
| GET | `/proxies/next` | Следующий рабочий прокси |
| POST | `/proxies/check` | Запуск проверки |
| POST | `/proxies/load` | Загрузка с GitHub |
| GET | `/stats` | Статистика |
| GET | `/health` | Health check |

## CLI

```bash
# Загрузка прокси с GitHub
hime load
hime load --check  # + проверка после загрузки

# Управление прокси
hime proxy list
hime proxy list --status=active --type=socks5
hime proxy add --file=proxies.txt
hime proxy check

# Поиск
hime search "python async" --lang=ru --page=1

# API сервер
hime serve --host=0.0.0.0 --port=8000

# Статистика
hime stats
```

## Деплой

### Локальная разработка
```bash
cd /home/opencode/projects/hime
docker compose up --build
curl http://localhost:8000/health
```

### Продакшен (ai.atom.ui)
- Сервер: ai.atom.ui (CentOS, 8 ядер, 7.5G RAM)
- Сеть: `app_default` (Docker)
- Порт: **8008** (внутри контейнера 8000)
- URL: `http://localhost:8008` или `http://hime:8000` (внутри сети)
- БД: SQLite внутри контейнера (нет volume — данные теряются при рестарте)
1. Добавить блок из `docker-compose-block.yml` в общий `docker-compose.yml`
2. `docker compose up -d --build hime`
3. `docker exec hime python -m hime load` — загрузить прокси

## Источники прокси (7 шт.)

1. TheSpeedX/SOCKS-List — http.txt, socks5.txt
2. ShiftyTR/Proxy-List — http.txt, https.txt
3. monosans/proxy-list — http.txt, socks5.txt
4. clarketm/proxy-list — proxy-list-raw.txt

## Таблица proxy_sources

### Схема БД

CREATE TABLE proxy_sources (
    uuid        TEXT PRIMARY KEY,
    url         TEXT NOT NULL UNIQUE,
    type_hint   TEXT DEFAULT 'http',
    enabled     INTEGER DEFAULT 1,
    last_fetch  REAL DEFAULT 0,
    added_at    TEXT DEFAULT (datetime('now'))
);

### CRUD операции

| Описание | Код |
|---|---|
| Добавить источник | store.add_source(url, type_hint) |
| Получить по UUID | store.get_source(uuid) |
| Список всех | store.list_sources() |
| Только активные | store.list_sources(enabled_only=True) |
| Включить | store.enable_source(uuid) |
| Выключить | store.disable_source(uuid) |
| Удалить | store.delete_source(uuid) |

### API эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| GET | /sources | Список всех источников |
| POST | /sources | Добавить источник |
| PATCH | /sources/{uuid} | Включить/выключить |
| DELETE | /sources/{uuid} | Удалить |

### CLI команды

| Команда | Описание |
|---------|----------|
| hime source list | Все источники |
| hime source add <url> | Добавить |
| hime source remove <uuid> | Удалить |
| hime source enable <uuid> | Включить |
| hime source disable <uuid> | Выключить |

### Миграция
- При первом запуске: дефолтные sources из config.py → proxy_sources
- Fallback: если таблица пуста, loader берёт URLs из конфига

## Конфигурация (.env)

```env
REDIS_URL=redis://localhost:6379/0
SQLITE_PATH=db/proxies.db
MAX_CONCURRENT=100
REQUEST_TIMEOUT=15
CHECK_INTERVAL=60
RATE_LIMIT_RPM=12
CACHE_TTL=3600
LOG_LEVEL=INFO
```

## История

### v0.2.0 — REST API + GitHub Loader (2026-07-28)
- ✅ Новая схема БД (uuid, last_working, source, added_at)
- ✅ Загрузка прокси с 7 GitHub репозиториев
- ✅ REST API (FastAPI): 7 эндпоинтов
- ✅ CLI: команда serve, обновление proxy list
- ✅ Docker: Dockerfile + docker-compose.yml
- ✅ Синхронизация ProxyManager с БД

### v0.1.0 — Скелет (2026-07-27)
- ✅ Скелет проекта, конфиг, SQLite, Redis
- ✅ ProxyManager (round-robin, health-check, rate-limiter)
- ✅ Async HTTP-клиент + retry
- ✅ Парсинг Google HTML
- ✅ CLI команды
