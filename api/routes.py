"""API route handlers."""

import asyncio
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from hime.proxy import ProxyStatus, ProxyType
from hime.proxy.loader import load_all_proxies
from hime.proxy.manager import ProxyManager
from hime.storage import ProxyStore

from .schemas import (
    CheckResponse,
    HealthResponse,
    LoadResponse,
    ProxyListResponse,
    ProxyResponse,
    StatsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency — inject store/manager from app state
# ---------------------------------------------------------------------------

def _get_store() -> ProxyStore:
    raise RuntimeError("Store not initialized")


def _get_manager() -> ProxyManager:
    raise RuntimeError("Manager not initialized")


def init_dependencies(store: ProxyStore, manager: ProxyManager) -> None:
    """Replace stub dependencies with live instances at startup."""
    global _get_store, _get_manager  # noqa: PLW0603
    _get_store = lambda: store  # type: ignore[misc]
    _get_manager = lambda: manager  # type: ignore[misc]


StoreDep = Annotated[ProxyStore, Depends(_get_store)]
ManagerDep = Annotated[ProxyManager, Depends(_get_manager)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts_to_iso(ts: float) -> Optional[str]:
    """Convert UNIX timestamp to ISO string, or None if zero."""
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
        last_check=_ts_to_iso(p.last_check),
        last_working=_ts_to_iso(p.last_working),
        added_at=p.added_at or None,
        last_used=_ts_to_iso(p.last_used),
        source=p.source,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.get("/proxies", response_model=ProxyListResponse)
async def list_proxies(
    store: StoreDep,
    status: Optional[str] = Query(None, description="Filter by status: active, dead, unknown"),
    type: Optional[str] = Query(None, description="Filter by type: http, https, socks5"),
    source: Optional[str] = Query(None, description="Filter by source substring"),
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

    total = len(proxies)
    page = proxies[offset : offset + limit]

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
async def get_proxy(
    proxy_uuid: str,
    store: StoreDep,
) -> ProxyResponse:
    proxy = store.get_by_uuid(proxy_uuid)
    if proxy is None:
        raise HTTPException(status_code=404, detail="Proxy not found")
    return _proxy_to_response(proxy)


async def _run_health_checks(manager: ProxyManager) -> None:
    """Background task: run full health check cycle."""
    try:
        await manager._run_health_checks()
    except Exception:
        logger.exception("Background health check failed")


@router.post("/proxies/check", response_model=CheckResponse)
async def trigger_check(
    background_tasks: BackgroundTasks,
    manager: ManagerDep,
) -> CheckResponse:
    background_tasks.add_task(_run_health_checks, manager)
    return CheckResponse()


async def _load_from_github(store: ProxyStore, manager: ProxyManager) -> None:
    """Background task: load proxies from GitHub and sync."""
    try:
        proxies = await load_all_proxies()
        store.bulk_upsert(proxies)
        active = store.get_active()
        await manager.stop()
        await manager.start(active, store)
        logger.info("Loaded %d proxies from GitHub", len(proxies))
    except Exception:
        logger.exception("Background proxy load failed")


@router.post("/proxies/load", response_model=LoadResponse)
async def trigger_load(
    background_tasks: BackgroundTasks,
    store: StoreDep,
    manager: ManagerDep,
) -> LoadResponse:
    background_tasks.add_task(_load_from_github, store, manager)
    return LoadResponse()


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

    return StatsResponse(
        total=total,
        active=by_status.get("active", 0),
        dead=by_status.get("dead", 0),
        unknown=by_status.get("unknown", 0),
        by_source=by_source,
    )
