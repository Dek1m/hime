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
    CheckResponse,
    CheckStatusResponse,
    HealthResponse,
    LoadResponse,
    ProxyListResponse,
    ProxyResponse,
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
        proxies = await load_all_proxies()
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
