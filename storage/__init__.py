"""SQLite storage for proxies."""

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from hime.proxy import ProxyData, ProxyType, ProxyStatus


class ProxyStore:
    """SQLite storage for proxy list."""

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
