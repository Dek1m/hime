"""FastAPI application for Hime proxy management."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hime.config import load_config
from hime.proxy.manager import ProxyManager
from hime.storage import ProxyStore

from .routes import init_dependencies, router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title="Hime API",
        description="Proxy management API for Hime scraper",
        version="0.1.0",
    )

    # CORS — allow everything for now
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    config = load_config()
    store = ProxyStore(config.sqlite_path)
    manager = ProxyManager(config.proxy)

    @app.on_event("startup")
    async def on_startup() -> None:
        active = store.get_active()
        await manager.start(active, store)
        init_dependencies(store, manager)
        logger.info("Hime API started with %d active proxies", len(active))

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        await manager.stop()
        logger.info("Hime API shut down")

    app.include_router(router)

    return app


app = create_app()
