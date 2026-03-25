import asyncpg
from typing import Optional
import structlog
import json
from datetime import datetime

from core.config import settings

logger = structlog.get_logger()


class Database:
    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        # asyncpg doesn't use SQLAlchemy URL format — strip the driver prefix
        url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        self._pool = await asyncpg.create_pool(url, min_size=2, max_size=10)
        logger.info("database.connected")

    async def disconnect(self):
        if self._pool:
            await self._pool.close()
            logger.info("database.disconnected")

    @property
    def pool(self) -> asyncpg.Pool:
        if not self._pool:
            raise RuntimeError("Database not connected")
        return self._pool

    # --- Scans ---

    async def create_scan(self, vin: str, plate: Optional[str] = None) -> str:
        row = await self.pool.fetchrow(
            "INSERT INTO scans (vin, plate) VALUES ($1, $2) RETURNING id::text",
            vin, plate
        )
        return row["id"]

    async def get_scan(self, scan_id: str) -> Optional[dict]:
        row = await self.pool.fetchrow(
            "SELECT * FROM scans WHERE id = $1::uuid", scan_id
        )
        return dict(row) if row else None

    async def update_scan_status(self, scan_id: str, status: str, decoded_data: Optional[dict] = None):
        # Tylko ustawiaj completed_at gdy skan naprawde sie zakonczyl
        set_completed = status not in ("running", "pending")
        if decoded_data and set_completed:
            await self.pool.execute(
                """UPDATE scans SET status=$1, completed_at=NOW(), decoded_data=$2
                   WHERE id=$3::uuid""",
                status, json.dumps(decoded_data), scan_id
            )
        elif decoded_data:
            await self.pool.execute(
                """UPDATE scans SET status=$1, decoded_data=$2
                   WHERE id=$3::uuid""",
                status, json.dumps(decoded_data), scan_id
            )
        elif set_completed:
            await self.pool.execute(
                "UPDATE scans SET status=$1, completed_at=NOW() WHERE id=$2::uuid",
                status, scan_id
            )
        else:
            await self.pool.execute(
                "UPDATE scans SET status=$1 WHERE id=$2::uuid",
                status, scan_id
            )

    async def list_scans(self, limit: int = 50) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT id::text, vin, plate, status, created_at, completed_at FROM scans ORDER BY created_at DESC LIMIT $1",
            limit
        )
        return [dict(r) for r in rows]

    async def delete_scan(self, scan_id: str):
        await self.pool.execute("DELETE FROM scans WHERE id=$1::uuid", scan_id)

    # --- Scan Results ---

    async def save_scan_result(self, scan_id: str, result) -> str:
        row = await self.pool.fetchrow(
            """INSERT INTO scan_results
               (scan_id, source_name, category, status, data, raw_html, screenshots, error_message, execution_time_ms)
               VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9)
               RETURNING id::text""",
            scan_id,
            result.source_name,
            result.category.value,
            result.status.value,
            json.dumps(result.data) if result.data else None,
            result.raw_html,
            result.screenshots,
            result.error_message,
            result.execution_time_ms,
        )
        return row["id"]

    async def get_scan_results(self, scan_id: str) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT * FROM scan_results WHERE scan_id=$1::uuid ORDER BY created_at",
            scan_id
        )
        return [dict(r) for r in rows]

    # --- Photos ---

    async def save_photo(self, scan_id: str, source_name: str, url: str,
                         thumbnail_url: Optional[str] = None,
                         context: Optional[str] = None,
                         relevance_score: Optional[float] = None) -> str:
        row = await self.pool.fetchrow(
            """INSERT INTO found_photos (scan_id, source_name, url, thumbnail_url, context, relevance_score)
               VALUES ($1::uuid, $2, $3, $4, $5, $6)
               RETURNING id::text""",
            scan_id, source_name, url, thumbnail_url, context, relevance_score
        )
        return row["id"]

    async def get_photos(self, scan_id: str) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT * FROM found_photos WHERE scan_id=$1::uuid ORDER BY relevance_score DESC NULLS LAST",
            scan_id
        )
        return [dict(r) for r in rows]

    # --- Reports ---

    async def save_report(self, scan_id: str, format: str, file_path: str, file_size: int) -> str:
        row = await self.pool.fetchrow(
            """INSERT INTO reports (scan_id, format, file_path, file_size_bytes)
               VALUES ($1::uuid, $2, $3, $4)
               RETURNING id::text""",
            scan_id, format, file_path, file_size
        )
        return row["id"]

    async def list_reports(self) -> list[dict]:
        rows = await self.pool.fetch(
            """SELECT r.id::text, r.scan_id::text, r.format, r.file_path, r.file_size_bytes, r.created_at,
                      s.vin, s.plate
               FROM reports r JOIN scans s ON s.id = r.scan_id
               ORDER BY r.created_at DESC""",
        )
        return [dict(r) for r in rows]

    async def get_report(self, report_id: str) -> Optional[dict]:
        row = await self.pool.fetchrow(
            "SELECT * FROM reports WHERE id=$1::uuid", report_id
        )
        return dict(row) if row else None

    # --- Plugin Config ---

    async def get_plugin_configs(self) -> list[dict]:
        rows = await self.pool.fetch("SELECT * FROM plugin_config")
        return [dict(r) for r in rows]

    async def upsert_plugin_config(self, name: str, enabled: bool, settings_json: dict):
        await self.pool.execute(
            """INSERT INTO plugin_config (name, enabled, settings)
               VALUES ($1, $2, $3)
               ON CONFLICT (name) DO UPDATE SET enabled=$2, settings=$3""",
            name, enabled, json.dumps(settings_json)
        )

    async def increment_plugin_stats(self, name: str, error: bool = False):
        if error:
            await self.pool.execute(
                """INSERT INTO plugin_config (name, total_queries, total_errors, last_used)
                   VALUES ($1, 1, 1, NOW())
                   ON CONFLICT (name) DO UPDATE SET
                     total_queries = plugin_config.total_queries + 1,
                     total_errors = plugin_config.total_errors + 1,
                     last_used = NOW()""",
                name
            )
        else:
            await self.pool.execute(
                """INSERT INTO plugin_config (name, total_queries, last_used)
                   VALUES ($1, 1, NOW())
                   ON CONFLICT (name) DO UPDATE SET
                     total_queries = plugin_config.total_queries + 1,
                     last_used = NOW()""",
                name
            )


db = Database()
