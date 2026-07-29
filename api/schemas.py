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
    latency_ms: float = Field(description="Response latency in milliseconds", default=0.0)
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
    avg_latency_ms: float = Field(description="Average latency of active proxies in ms", default=0.0)


class CheckStatusResponse(BaseModel):
    """Health check progress."""

    running: bool
    total: int
    checked: int
    active: int
    dead: int
    unknown: int
    progress_pct: float = Field(description="Check progress percentage")
    elapsed_sec: float


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


# ──────────────── Sources ────────────────


class SourceCreate(BaseModel):
    """Request to create a proxy source."""

    url: str
    type_hint: str = Field(default="http", description="Fallback proxy type: http, https, socks5")


class SourceUpdate(BaseModel):
    """Request to update a proxy source."""

    enabled: bool | None = None
    type_hint: str | None = None


class SourceResponse(BaseModel):
    """Single proxy source representation."""

    uuid: str
    url: str
    type_hint: str
    enabled: bool
    last_check: datetime | None = None
    added_at: str | None = None


class SourceListResponse(BaseModel):
    """List of proxy sources."""

    sources: list[SourceResponse]
    total: int
    enabled: int
