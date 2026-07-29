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
    reuse_timeout: int = Field(default=120, description="Seconds before proxy can be reused (LRU)")
    health_check_url: str = Field(
        default="https://httpbin.org/ip", description="URL for health checks"
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
    embedding_url: str = Field(default="http://10.0.0.21:8080/v1", description="Embedding API URL")
    embedding_model: str = Field(default="qwen3-embedding-8b", description="Embedding model name")
    embedding_dimension: int = Field(default=4096, description="Embedding vector dimension")

    model_config = {"env_prefix": "", "env_nested_delimiter": "__"}

    def model_post_init(self, __context) -> None:
        """Apply top-level proxy env vars to nested ProxyConfig."""
        import os
        mapping = {
            "CHECK_INTERVAL": "check_interval",
            "RATE_LIMIT_RPM": "rate_limit_rpm",
            "HEALTH_CHECK_TIMEOUT": "health_check_timeout",
            "MAX_FAILURES": "max_failures",
            "PROXY_REUSE_TIMEOUT": "reuse_timeout",
            "HEALTH_CHECK_URL": "health_check_url",
        }
        for env_key, field_name in mapping.items():
            val = os.environ.get(env_key)
            if val is not None:
                current = getattr(self.proxy, field_name)
                setattr(self.proxy, field_name, type(current)(val))


def load_config() -> AppConfig:
    """Load configuration from environment."""
    return AppConfig()
