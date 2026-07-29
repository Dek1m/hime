# GProxy — Mass Google Scraper with Proxy Rotation

## Статус
В разработке. Фаза 0: скелет проекта.

## Суть
Массовый HTTP-клиент с прокси-ротацией для поисковых запросов к Google. Парсинг HTML выдачи, кеш в Redis, SQLite для списка прокси.

## Стек
- **Python 3.11+** + asyncio
- **httpx[socks]** — HTTP/SOCKS5 прокси
- **selectolax** — парсинг HTML (в 10x быстрее BeautifulSoup)
- **Redis** — кеш на час
- **SQLite** — список прокси
- **pydantic-settings** — конфигурация

## Архитектура

```
gproxy/
├── gproxy/
│   ├── proxy/          # менеджер, checker, rate-limiter
│   ├── scraper/        # HTTP-клиент + парсер Google
│   ├── cache/          # Redis
│   ├── storage/        # SQLite
│   └── cli/            # интерфейс
├── Dockerfile
└── docker-compose.yml
```

## 6 фаз, 17 задач

| Фаза | Суть | Часы | Статус |
|------|------|------|--------|
| 0 | Скелет, конфиг, SQLite, Redis | 3-4ч | ✅ |
| 1 | ProxyManager (round-robin, health-check, rate-limiter) | 5-6ч | ✅ |
| 2 | Async HTTP-клиент + retry | 4-5ч | ⏳ |
| 3 | Парсинг Google HTML | 3-4ч | ⏳ |
| 4 | Оркестрация + CLI | 2-3ч | ⏳ |
| 5 | Docker + CI/CD | 1-2ч | ⏳ |

## Ключевые решения

### ProxyManager
- **Round-robin** через `itertools.cycle` — O(1)
- **Token bucket** rate limiter — 1 запрос/прокси/5мин
- **Health-check** каждую минуту, тестовый URL: httpbin.org/ip
- **Semaphore(100)** для контроля concurrency

### Парсинг Google
- **selectolax** — C-парсер, минимум памяти
- CSS-селекторы: `div.g` (результаты), `h3` (заголовок), `a` (ссылка), `[data-sncf]`/`.VwiC3b` (сниппет)
- Fallback: цепочка селекторов (Google меняет классы)

### Rate Limiting
- 2000 прокси × 1 запрос / 5 мин = 400 запросов/мин = 24000/час
- Запросы Милорда: ~300/час = 1.25% нагрузки

### Кеш Redis
- Key: `gproxy:search:{sha256(query:lang:page)[:16]}`
- TTL: 1 час
- Value: JSON array с SearchResult

### SQLite
- Composite PK: `(ip, port)`
- Статусы: active/dead/unknown
- Индексы: status, last_check

## Инфраструктура (ai-atom.ui)

### Текущий docker-compose.yml
Путь: `~/app/docker-compose.yml`
Сеть: `app_default`
Сервисы: postgres (pgvector:pg18), redis (redis:8-alpine), memory-server, opencode

### Деплой gproxy
1. Добавить сервис в `docker-compose.yml`
2. Или создать отдельный compose файл
3. Подключить к сети `app_default` (для доступа к Redis)
4. Volume для SQLite: `./data/proxies.db`

### CI/CD (GitHub Actions)
- Сборка Docker образа → пуш в ghcr.io
- Деплой через SSH: `docker compose pull && docker compose up -d`

## Риски

1. **Google меняет HTML-селекторы** → regex-fallback в парсере
2. **Бесплатные прокси мрут** → health-check + auto-reload из GitHub
3. **CAPTCHA** → распознавание по `div` с формой, пропуск прокси на 10 мин
4. **SOCKS5 нестабильны** → fallback на HTTP-only прокси
5. **Rate limit Google** → 1 запрос/прокси/5мин строго, + рандомная задержка 2-5 сек

## CLI

```bash
gproxy search "python async" --lang=ru --page=1
gproxy proxy add --file=proxies.txt
gproxy proxy list --status=active
gproxy proxy check
gproxy stats
```

## Конфигурация (.env)

```env
REDIS_URL=redis://localhost:6379/0
SQLITE_PATH=data/proxies.db
MAX_CONCURRENT=100
REQUEST_TIMEOUT=15
CHECK_INTERVAL=60
RATE_LIMIT_RPM=12
CACHE_TTL=3600
LOG_LEVEL=INFO
```
