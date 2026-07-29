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


# ──────────────── Services ────────────────


class ServiceCreate(BaseModel):
    """Request to create a service."""

    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., description="Base URL of the service endpoint")
    method: str = Field(default="GET", pattern="^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$")
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = Field(default="", description="Request body (for POST/PUT/PATCH)")
    timeout: float = Field(default=15.0, ge=1.0, le=300.0)
    cache_ttl: int = Field(default=0, ge=0, description="Cache TTL in seconds (0 = no cache)")
    auto_parse: bool = Field(default=True, description="Auto-parse response")
    rate_limit_rpm: int = Field(default=60, ge=1, le=10000, description="Requests per minute")
    callback_url: str = Field(default="", description="Callback URL")
    proxy: bool = Field(default=False, description="Use proxy")
    enabled: bool = Field(default=True)


class ServiceUpdate(BaseModel):
    """Request to update a service (all fields optional)."""

    name: str | None = Field(None, min_length=1, max_length=100)
    url: str | None = None
    method: str | None = Field(None, pattern="^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$")
    headers: dict[str, str] | None = None
    body: str | None = None
    timeout: float | None = Field(None, ge=1.0, le=300.0)
    cache_ttl: int | None = Field(None, ge=0)
    auto_parse: bool | None = None
    rate_limit_rpm: int | None = Field(None, ge=1, le=10000)
    callback_url: str | None = None
    proxy: bool | None = None
    enabled: bool | None = None


class ServiceResponse(BaseModel):
    """Single service representation."""

    uuid: str
    name: str
    url: str
    method: str
    headers: dict[str, str]
    body: str
    timeout: float
    cache_ttl: int
    auto_parse: bool
    rate_limit_rpm: int
    callback_url: str
    proxy: bool
    enabled: bool
    created_at: str
    modified_at: str


class ServiceListResponse(BaseModel):
    """List of services."""

    services: list[ServiceResponse]
    total: int


# ──────────────── Fetch ────────────────


class FetchRequest(BaseModel):
    """Universal HTTP fetch request."""

    url: str = Field(..., description="Target URL")
    method: str = Field(default="GET", pattern="^(GET|POST)$")
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = Field(default="", description="Request body for POST")
    proxy: str | None = Field(default=None, description="Proxy URL (http/socks5)")
    timeout: float = Field(default=15.0, ge=1.0, le=60.0)


class FetchLink(BaseModel):
    """Extracted link from page."""

    url: str
    title: str = ""
    description: str = ""


class FetchResponse(BaseModel):
    """Universal fetch response."""

    ok: bool
    url: str
    status: int
    title: str = ""
    content: str = ""
    links: list[FetchLink] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)
    timing_ms: float = 0.0
    error: str | None = None
