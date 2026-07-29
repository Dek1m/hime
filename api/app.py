"""FastAPI application for Hime proxy management."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Store and manager are created eagerly and bound to app.state.
    Lifespan handles startup/shutdown lifecycle.
    """
    from hime.config import load_config
    from hime.proxy.manager import ProxyManager
    from hime.storage import ProxyStore

    config = load_config()
    store = ProxyStore(config.sqlite_path)
    manager = ProxyManager(config.proxy)

    app = FastAPI(
        title="Hime API",
        description="Proxy management API for Hime scraper",
        version="0.1.0",
    )

    # Bind to app.state — routes read these via Request.app.state
    app.state.store = store
    app.state.manager = manager

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.on_event("startup")
    async def on_startup():
        active = store.get_active()
        await manager.start(active, store)
        logger.info("Hime API started — %d active proxies", len(active))

    @app.on_event("shutdown")
    async def on_shutdown():
        await manager.stop()
        logger.info("Hime API shut down")

    return app


# Module-level instance — used by `uvicorn hime.api.app:app`
app = create_app()
