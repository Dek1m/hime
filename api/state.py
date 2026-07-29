"""Application state — single source of truth for store & manager."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hime.proxy.manager import ProxyManager
    from hime.storage import ProxyStore

logger = logging.getLogger(__name__)


@dataclass
class AppState:
    """Mutable container shared across the entire app lifecycle.

    Store and manager are None until startup() completes.
    Routes pull them via ``get_store`` / ``get_manager``.
    """

    store: ProxyStore | None = None
    manager: ProxyManager | None = None

    # -- lifecycle -----------------------------------------------------------

    def startup(self, store: ProxyStore, manager: ProxyManager) -> None:
        """Bind the live instances.  Called once at app startup."""
        self.store = store
        self.manager = manager
        logger.info("AppState: store & manager bound")

    def shutdown(self) -> None:
        """Release references (best-effort)."""
        self.store = None
        self.manager = None
        logger.info("AppState: released")


# Singleton — imported everywhere, mutated at startup.
state = AppState()
