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

## Таблица services (v0.3.0)

### Описание
Таблица `services` хранит настройки запросов к внешним сервисам. Каждый сервис — это конфигурация HTTP-запроса: URL, метод, заголовки, тело, таймаут, кеш, прокси.

### Схема БД (миграция)

CREATE TABLE IF NOT EXISTS services (
    uuid            TEXT PRIMARY KEY,
    name            TEXT    NOT NULL UNIQUE,
    url             TEXT    NOT NULL,
    method          TEXT    NOT NULL DEFAULT 'GET',
    headers         TEXT    DEFAULT '{}',
    body            TEXT    DEFAULT '',
    timeout         REAL    DEFAULT 15.0,
    cache_ttl       INTEGER DEFAULT 0,
    auto_parse      INTEGER DEFAULT 1,
    rate_limit_rpm  INTEGER DEFAULT 60,
    callback_url    TEXT    DEFAULT '',
    proxy           INTEGER DEFAULT 0,
    enabled         INTEGER DEFAULT 1,
    created_at      TEXT    DEFAULT (datetime('now')),
    modified_at     TEXT    DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_services_name ON services(name);
CREATE INDEX IF NOT EXISTS idx_services_enabled ON services(enabled);

### Параметры

| Параметр | Тип | Описание | Дефолт |
|---|---|---|---|
| uuid | TEXT PK | Уникальный идентификатор | UUID4 |
| name | TEXT UNIQUE | Имя сервиса | — |
| url | TEXT | Базовый URL | — |
| method | TEXT | HTTP метод (GET/POST/PUT/DELETE) | GET |
| headers | TEXT (JSON) | Заголовки по умолчанию | {} |
| body | TEXT | Тело для POST | "" |
| timeout | REAL | Таймаут (сек) | 15.0 |
| cache_ttl | INT | Время кеша (сек), 0 = без кеша | 0 |
| auto_parse | INT | Автопарсинг ответа (bool) | 1 |
| rate_limit_rpm | INT | Лимит запросов/мин | 60 |
| callback_url | TEXT | URL для callback'а | "" |
| proxy | INT | Использовать прокси (bool) | 0 |
| enabled | INT | Сервис включён (bool) | 1 |
| created_at | TEXT | Дата создания | datetime('now') |
| modified_at | TEXT | Дата последнего изменения | datetime('now') |

### CRUD операции

| Описание | Код |
|---|---|
| Создать сервис | store.create_service(name, url, **kwargs) |
| Получить по UUID | store.get_service(uuid) |
| Получить по имени | store.get_service_by_name(name) |
| Список всех | store.list_services() |
| Только включённые | store.list_services(enabled_only=True) |
| Обновить | store.update_service(uuid, **fields) |
| Удалить | store.delete_service(uuid) |

### API эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| GET | /services | Список всех сервисов |
| GET | /services/{uuid} | Один сервис |
| POST | /services | Создать сервис |
| PATCH | /services/{uuid} | Обновить сервис |
| DELETE | /services/{uuid} | Удалить сервис |

### JSON формат запроса

POST /services:
{
  "name": "github_api",
  "url": "https://api.github.com",
  "method": "GET",
  "headers": {"Accept": "application/json"},
  "timeout": 10.0,
  "cache_ttl": 300,
  "proxy": false
}

### Декомпозиция задач

| # | Задача | Файл | Сложность | Время |
|---|--------|------|-----------|-------|
| 1 | Миграция: таблица services | storage/__init__.py | Низкая | 0.5ч |
| 2 | Модель ServiceData | storage/__init__.py | Низкая | 0.5ч |
| 3 | CRUD методы | storage/__init__.py | Средняя | 1ч |
| 4 | Pydantic схемы | api/schemas.py | Низкая | 0.5ч |
| 5 | API эндпоинты | api/routes.py | Средняя | 1.5ч |
| 6 | ServiceStore в app.state | api/app.py | Низкая | 0.5ч |
| 7 | CLI команды | cli/commands.py | Низкая | 1ч |
| 8 | Тесты | tests/ | Средняя | 1ч |
| 9 | Коммит, push, deploy | — | — | 0.5ч |

### Порядок выполнения

1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9

### Зависимости

- Задача 1 (миграция) — обязательна первой
- Задача 2 (модель) — от задачи 1
- Задача 3 (CRUD) — от задачи 2
- Задача 4 (схемы) — от задачи 2
- Задача 5 (API) — от задач 3, 4
- Задача 6 (app.state) — от задачи 3
- Задача 7 (CLI) — от задачи 3
- Задача 8 (тесты) — от задач 5, 7
- Задача 9 (deploy) — от всех

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

### v0.3.0 — Services Table (2026-07-29)
- ✅ Таблица services (uuid, name, url, method, headers, body, timeout, cache_ttl, auto_parse, rate_limit_rpm, callback_url, proxy, enabled)
- ✅ CRUD: create, get, list, update, delete
- ✅ API: GET/POST/PATCH/DELETE /services
- ✅ CLI: hime service list/add/remove
- ✅ Миграция из существующей БД

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
