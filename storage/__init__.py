"""SQLite storage for proxies."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from hime.proxy import ProxyData, ProxyType, ProxyStatus


class ProxyStore:
    """SQLite storage for proxy list."""

    def __init__(self, db_path: str = "data/proxies.db"):
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS proxies (
                    ip           TEXT    NOT NULL,
                    port         INTEGER NOT NULL,
                    type         TEXT    NOT NULL DEFAULT 'http',
                    status       TEXT    NOT NULL DEFAULT 'unknown',
                    last_check   REAL    DEFAULT 0,
                    response_time REAL   DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    last_used    REAL    DEFAULT 0,
                    created_at   TEXT    DEFAULT (datetime('now')),
                    updated_at   TEXT    DEFAULT (datetime('now')),
                    PRIMARY KEY (ip, port)
                );

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
                INSERT INTO proxies (ip, port, type, status, last_check,
                                     response_time, failure_count, last_used, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT (ip, port) DO UPDATE SET
                    type=excluded.type,
                    status=excluded.status,
                    last_check=excluded.last_check,
                    response_time=excluded.response_time,
                    failure_count=excluded.failure_count,
                    last_used=excluded.last_used,
                    updated_at=datetime('now')
                """,
                (
                    proxy.ip,
                    proxy.port,
                    proxy.type.value,
                    proxy.status.value,
                    proxy.last_check,
                    proxy.response_time,
                    proxy.failure_count,
                    proxy.last_used,
                ),
            )

    def bulk_upsert(self, proxies: list[ProxyData]) -> None:
        """Insert or update multiple proxies."""
        if not proxies:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO proxies (ip, port, type, status, last_check,
                                     response_time, failure_count, last_used, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT (ip, port) DO UPDATE SET
                    type=excluded.type,
                    status=excluded.status,
                    last_check=excluded.last_check,
                    response_time=excluded.response_time,
                    failure_count=excluded.failure_count,
                    last_used=excluded.last_used,
                    updated_at=datetime('now')
                """,
                [
                    (
                        p.ip,
                        p.port,
                        p.type.value,
                        p.status.value,
                        p.last_check,
                        p.response_time,
                        p.failure_count,
                        p.last_used,
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

    def count(self) -> dict[str, int]:
        """Count proxies by status."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM proxies GROUP BY status"
            ).fetchall()
            return {row["status"]: row["cnt"] for row in rows}

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
            ip=row["ip"],
            port=row["port"],
            type=ProxyType(row["type"]),
            status=ProxyStatus(row["status"]),
            last_check=row["last_check"],
            response_time=row["response_time"],
            failure_count=row["failure_count"],
            last_used=row["last_used"],
        )
