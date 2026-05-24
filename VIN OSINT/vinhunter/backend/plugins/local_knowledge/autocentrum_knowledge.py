"""
autocentrum_knowledge — Local knowledge from autocentrum.pl (Hermes-scraped).

Queries the local PostgreSQL rag DB for editorial reviews and owner opinions
matching the decoded VIN. Zero cost, zero external requests.
"""
import os
import time

import psycopg2
import structlog

from plugins.base import PluginResult, SourceCategory, SourcePlugin, SourceStatus

logger = structlog.get_logger()

_DB_DSN = os.getenv(
    "AUTOCENTRUM_DB_DSN",
    "postgresql://rag:ragpass@host.docker.internal:5434/rag",
)


class AutocentrumKnowledgePlugin(SourcePlugin):
    name = "autocentrum_knowledge"
    display_name = "Autocentrum.pl (lokalna baza)"
    category = SourceCategory.LOCAL_KNOWLEDGE
    country = "PL"
    enabled = True

    async def search_by_vin(self, vin: str, **kwargs) -> PluginResult:
        start = time.monotonic()
        context: dict = kwargs.get("context", {})

        make: str = context.get("make", "")
        model: str = context.get("model", "")
        year: int = 0
        try:
            year = int(context.get("year", 0) or 0)
        except (ValueError, TypeError):
            pass

        if not make or not model:
            return self._make_no_data(int((time.monotonic() - start) * 1000))

        try:
            conn = psycopg2.connect(_DB_DSN, connect_timeout=5)
            cur = conn.cursor()

            # Find best matching model
            cur.execute(
                """
                SELECT id FROM autocentrum_models
                WHERE LOWER(make) = LOWER(%s)
                  AND LOWER(model) LIKE LOWER(%s)
                  AND (%s = 0 OR year_from IS NULL OR year_from <= %s)
                  AND (%s = 0 OR year_to IS NULL OR year_to >= %s)
                ORDER BY scraped_at DESC
                LIMIT 1
                """,
                (make, f"%{model.split()[0]}%", year, year, year, year),
            )
            row = cur.fetchone()
            if not row:
                cur.close()
                conn.close()
                return self._make_no_data(int((time.monotonic() - start) * 1000))

            model_id = row[0]

            # Editorial review (latest, first chunk only)
            cur.execute(
                """
                SELECT title, content, rating, url
                FROM autocentrum_reviews
                WHERE model_id = %s AND source = 'editorial'
                ORDER BY scraped_at DESC
                LIMIT 1
                """,
                (model_id,),
            )
            editorial = cur.fetchone()

            # Top owner opinions by rating
            cur.execute(
                """
                SELECT content, rating
                FROM autocentrum_reviews
                WHERE model_id = %s AND source = 'owner'
                ORDER BY rating DESC NULLS LAST
                LIMIT 3
                """,
                (model_id,),
            )
            opinions = cur.fetchall()

            cur.close()
            conn.close()

            if not editorial and not opinions:
                return self._make_no_data(int((time.monotonic() - start) * 1000))

            data: dict = {}

            if editorial:
                data["editorial"] = {
                    "title": editorial[0] or f"{make} {model} — test",
                    "summary": (editorial[1][:300] + "…") if len(editorial[1]) > 300 else editorial[1],
                    "rating": float(editorial[2]) if editorial[2] is not None else None,
                    "source_url": editorial[3],
                }

            if opinions:
                data["owner_opinions"] = [
                    {
                        "excerpt": (op[0][:200] + "…") if len(op[0]) > 200 else op[0],
                        "rating": float(op[1]) if op[1] is not None else None,
                    }
                    for op in opinions
                ]

            return PluginResult(
                source_name=self.name,
                category=self.category,
                status=SourceStatus.DONE,
                data=data,
                execution_time_ms=int((time.monotonic() - start) * 1000),
            )

        except psycopg2.OperationalError as exc:
            logger.warning("autocentrum_knowledge.db_unavailable", error=str(exc))
            return self._make_no_data(int((time.monotonic() - start) * 1000))
        except Exception as exc:
            return self._make_error(str(exc), int((time.monotonic() - start) * 1000))
