"""SQLite-backed checkpoint store. Resumable, crash-safe."""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

TileStatus = Literal["pending", "in_flight", "done", "failed"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS job (
  config_hash   TEXT PRIMARY KEY,
  asset_id      TEXT NOT NULL,
  started_at    REAL NOT NULL,
  completed_at  REAL
);

CREATE TABLE IF NOT EXISTS tiles (
  id            TEXT PRIMARY KEY,
  status        TEXT NOT NULL,
  attempts      INTEGER DEFAULT 0,
  last_error    TEXT,
  output_path   TEXT,
  completed_at  REAL
);

CREATE INDEX IF NOT EXISTS ix_tiles_status ON tiles(status);
"""


class Checkpoint:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self):
        cur = self._conn.cursor()
        cur.execute("BEGIN")
        try:
            yield cur
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise

    # ── Job-level ────────────────────────────────────────────────────────────
    def init_job(self, config_hash: str, asset_id: str) -> None:
        with self._tx() as cur:
            cur.execute(
                "INSERT OR IGNORE INTO job (config_hash, asset_id, started_at) "
                "VALUES (?, ?, ?)",
                (config_hash, asset_id, time.time()),
            )

    def get_job(self) -> tuple[str, str] | None:
        row = self._conn.execute(
            "SELECT config_hash, asset_id FROM job LIMIT 1"
        ).fetchone()
        return (row[0], row[1]) if row else None

    def mark_job_complete(self) -> None:
        with self._tx() as cur:
            cur.execute("UPDATE job SET completed_at = ?", (time.time(),))

    # ── Tile-level ───────────────────────────────────────────────────────────
    def register_tiles(self, tile_ids: Iterable[str]) -> None:
        with self._tx() as cur:
            cur.executemany(
                "INSERT OR IGNORE INTO tiles (id, status) VALUES (?, 'pending')",
                [(tid,) for tid in tile_ids],
            )

    def claim(self, tile_id: str) -> bool:
        """Move pending → in_flight atomically. Returns False if not pending."""
        with self._tx() as cur:
            cur.execute(
                "UPDATE tiles SET status='in_flight', attempts = attempts + 1 "
                "WHERE id = ? AND status IN ('pending', 'failed')",
                (tile_id,),
            )
            return cur.rowcount > 0

    def mark_done(self, tile_id: str, output_path: str) -> None:
        """Call ONLY after os.rename to the final path returns successfully."""
        with self._tx() as cur:
            cur.execute(
                "UPDATE tiles SET status='done', output_path=?, completed_at=?, last_error=NULL "
                "WHERE id = ?",
                (output_path, time.time(), tile_id),
            )

    def mark_failed(self, tile_id: str, error: str) -> None:
        with self._tx() as cur:
            cur.execute(
                "UPDATE tiles SET status='failed', last_error=? WHERE id = ?",
                (error, tile_id),
            )

    def reset_to_pending(self, tile_id: str) -> None:
        with self._tx() as cur:
            cur.execute(
                "UPDATE tiles SET status='pending' WHERE id = ?",
                (tile_id,),
            )

    def status(self, tile_id: str) -> TileStatus | None:
        row = self._conn.execute(
            "SELECT status FROM tiles WHERE id = ?", (tile_id,)
        ).fetchone()
        return row[0] if row else None

    def pending_ids(self, include_failed: bool = False) -> list[str]:
        statuses = ("pending", "failed") if include_failed else ("pending",)
        placeholders = ",".join("?" * len(statuses))
        rows = self._conn.execute(
            f"SELECT id FROM tiles WHERE status IN ({placeholders})", statuses
        ).fetchall()
        return [r[0] for r in rows]

    def counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) FROM tiles GROUP BY status"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def in_flight_ids(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT id, output_path FROM tiles WHERE status = 'in_flight'"
        ).fetchall()
        return [r[0] for r in rows]

    def recover_from_crash(self, output_root: Path) -> None:
        """On startup: reset all in_flight → pending and delete any stale tmp/output."""
        rows = self._conn.execute(
            "SELECT id, output_path FROM tiles WHERE status = 'in_flight'"
        ).fetchall()
        for tile_id, output_path in rows:
            if output_path:
                final = Path(output_path)
                tmp = final.with_suffix(final.suffix + ".tmp")
                for p in (tmp, final):
                    try:
                        p.unlink(missing_ok=True)
                    except OSError as exc:
                        log.warning("could not remove %s: %s", p, exc)
            log.info("recovered crashed tile %s -> pending", tile_id)
        with self._tx() as cur:
            cur.execute("UPDATE tiles SET status='pending' WHERE status='in_flight'")
