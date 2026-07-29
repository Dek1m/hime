"""FastAPI application for Hime proxy management."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router
from .state import state

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle — binds store & manager to app.state."""
    from hime.config import load_config
    from hime.proxy.manager import ProxyManager
    from hime.storage import ProxyStore

    config = load_config()
    store = ProxyStore(config.sqlite_path)
    manager = ProxyManager(config.proxy)

    # Attach to app.state so routes can reach them via Request
    app.state.store = store
    app.state.manager = manager

    active = store.get_active()
    await manager.start(active, store)

    logger.info("Hime API started — %d active proxies", len(active))

    yield  # ── server is live ──

    await manager.stop()
    state.shutdown()
    logger.info("Hime API shut down")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title="Hime API",
        description="Proxy management API for Hime scraper",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


# Module-level instance — used by `uvicorn hime.api.app:app`
app = create_app()
