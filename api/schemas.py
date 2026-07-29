"""Pydantic response schemas for Hime API."""

from datetime import datetime

from pydantic import BaseModel, Field


class ProxyResponse(BaseModel):
    """Single proxy representation."""

    uuid: str
    ip: str
    port: int
    type: str = Field(description="Proxy protocol: http, https, socks5")
    status: str = Field(description="Proxy status: active, dead, unknown")
    last_check: datetime | None = None
    last_working: datetime | None = None
    added_at: str | None = None
    last_used: datetime | None = None
    source: str = ""


class ProxyListResponse(BaseModel):
    """Paginated proxy list."""

    proxies: list[ProxyResponse]
    total: int


class StatsResponse(BaseModel):
    """Aggregate proxy statistics."""

    total: int
    active: int
    dead: int
    unknown: int
    by_source: dict[str, int]


class CheckResponse(BaseModel):
    """Health check trigger result."""

    status: str = "started"
    message: str = "Health check triggered"


class LoadResponse(BaseModel):
    """Proxy load trigger result."""

    status: str = "started"
    message: str = "Proxy loading from GitHub triggered"


class HealthResponse(BaseModel):
    """API health check."""

    status: str = "ok"
