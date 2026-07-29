"""SQLite storage for proxies, sources and services."""

import json
import sqlite3
import uuid as _uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from hime.proxy import ProxyData, ProxyType, ProxyStatus


@dataclass
class ProxySource:
    """Proxy source data model."""
    uuid: str
    url: str
    type_hint: str = "http"
    enabled: bool = True
    last_fetch: float = 0.0
    added_at: str = ""


@dataclass
class ServiceData:
    """Service configuration data model."""
    uuid: str
    name: str
    url: str
    method: str = "GET"
    headers: dict = field(default_factory=dict)
    body: str = ""
    timeout: float = 15.0
    cache_ttl: int = 0
    auto_parse: bool = True
    rate_limit_rpm: int = 60
    callback_url: str = ""
    proxy: bool = False
    enabled: bool = True
    created_at: str = ""
    modified_at: str = ""


class ProxyStore:
    """SQLite storage for proxy list and sources."""

    def __init__(self, db_path: str = "db/proxies.db"):
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS proxies (
                    uuid          TEXT    PRIMARY KEY,
                    ip            TEXT    NOT NULL,
                    port          INTEGER NOT NULL,
                    type          TEXT    NOT NULL DEFAULT 'http',
                    status        TEXT    NOT NULL DEFAULT 'unknown',
                    last_check    REAL    DEFAULT 0,
                    last_working  REAL    DEFAULT 0,
                    latency_ms    REAL    DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    last_used     REAL    DEFAULT 0,
                    added_at      TEXT    DEFAULT (datetime('now')),
                    source        TEXT    DEFAULT '',
                    UNIQUE(ip, port)
                );

                CREATE INDEX IF NOT EXISTS idx_proxies_status
                    ON proxies(status);
                CREATE INDEX IF NOT EXISTS idx_proxies_last_check
                    ON proxies(last_check);

                CREATE TABLE IF NOT EXISTS proxy_sources (
                    uuid        TEXT PRIMARY KEY,
                    url         TEXT NOT NULL UNIQUE,
                    type_hint   TEXT NOT NULL DEFAULT 'http',
                    enabled     INTEGER NOT NULL DEFAULT 1,
                    last_fetch  REAL DEFAULT 0,
                    added_at    TEXT DEFAULT (datetime('now'))
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_url
                    ON proxy_sources(url);
                CREATE INDEX IF NOT EXISTS idx_sources_enabled
                    ON proxy_sources(enabled);

                CREATE TABLE IF NOT EXISTS services (
                    uuid            TEXT PRIMARY KEY,
                    name            TEXT    NOT NULL UNIQUE,
                    url             TEXT    NOT NULL,
                    method          TEXT    NOT NULL DEFAULT 'GET',
                    headers         TEXT    DEFAULT '{}',
                    body            TEXT    DEFAULT '',
                    timeout         REAL    DEFAULT 15.0,
                    cache_ttl       INTEGER DEFAULT 0,
                    auto_parse      INTEGER DEFAULT 1,
                    rate_limit_rpm  INTEGER DEFAULT 60,
                    callback_url    TEXT    DEFAULT '',
                    proxy           INTEGER DEFAULT 0,
                    enabled         INTEGER DEFAULT 1,
                    created_at      TEXT    DEFAULT (datetime('now')),
                    modified_at     TEXT    DEFAULT (datetime('now'))
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_services_name
                    ON services(name);
                CREATE INDEX IF NOT EXISTS idx_services_enabled
                    ON services(enabled);
                """
            )
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Run all schema migrations."""
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='proxies'")
        if not cursor.fetchone():
            return

        cursor = conn.execute("PRAGMA table_info(proxies)")
        columns = {row["name"] for row in cursor.fetchall()}

        # Migration: add uuid column (from v0.1 schema)
        if "uuid" not in columns:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS proxies_new (
                    uuid          TEXT    PRIMARY KEY,
                    ip            TEXT    NOT NULL,
                    port          INTEGER NOT NULL,
                    type          TEXT    NOT NULL DEFAULT 'http',
                    status        TEXT    NOT NULL DEFAULT 'unknown',
                    last_check    REAL    DEFAULT 0,
                    last_working  REAL    DEFAULT 0,
                    latency_ms    REAL    DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    last_used     REAL    DEFAULT 0,
                    added_at      TEXT    DEFAULT (datetime('now')),
                    source        TEXT    DEFAULT '',
                    UNIQUE(ip, port)
                );

                INSERT INTO proxies_new (uuid, ip, port, type, status, last_check,
                                         latency_ms, failure_count, last_used, added_at)
                SELECT lower(hex(randomblob(4)) || '-' || lower(hex(randomblob(2))) || '-4' ||
                             substr(lower(hex(randomblob(2))),2) || '-' ||
                             substr('89ab',abs(random())%4+1,1) ||
                             substr(lower(hex(randomblob(2))),2) || '-' ||
                             lower(hex(randomblob(6)))),
                       ip, port, type, status, last_check,
                       response_time, failure_count, last_used,
                       COALESCE(created_at, datetime('now'))
                FROM proxies;

                DROP TABLE proxies;
                ALTER TABLE proxies_new RENAME TO proxies;
                """
            )

        # Migration: rename response_time → latency_ms (from v0.1 schema)
        if "response_time" in columns and "latency_ms" not in columns:
            conn.execute("ALTER TABLE proxies RENAME COLUMN response_time TO latency_ms")

        # Recreate indexes
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_proxies_status
                ON proxies(status);
            CREATE INDEX IF NOT EXISTS idx_proxies_last_check
                ON proxies(last_check);
            """
        )

    @contextmanager
    def _connect(self):
        """Context manager for database connection."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def upsert(self, proxy: ProxyData) -> None:
        """Insert or update a single proxy."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO proxies (uuid, ip, port, type, status, last_check,
                                     last_working, latency_ms, failure_count,
                                     last_used, added_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(NULLIF(?, ''), datetime('now')), ?)
                ON CONFLICT (ip, port) DO UPDATE SET
                    uuid=excluded.uuid,
                    type=excluded.type,
                    status=excluded.status,
                    last_check=excluded.last_check,
                    last_working=excluded.last_working,
                    latency_ms=excluded.latency_ms,
                    failure_count=excluded.failure_count,
                    last_used=excluded.last_used,
                    source=excluded.source
                """,
                (
                    proxy.uuid,
                    proxy.ip,
                    proxy.port,
                    proxy.type.value,
                    proxy.status.value,
                    proxy.last_check,
                    proxy.last_working,
                    proxy.latency_ms,
                    proxy.failure_count,
                    proxy.last_used,
                    proxy.added_at,
                    proxy.source,
                ),
            )

    def bulk_upsert(self, proxies: list[ProxyData]) -> None:
        """Insert or update multiple proxies."""
        if not proxies:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO proxies (uuid, ip, port, type, status, last_check,
                                     last_working, latency_ms, failure_count,
                                     last_used, added_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(NULLIF(?, ''), datetime('now')), ?)
                ON CONFLICT (ip, port) DO UPDATE SET
                    uuid=excluded.uuid,
                    type=excluded.type,
                    status=excluded.status,
                    last_check=excluded.last_check,
                    last_working=excluded.last_working,
                    latency_ms=excluded.latency_ms,
                    failure_count=excluded.failure_count,
                    last_used=excluded.last_used,
                    source=excluded.source
                """,
                [
                    (
                        p.uuid,
                        p.ip,
                        p.port,
                        p.type.value,
                        p.status.value,
                        p.last_check,
                        p.last_working,
                        p.latency_ms,
                        p.failure_count,
                        p.last_used,
                        p.added_at,
                        p.source,
                    )
                    for p in proxies
                ],
            )

    def get_all(self) -> list[ProxyData]:
        """Get all proxies."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM proxies").fetchall()
            return [self._row_to_proxy(r) for r in rows]

    def get_active(self) -> list[ProxyData]:
        """Get active proxies only."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM proxies WHERE status = 'active'"
            ).fetchall()
            return [self._row_to_proxy(r) for r in rows]

    def get_by_status(self, status: ProxyStatus) -> list[ProxyData]:
        """Get proxies by status."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM proxies WHERE status = ?", (status.value,)
            ).fetchall()
            return [self._row_to_proxy(r) for r in rows]

    def get_by_uuid(self, proxy_uuid: str) -> ProxyData | None:
        """Get proxy by UUID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM proxies WHERE uuid = ?", (proxy_uuid,)
            ).fetchone()
            return self._row_to_proxy(row) if row else None

    def get_working(self, limit: int = 50) -> list[ProxyData]:
        """Get working proxies ordered by latency_ms asc (fastest first)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM proxies WHERE status = 'active' ORDER BY latency_ms ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_proxy(r) for r in rows]

    def mark_working(self, proxy: ProxyData) -> None:
        """Update last_working for a proxy."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE proxies SET last_working = ? WHERE ip = ? AND port = ?",
                (proxy.last_working, proxy.ip, proxy.port),
            )

    def update_last_used(self, proxy: ProxyData) -> None:
        """Update last_used for a proxy."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE proxies SET last_used = ? WHERE ip = ? AND port = ?",
                (proxy.last_used, proxy.ip, proxy.port),
            )

    def count(self) -> dict[str, int]:
        """Count proxies by status."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM proxies GROUP BY status"
            ).fetchall()
            return {row["status"]: row["cnt"] for row in rows}

    def count_checked(self) -> dict[str, int]:
        """Count proxies that have been checked (last_check > 0)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM proxies WHERE last_check > 0"
            ).fetchone()
            return {"checked": row["cnt"]}

    def get_avg_latency(self, status: str = "active") -> float:
        """Get average latency for proxies with given status."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT AVG(latency_ms) as avg_lat FROM proxies WHERE status = ? AND latency_ms > 0",
                (status,),
            ).fetchone()
            return row["avg_lat"] or 0.0

    def delete_dead(self) -> int:
        """Delete dead proxies. Returns count deleted."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM proxies WHERE status = 'dead' AND failure_count >= 10"
            )
            return cursor.rowcount

    @staticmethod
    def _row_to_proxy(row: sqlite3.Row) -> ProxyData:
        """Convert database row to ProxyData."""
        return ProxyData(
            uuid=row["uuid"],
            ip=row["ip"],
            port=row["port"],
            type=ProxyType(row["type"]),
            status=ProxyStatus(row["status"]),
            last_check=row["last_check"],
            last_working=row["last_working"],
            latency_ms=row["latency_ms"],
            failure_count=row["failure_count"],
            last_used=row["last_used"],
            added_at=row["added_at"],
            source=row["source"],
        )

    # ──────────────── Sources CRUD ────────────────

    def add_source(self, url: str, type_hint: str = "http") -> ProxySource:
        """Add a proxy source. Returns created ProxySource."""
        source_uuid = str(_uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO proxy_sources (uuid, url, type_hint)
                VALUES (?, ?, ?)
                """,
                (source_uuid, url, type_hint),
            )
        return ProxySource(uuid=source_uuid, url=url, type_hint=type_hint, enabled=True)

    def get_source(self, source_uuid: str) -> ProxySource | None:
        """Get source by UUID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM proxy_sources WHERE uuid = ?", (source_uuid,)
            ).fetchone()
            return self._row_to_source(row) if row else None

    def get_source_by_url(self, url: str) -> ProxySource | None:
        """Get source by URL."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM proxy_sources WHERE url = ?", (url,)
            ).fetchone()
            return self._row_to_source(row) if row else None

    def list_sources(self, enabled_only: bool = False) -> list[ProxySource]:
        """List all sources."""
        with self._connect() as conn:
            query = "SELECT * FROM proxy_sources"
            if enabled_only:
                query += " WHERE enabled = 1"
            query += " ORDER BY added_at DESC"
            rows = conn.execute(query).fetchall()
            return [self._row_to_source(r) for r in rows]

    def enable_source(self, source_uuid: str) -> bool:
        """Enable a source."""
        return self._update_source_field(source_uuid, "enabled", 1)

    def disable_source(self, source_uuid: str) -> bool:
        """Disable a source."""
        return self._update_source_field(source_uuid, "enabled", 0)

    def update_source_type(self, source_uuid: str, type_hint: str) -> bool:
        """Update source type hint."""
        return self._update_source_field(source_uuid, "type_hint", type_hint)

    def update_last_fetch(self, source_uuid: str) -> None:
        """Update last_fetch timestamp."""
        import time
        self._update_source_field(source_uuid, "last_fetch", time.time())

    def delete_source(self, source_uuid: str) -> bool:
        """Delete a source."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM proxy_sources WHERE uuid = ?", (source_uuid,)
            )
            return cursor.rowcount > 0

    def seed_sources(self, urls: list[tuple[str, str]]) -> int:
        """Seed sources from a list of (url, type_hint). Returns count added."""
        added = 0
        with self._connect() as conn:
            for url, type_hint in urls:
                existing = conn.execute(
                    "SELECT uuid FROM proxy_sources WHERE url = ?", (url,)
                ).fetchone()
                if not existing:
                    source_uuid = str(_uuid.uuid4())
                    conn.execute(
                        """
                        INSERT INTO proxy_sources (uuid, url, type_hint)
                        VALUES (?, ?, ?)
                        """,
                        (source_uuid, url, type_hint),
                    )
                    added += 1
        return added

    def _update_source_field(self, source_uuid: str, field: str, value) -> bool:
        """Update a single field of a source."""
        allowed = {"type_hint", "enabled", "last_fetch"}
        if field not in allowed:
            return False
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE proxy_sources SET {field} = ? WHERE uuid = ?",
                (value, source_uuid),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _row_to_source(row: sqlite3.Row) -> ProxySource:
        """Convert database row to ProxySource."""
        return ProxySource(
            uuid=row["uuid"],
            url=row["url"],
            type_hint=row["type_hint"],
            enabled=bool(row["enabled"]),
            last_fetch=row["last_fetch"],
            added_at=row["added_at"],
        )

    # ──────────────── Services CRUD ────────────────

    def create_service(self, name: str, url: str, **kwargs) -> ServiceData:
        """Create a new service."""
        service_uuid = str(_uuid.uuid4())
        headers = json.dumps(kwargs.pop("headers", {}))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO services (uuid, name, url, method, headers, body,
                    timeout, cache_ttl, auto_parse, rate_limit_rpm,
                    callback_url, proxy, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    service_uuid,
                    name,
                    url,
                    kwargs.get("method", "GET"),
                    headers,
                    kwargs.get("body", ""),
                    kwargs.get("timeout", 15.0),
                    kwargs.get("cache_ttl", 0),
                    int(kwargs.get("auto_parse", True)),
                    kwargs.get("rate_limit_rpm", 60),
                    kwargs.get("callback_url", ""),
                    int(kwargs.get("proxy", False)),
                    int(kwargs.get("enabled", True)),
                ),
            )
        return self.get_service(service_uuid)

    def get_service(self, service_uuid: str) -> ServiceData | None:
        """Get service by UUID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM services WHERE uuid = ?", (service_uuid,)
            ).fetchone()
            return self._row_to_service(row) if row else None

    def get_service_by_name(self, name: str) -> ServiceData | None:
        """Get service by unique name."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM services WHERE name = ?", (name,)
            ).fetchone()
            return self._row_to_service(row) if row else None

    def list_services(self, enabled_only: bool = False) -> list[ServiceData]:
        """List all services."""
        with self._connect() as conn:
            query = "SELECT * FROM services"
            if enabled_only:
                query += " WHERE enabled = 1"
            query += " ORDER BY name"
            rows = conn.execute(query).fetchall()
            return [self._row_to_service(r) for r in rows]

    def update_service(self, service_uuid: str, **kwargs) -> ServiceData | None:
        """Update service fields. Returns updated service or None."""
        allowed = {
            "name", "url", "method", "headers", "body", "timeout",
            "cache_ttl", "auto_parse", "rate_limit_rpm", "callback_url",
            "proxy", "enabled"
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return self.get_service(service_uuid)

        if "headers" in updates and isinstance(updates["headers"], dict):
            updates["headers"] = json.dumps(updates["headers"])

        for bool_field in ("auto_parse", "proxy", "enabled"):
            if bool_field in updates:
                updates[bool_field] = int(updates[bool_field])

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [service_uuid]

        with self._connect() as conn:
            conn.execute(
                f"UPDATE services SET {set_clause}, modified_at = datetime('now') WHERE uuid = ?",
                values,
            )
        return self.get_service(service_uuid)

    def delete_service(self, service_uuid: str) -> bool:
        """Delete a service."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM services WHERE uuid = ?", (service_uuid,)
            )
            return cursor.rowcount > 0

    def service_exists(self, name: str) -> bool:
        """Check if a service with this name exists."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM services WHERE name = ?", (name,)
            ).fetchone()
            return row is not None

    @staticmethod
    def _row_to_service(row: sqlite3.Row) -> ServiceData:
        """Convert database row to ServiceData."""
        return ServiceData(
            uuid=row["uuid"],
            name=row["name"],
            url=row["url"],
            method=row["method"],
            headers=json.loads(row["headers"]) if row["headers"] else {},
            body=row["body"],
            timeout=row["timeout"],
            cache_ttl=row["cache_ttl"],
            auto_parse=bool(row["auto_parse"]),
            rate_limit_rpm=row["rate_limit_rpm"],
            callback_url=row["callback_url"],
            proxy=bool(row["proxy"]),
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            modified_at=row["modified_at"],
        )
