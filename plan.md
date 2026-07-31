# Hime — Proxy Management API

## Статус
✅ v0.6.0 — Работает на ai.atom.ui:8008

## Суть
Сервис управления прокси для поисковых запросов. Загружает HTTP/SOCKS5 прокси с GitHub, проверяет работоспособность, предоставляет REST API для агентов и серверов.

## Стек
- **Python 3.11+** + asyncio
- **FastAPI** + uvicorn — REST API
- **httpx[socks]** — HTTP/SOCKS5 прокси
- **selectolax** — парсинг HTML
- **Redis** — кеш + vector search
- **SQLite** — список прокси (proxies, proxy_sources, services)
- **pydantic-settings** — конфигурация
- **typer** + **rich** — CLI
- **Logging** — INFO/DEBUG/WARNING/ERROR

## Архитектура

```
hime/
├── api/              # REST API (FastAPI)
│   ├── app.py        # FastAPI приложение
│   ├── routes.py     # Эндпоинты
│   └── schemas.py    # Pydantic модели
├── cache/            # Redis cache + Vector search
│   ├── __init__.py   # SearchCache (UUID, cosine similarity)
│   └── embedding.py  # EmbeddingClient (Qwen3, 4096-dim)
├── proxy/            # Менеджер прокси
│   ├── __init__.py   # ProxyData, ProxyType, ProxyStatus
│   ├── manager.py    # ProxyManager (LRU, health-check, rate-limit)
│   └── loader.py     # Загрузка с GitHub
├── scraper/          # HTTP-клиент + парсер
├── storage/          # SQLite
├── cli/              # CLI команды
├── Dockerfile        # Multi-stage build
├── docker-compose.yml # Локальная разработка
└── pyproject.toml
```

## Схема БД

### Таблица proxies

| Поле | Тип | Описание |
|------|-----|----------|
| uuid | TEXT PK | UUID4 |
| ip | TEXT | IP-адрес |
| port | INTEGER | Порт |
| type | TEXT | http/https/socks5 |
| status | TEXT | active/dead/unknown |
| last_check | REAL | Дата последней проверки |
| last_working | REAL | Дата последней работоспособности |
| latency_ms | REAL | Время ответа (ms) |
| failure_count | INTEGER | Счётчик ошибок |
| last_used | REAL | Время последнего использования |
| added_at | TEXT | Дата добавления |
| source | TEXT | URL GitHub репозитория |

### Таблица proxy_sources

| Поле | Тип | Описание |
|------|-----|----------|
| uuid | TEXT PK | UUID4 |
| url | TEXT UNIQUE | URL источника |
| type_hint | TEXT | Тип прокси по умолчанию |
| enabled | INTEGER | Включён (0/1) |
| last_fetch | REAL | Дата последней загрузки |
| added_at | TEXT | Дата добавления |

### Таблица services

| Поле | Тип | Описание |
|------|-----|----------|
| uuid | TEXT PK | UUID4 |
| name | TEXT UNIQUE | Имя сервиса |
| url | TEXT | Базовый URL |
| method | TEXT | HTTP метод |
| headers | TEXT (JSON) | Заголовки |
| body | TEXT | Тело для POST |
| timeout | REAL | Таймаут (сек) |
| cache_ttl | INTEGER | Время кеша (сек) |
| auto_parse | INTEGER | Автопарсинг (0/1) |
| rate_limit_rpm | INTEGER | Лимит запросов/мин |
| callback_url | TEXT | URL для callback |
| proxy | INTEGER | Использовать прокси (0/1) |
| enabled | INTEGER | Включён (0/1) |
| created_at | TEXT | Дата создания |
| modified_at | TEXT | Дата изменения |

## REST API

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/v1/proxies` | Список прокси (фильтры: status, type, source, sort) |
| GET | `/api/v1/proxies/{uuid}` | Один прокси |
| GET | `/api/v1/proxies/next` | Следующий рабочий прокси (LRU) |
| POST | `/api/v1/proxies/check` | Запуск проверки |
| POST | `/api/v1/proxies/load` | Загрузка с GitHub |
| GET | `/api/v1/stats` | Статистика |
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/cache/stats` | Статистика кеша (hit/miss) |
| POST | `/api/v1/fetch` | Универсальный fetch с vector cache |
| GET | `/api/v1/sources` | Все источники |
| POST | `/api/v1/sources` | Добавить источник |
| PATCH | `/api/v1/sources/{uuid}` | Включить/выключить |
| DELETE | `/api/v1/sources/{uuid}` | Удалить |
| POST | `/api/v1/sources/seed` | Засеять из конфига |
| GET | `/api/v1/services` | Все сервисы |
| POST | `/api/v1/services` | Создать сервис |
| PATCH | `/api/v1/services/{uuid}` | Обновить сервис |
| DELETE | `/api/v1/services/{uuid}` | Удалить сервис |

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

# Управление источниками
hime source list
hime source add <url> --type http
hime source remove <uuid>
hime source enable <uuid>
hime source disable <uuid>
hime source seed

# Управление сервисами
hime service list
hime service add --name=github --url=https://api.github.com
hime service remove <uuid>
hime service get <uuid>

# Статистика
hime stats

# API сервер
hime serve --host=0.0.0.0 --port=8008
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
PROXY_REUSE_TIMEOUT=120
EMBEDDING_URL=http://10.0.0.21:8080/v1
EMBEDDING_MODEL=qwen3-embedding-8b
EMBEDDING_DIMENSION=4096
```

## Тесты

```bash
pytest tests/
```

- `test_cache.py` — тесты Redis cache + vector search
- `test_fetcher.py` — тесты HTTP fetcher + HTML парсинга
- `test_api.py` — тесты REST API эндпоинтов

## История

### v0.6.0 — Vector Cache + Semantic Search (2026-07-29)
- ✅ Sources хранятся ТОЛЬКО в БД (proxy_sources table)
- ✅ LRU proxy selection (reuse_timeout=120s)
- ✅ Vector cache с embedding (Qwen3, 4096-dim)
- ✅ Semantic search (cosine >= 0.95)
- ✅ 8 критических багов исправлено
- ✅ Cache hit/miss metrics
- ✅ Tests: test_cache.py, test_fetcher.py, test_api.py
- ✅ 25 sources, 494K+ прокси
- ✅ gfpcom (956K прокси) добавлен

### v0.5.0 — Universal Fetcher (2026-07-29)
- ✅ Универсальный HTTP fetcher с парсингом
- ✅ POST/GET запросы с прокси
- ✅ HTML парсинг (title, content, links)
- ✅ Кеш результатов в Redis

### v0.4.0 — Services Table (2026-07-29)
- ✅ Таблица services (uuid, name, url, method, headers, body, timeout, cache_ttl, auto_parse, rate_limit_rpm, callback_url, proxy, enabled)
- ✅ CRUD: create, get, list, update, delete
- ✅ API: GET/POST/PATCH/DELETE /services
- ✅ CLI: hime service list/add/remove

### v0.3.0 — Proxy Sources (2026-07-29)
- ✅ Таблица proxy_sources (uuid, url, type_hint, enabled, last_fetch)
- ✅ CRUD: add, get, list, enable, disable, delete
- ✅ API: GET/POST/PATCH/DELETE /sources
- ✅ CLI: hime source list/add/remove/enable/disable/seed
- ✅ Миграция из конфига в БД

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