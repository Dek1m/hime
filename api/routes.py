"""API route handlers."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from hime.proxy import ProxyStatus, ProxyType
from hime.proxy.loader import load_all_proxies
from hime.proxy.manager import ProxyManager
from hime.storage import ProxyStore

from .schemas import (
    CacheStatsResponse,
    CheckResponse,
    CheckStatusResponse,
    FetchLink,
    FetchRequest,
    FetchResponse,
    HealthResponse,
    LoadResponse,
    ProxyListResponse,
    ProxyResponse,
    ServiceCreate,
    ServiceListResponse,
    ServiceResponse,
    ServiceUpdate,
    SourceCreate,
    SourceListResponse,
    SourceResponse,
    SourceUpdate,
    StatsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Global task registry
# ---------------------------------------------------------------------------

_tasks: dict[str, asyncio.Task] = {}


def _task_name(prefix: str) -> str:
    return f"{prefix}_{int(time.time())}"


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def _get_store(request: Request) -> ProxyStore:
    store: ProxyStore | None = request.app.state.store
    if store is None:
        raise RuntimeError("Store not initialized")
    return store


def _get_manager(request: Request) -> ProxyManager:
    manager: ProxyManager | None = request.app.state.manager
    if manager is None:
        raise RuntimeError("Manager not initialized")
    return manager


StoreDep = Annotated[ProxyStore, Depends(_get_store)]
ManagerDep = Annotated[ProxyManager, Depends(_get_manager)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts_to_iso(ts: float) -> Optional[str]:
    if not ts:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _proxy_to_response(p) -> ProxyResponse:
    return ProxyResponse(
        uuid=p.uuid,
        ip=p.ip,
        port=p.port,
        type=p.type.value,
        status=p.status.value,
        latency_ms=round(p.latency_ms, 1),
        last_check=_ts_to_iso(p.last_check),
        last_working=_ts_to_iso(p.last_working),
        added_at=p.added_at or None,
        last_used=_ts_to_iso(p.last_used),
        source=p.source,
    )


# ---------------------------------------------------------------------------
# Background coroutines
# ---------------------------------------------------------------------------

async def _bg_health_check(store: ProxyStore, manager: ProxyManager) -> None:
    """Run full health check on ALL proxies from DB."""
    logger.info("Background health check started")
    try:
        all_proxies = store.get_all()
        manager._proxies = all_proxies
        manager._rebuild_cycle()
        await manager._run_health_checks()
        logger.info("Background health check finished — %d proxies checked", len(all_proxies))
    except Exception:
        logger.exception("Background health check failed")


async def _bg_load_from_github(store: ProxyStore, manager: ProxyManager) -> None:
    """Load proxies from GitHub, save to DB, restart manager."""
    logger.info("Background proxy load started")
    try:
        proxies = await load_all_proxies(store)
        store.bulk_upsert(proxies)
        active = store.get_active()
        await manager.stop()
        await manager.start(active, store)
        logger.info("Background proxy load finished — %d proxies", len(proxies))
    except Exception:
        logger.exception("Background proxy load failed")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.get("/proxies", response_model=ProxyListResponse)
async def list_proxies(
    store: StoreDep,
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    sort: Optional[str] = Query(None, description="Sort by: latency, last_check, last_working"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> ProxyListResponse:
    proxies = store.get_all()
    if status:
        proxies = [p for p in proxies if p.status.value == status]
    if type:
        proxies = [p for p in proxies if p.type.value == type]
    if source:
        proxies = [p for p in proxies if source.lower() in p.source.lower()]

    # Sorting
    if sort == "latency":
        proxies.sort(key=lambda p: p.latency_ms if p.latency_ms > 0 else float("inf"))
    elif sort == "last_check":
        proxies.sort(key=lambda p: p.last_check, reverse=True)
    elif sort == "last_working":
        proxies.sort(key=lambda p: p.last_working, reverse=True)

    total = len(proxies)
    page = proxies[offset:offset + limit]
    return ProxyListResponse(
        proxies=[_proxy_to_response(p) for p in page],
        total=total,
    )


@router.get("/proxies/next", response_model=ProxyResponse)
async def next_proxy(manager: ManagerDep) -> ProxyResponse:
    proxy = await manager.get_proxy()
    if proxy is None:
        raise HTTPException(status_code=404, detail="No available proxy")
    return _proxy_to_response(proxy)


@router.get("/proxies/{proxy_uuid}", response_model=ProxyResponse)
async def get_proxy(proxy_uuid: str, store: StoreDep) -> ProxyResponse:
    proxy = store.get_by_uuid(proxy_uuid)
    if proxy is None:
        raise HTTPException(status_code=404, detail="Proxy not found")
    return _proxy_to_response(proxy)


@router.get("/tasks")
async def list_tasks():
    """List active background tasks."""
    return {
        name: {
            "done": task.done(),
            "cancelled": task.cancelled(),
        }
        for name, task in _tasks.items()
    }


@router.get("/check/status", response_model=CheckStatusResponse)
async def check_status(manager: ManagerDep) -> CheckStatusResponse:
    """Get current health check progress."""
    return CheckStatusResponse(**manager.progress.to_dict())


@router.post("/proxies/check", response_model=CheckResponse)
async def trigger_check(store: StoreDep, manager: ManagerDep) -> CheckResponse:
    """Launch health check as a non-blocking background task."""
    name = _task_name("health_check")
    # Cancel previous check if still running
    for k, t in list(_tasks.items()):
        if k.startswith("health_check") and not t.done():
            t.cancel()
    # Reset progress before starting new check
    manager.progress.reset(0)
    task = asyncio.create_task(_bg_health_check(store, manager))
    _tasks[name] = task
    task.add_done_callback(lambda t: _tasks.pop(name, None))
    return CheckResponse(status="started", message=f"Health check started: {name}")


@router.post("/proxies/load", response_model=LoadResponse)
async def trigger_load(store: StoreDep, manager: ManagerDep) -> LoadResponse:
    """Launch GitHub proxy loading as a non-blocking background task."""
    name = _task_name("proxy_load")
    task = asyncio.create_task(_bg_load_from_github(store, manager))
    _tasks[name] = task
    task.add_done_callback(lambda t: _tasks.pop(name, None))
    return LoadResponse(status="started", message=f"Proxy loading started: {name}")


@router.get("/stats", response_model=StatsResponse)
async def stats(store: StoreDep) -> StatsResponse:
    all_proxies = store.get_all()
    total = len(all_proxies)
    by_status = {"active": 0, "dead": 0, "unknown": 0}
    by_source: dict[str, int] = {}
    for p in all_proxies:
        by_status[p.status.value] = by_status.get(p.status.value, 0) + 1
        src = p.source or "unknown"
        by_source[src] = by_source.get(src, 0) + 1
    avg_lat = store.get_avg_latency("active")
    return StatsResponse(
        total=total,
        active=by_status.get("active", 0),
        dead=by_status.get("dead", 0),
        unknown=by_status.get("unknown", 0),
        by_source=by_source,
        avg_latency_ms=round(avg_lat, 1),
    )


@router.get("/cache/stats", response_model=CacheStatsResponse)
async def cache_stats(request: Request) -> CacheStatsResponse:
    """Redis cache statistics — key counts by type, memory usage."""
    cache = request.app.state.cache
    stats = await cache.stats()
    return CacheStatsResponse(**stats)


# ──────────────── Sources ────────────────


def _source_to_response(s) -> SourceResponse:
    from datetime import datetime, timezone
    last_fetch_dt = None
    if s.last_fetch:
        last_fetch_dt = datetime.fromtimestamp(s.last_fetch, tz=timezone.utc)
    return SourceResponse(
        uuid=s.uuid,
        url=s.url,
        type_hint=s.type_hint,
        enabled=s.enabled,
        last_check=last_fetch_dt,
        added_at=s.added_at or None,
    )


@router.get("/sources", response_model=SourceListResponse)
async def list_sources(store: StoreDep) -> SourceListResponse:
    """List all proxy sources."""
    sources = store.list_sources()
    enabled_count = sum(1 for s in sources if s.enabled)
    return SourceListResponse(
        sources=[_source_to_response(s) for s in sources],
        total=len(sources),
        enabled=enabled_count,
    )


@router.post("/sources", response_model=SourceResponse)
async def create_source(body: SourceCreate, store: StoreDep) -> SourceResponse:
    """Add a new proxy source."""
    existing = store.get_source_by_url(body.url)
    if existing:
        raise HTTPException(status_code=409, detail="Source already exists")
    source = store.add_source(body.url, body.type_hint)
    return _source_to_response(source)


@router.patch("/sources/{source_uuid}", response_model=SourceResponse)
async def update_source(
    source_uuid: str,
    body: SourceUpdate,
    store: StoreDep,
) -> SourceResponse:
    """Update a proxy source (enable/disable, change type)."""
    # Find by prefix
    sources = store.list_sources()
    target = None
    for s in sources:
        if s.uuid.startswith(source_uuid):
            target = s
            break
    if target is None:
        raise HTTPException(status_code=404, detail="Source not found")

    if body.enabled is not None:
        if body.enabled:
            store.enable_source(target.uuid)
        else:
            store.disable_source(target.uuid)
    if body.type_hint is not None:
        store.update_source_type(target.uuid, body.type_hint)

    updated = store.get_source(target.uuid)
    return _source_to_response(updated)


@router.delete("/sources/{source_uuid}")
async def delete_source(source_uuid: str, store: StoreDep) -> dict:
    """Delete a proxy source."""
    sources = store.list_sources()
    target = None
    for s in sources:
        if s.uuid.startswith(source_uuid):
            target = s
            break
    if target is None:
        raise HTTPException(status_code=404, detail="Source not found")

    store.delete_source(target.uuid)
    return {"deleted": True, "uuid": target.uuid, "url": target.url}


@router.post("/sources/seed")
async def seed_sources(store: StoreDep) -> dict:
    """Seed default sources from config into DB."""
    from hime.config import load_config
    config = load_config()
    urls = [(url, "http") for url in config.proxy.proxy_sources]
    added = store.seed_sources(urls)
    total = len(store.list_sources())
    return {"added": added, "total": total}


# ──────────────── Services ────────────────


def _service_to_response(s) -> ServiceResponse:
    return ServiceResponse(
        uuid=s.uuid,
        name=s.name,
        url=s.url,
        method=s.method,
        headers=s.headers,
        body=s.body,
        timeout=s.timeout,
        cache_ttl=s.cache_ttl,
        auto_parse=s.auto_parse,
        rate_limit_rpm=s.rate_limit_rpm,
        callback_url=s.callback_url,
        proxy=s.proxy,
        enabled=s.enabled,
        created_at=s.created_at or "",
        modified_at=s.modified_at or "",
    )


@router.get("/services", response_model=ServiceListResponse)
async def list_services(
    store: StoreDep,
    enabled: Optional[bool] = Query(None),
) -> ServiceListResponse:
    """List all services."""
    services = store.list_services(enabled_only=enabled is True)
    return ServiceListResponse(
        services=[_service_to_response(s) for s in services],
        total=len(services),
    )


@router.get("/services/{service_uuid}", response_model=ServiceResponse)
async def get_service(service_uuid: str, store: StoreDep) -> ServiceResponse:
    """Get service by UUID."""
    service = store.get_service(service_uuid)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return _service_to_response(service)


@router.post("/services", response_model=ServiceResponse, status_code=201)
async def create_service(body: ServiceCreate, store: StoreDep) -> ServiceResponse:
    """Create a new service."""
    if store.service_exists(body.name):
        raise HTTPException(status_code=409, detail=f"Service '{body.name}' already exists")
    service = store.create_service(
        name=body.name,
        url=body.url,
        method=body.method,
        headers=body.headers,
        body=body.body,
        timeout=body.timeout,
        cache_ttl=body.cache_ttl,
        auto_parse=body.auto_parse,
        rate_limit_rpm=body.rate_limit_rpm,
        callback_url=body.callback_url,
        proxy=body.proxy,
        enabled=body.enabled,
    )
    return _service_to_response(service)


@router.patch("/services/{service_uuid}", response_model=ServiceResponse)
async def update_service(
    service_uuid: str,
    body: ServiceUpdate,
    store: StoreDep,
) -> ServiceResponse:
    """Update a service (partial update)."""
    existing = store.get_service(service_uuid)
    if existing is None:
        raise HTTPException(status_code=404, detail="Service not found")

    if body.name is not None and body.name != existing.name:
        if store.service_exists(body.name):
            raise HTTPException(status_code=409, detail=f"Service '{body.name}' already exists")

    updates = body.model_dump(exclude_unset=True)
    updated = store.update_service(service_uuid, **updates)
    return _service_to_response(updated)


@router.delete("/services/{service_uuid}")
async def delete_service(service_uuid: str, store: StoreDep) -> dict:
    """Delete a service."""
    existing = store.get_service(service_uuid)
    if existing is None:
        raise HTTPException(status_code=404, detail="Service not found")
    store.delete_service(service_uuid)
    return {"deleted": True, "uuid": service_uuid, "name": existing.name}


# ──────────────── Fetch ────────────────


@router.post("/fetch", response_model=FetchResponse)
async def fetch_url(
    body: FetchRequest,
    request: Request,
) -> FetchResponse:
    """Universal HTTP fetch with HTML parsing and vector cache.

    If a semantically similar result exists in cache (cosine >= 0.95),
    returns cached version instead of making a new request.
    """
    from hime.scraper.fetcher import fetch_url as do_fetch

    cache = request.app.state.cache
    embedding = request.app.state.embedding

    # 1. Try exact cache match by URL
    cached = await cache.get_by_query(body.url)
    if cached and cached.get("results"):
        logger.info("Cache hit for URL=%s (uuid=%s)", body.url[:60], cached.get("uuid", "?"))
        results = cached["results"]
        return FetchResponse(
            ok=True,
            url=cached.get("url", body.url),
            status=200,
            title=cached.get("title", ""),
            content=cached.get("content", ""),
            links=[FetchLink(**link) for link in results] if results and isinstance(results[0], dict) and "url" in results[0] else [],
            headers={},
            timing_ms=0.0,
            cache_uuid=cached.get("uuid"),
        )

    # 2. Try semantic search if embedding is available
    if body.url and embedding:
        try:
            vector = await embedding.embed(body.url)
            similar = await cache.find_similar(vector, threshold=0.95, limit=1)
            if similar:
                item = similar[0]
                logger.info("Semantic cache hit: similarity >= 0.95, uuid=%s", item.get("uuid"))
                results = item.get("results", [])
                return FetchResponse(
                    ok=True,
                    url=item.get("url", body.url),
                    status=200,
                    title=item.get("title", ""),
                    content=item.get("content", ""),
                    links=[FetchLink(**link) for link in results] if results and isinstance(results[0], dict) and "url" in results[0] else [],
                    headers={},
                    timing_ms=0.0,
                    cache_uuid=item.get("uuid"),
                )
        except Exception as e:
            logger.warning("Semantic search failed: %s", e)

    # 3. Fetch from network
    result = await do_fetch(
        url=body.url,
        method=body.method,
        headers=body.headers,
        body=body.body,
        proxy=body.proxy,
        timeout=body.timeout,
    )

    # 4. Cache the result with vector
    cache_uuid = None
    if result.get("ok") and embedding:
        try:
            vector = await embedding.embed(body.url)
            links_data = result.get("links", [])
            cache_uuid = await cache.set_with_vector(
                query=body.url,
                results=links_data,
                vector=vector,
            )
            logger.info("Cached result uuid=%s for URL=%s", cache_uuid, body.url[:60])
        except Exception as e:
            logger.warning("Failed to cache result: %s", e)

    return FetchResponse(
        ok=result["ok"],
        url=result["url"],
        status=result["status"],
        title=result.get("title", ""),
        content=result.get("content", ""),
        links=[FetchLink(**link) for link in result.get("links", [])],
        headers=result.get("headers", {}),
        timing_ms=round(result.get("timing_ms", 0), 1),
        cache_uuid=cache_uuid,
        error=result.get("error"),
    )
