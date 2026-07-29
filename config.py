"""Configuration for Hime."""

import logging
import sys

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with format and level from env."""
    numeric = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT))
    root = logging.getLogger("hime")
    root.setLevel(numeric)
    root.handlers.clear()
    root.addHandler(handler)
    root.propagate = False


class ProxyConfig(BaseModel):
    """Proxy manager configuration."""

    check_interval: int = Field(default=60, description="Seconds between health checks")
    rate_limit_rpm: int = Field(default=12, description="Requests per minute per proxy")
    health_check_timeout: float = Field(default=5.0, description="Health check timeout")
    max_failures: int = Field(default=3, description="Max failures before marking dead")
    health_check_url: str = Field(
        default="https://httpbin.org/ip", description="URL for health checks"
    )
    proxy_sources: list[str] = Field(
        default=[
            # === TheSpeedX ===
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
            # === ShiftyTR ===
            "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
            "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/https.txt",
            # === monosans ===
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
            # === clarketm ===
            "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
            # === vmheaven (7k+ http, 1k+ socks5) ===
            "https://raw.githubusercontent.com/vmheaven/VMHeaven.io-Free-Proxy-List/main/http.txt",
            "https://raw.githubusercontent.com/vmheaven/VMHeaven.io-Free-Proxy-List/main/https.txt",
            "https://raw.githubusercontent.com/vmheaven/VMHeaven.io-Free-Proxy-List/main/socks5.txt",
            # === hproxy-com (3k+ http) ===
            "https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/http.txt",
            "https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/https.txt",
            "https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/socks5.txt",
            # === ProxyScrape (1k+ http, 900+ socks5) ===
            "https://raw.githubusercontent.com/ProxyScrape/free-proxy-list/main/proxies/protocols/http/data.txt",
            "https://raw.githubusercontent.com/ProxyScrape/free-proxy-list/main/proxies/protocols/https/data.txt",
            "https://raw.githubusercontent.com/ProxyScrape/free-proxy-list/main/proxies/protocols/socks5/data.txt",
            # === hookzof (600+ socks5) ===
            "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
            # === vakhov (500+ http) ===
            "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/http.txt",
            "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks5.txt",
            # === stormsia (200+ http, 40+ socks5) ===
            "https://raw.githubusercontent.com/stormsia/proxy-list/main/http.txt",
            "https://raw.githubusercontent.com/stormsia/proxy-list/main/socks5.txt",
        ],
        description="GitHub raw URLs with proxy lists",
    )


class CacheConfig(BaseModel):
    """Redis cache configuration."""

    ttl: int = Field(default=3600, description="Cache TTL in seconds")
    prefix: str = Field(default="hime", description="Redis key prefix")


class ScraperConfig(BaseModel):
    """Scraper configuration."""

    max_concurrent: int = Field(default=100, description="Max concurrent requests")
    request_timeout: float = Field(default=15.0, description="HTTP request timeout")
    user_agent: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
        description="User-Agent header",
    )
    search_domain: str = Field(default="google.com", description="Google domain")
    language: str = Field(default="ru", description="Search language")
    retry_count: int = Field(default=3, description="Retry count per request")
    retry_delay: float = Field(default=1.0, description="Base retry delay in seconds")


class AppConfig(BaseSettings):
    """Main application configuration."""

    proxy: ProxyConfig = ProxyConfig()
    cache: CacheConfig = CacheConfig()
    scraper: ScraperConfig = ScraperConfig()

    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis URL")
    sqlite_path: str = Field(default="db/proxies.db", description="SQLite database path")
    log_level: str = Field(default="INFO", description="Logging level")

    model_config = {"env_prefix": "", "env_nested_delimiter": "__"}


def load_config() -> AppConfig:
    """Load configuration from environment."""
    return AppConfig()
