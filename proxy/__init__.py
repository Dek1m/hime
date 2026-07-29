"""Data models for proxy."""

import uuid as _uuid
from dataclasses import dataclass, field
from enum import Enum
import time


class ProxyType(str, Enum):
    """Proxy protocol type."""

    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"


class ProxyStatus(str, Enum):
    """Proxy health status."""

    ACTIVE = "active"
    DEAD = "dead"
    UNKNOWN = "unknown"


@dataclass
class ProxyData:
    """Proxy data model."""

    ip: str
    port: int
    type: ProxyType = ProxyType.HTTP
    status: ProxyStatus = ProxyStatus.UNKNOWN
    last_check: float = 0.0
    last_working: float = 0.0
    response_time: float = 0.0
    failure_count: int = 0
    last_used: float = 0.0
    added_at: str = ""
    source: str = ""
    uuid: str = field(default_factory=lambda: str(_uuid.uuid4()))

    @property
    def url(self) -> str:
        """Get proxy URL for httpx."""
        return f"{self.type.value}://{self.ip}:{self.port}"

    @property
    def is_available(self) -> bool:
        """Check if proxy is available for use."""
        return self.status == ProxyStatus.ACTIVE and self.failure_count < 3

    def mark_success(self, response_time_ms: float) -> None:
        """Mark successful request."""
        self.status = ProxyStatus.ACTIVE
        self.failure_count = 0
        self.response_time = response_time_ms
        self.last_used = time.time()
        self.last_working = time.time()

    def mark_failure(self) -> None:
        """Mark failed request."""
        self.failure_count += 1
        if self.failure_count >= 3:
            self.status = ProxyStatus.DEAD

    def mark_checked(self, alive: bool, response_time_ms: float = 0.0) -> None:
        """Mark health check result."""
        self.last_check = time.time()
        self.response_time = response_time_ms
        if alive:
            self.status = ProxyStatus.ACTIVE
            self.failure_count = 0
            self.last_working = time.time()
        else:
            self.failure_count += 1
            if self.failure_count >= 3:
                self.status = ProxyStatus.DEAD
