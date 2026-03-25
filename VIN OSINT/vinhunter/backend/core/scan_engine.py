import asyncio
import re
from datetime import datetime
from typing import Optional
import structlog

from plugins.base import SourceCategory, SourceStatus
from plugins.registry import PluginRegistry
from core.database import Database
from api.websocket import WebSocketManager

logger = structlog.get_logger()


class ScanEngine:
    def __init__(self, registry: PluginRegistry, db: Database, ws: WebSocketManager):
        self.registry = registry
        self.db = db
        self.ws = ws

    async def run_scan(self, scan_id: str, vin: str, plate: Optional[str] = None):
        logger.info("scan.started", scan_id=scan_id, vin=vin)
        plugins = self.registry.get_enabled()

        # Faza 1: VIN decode (musi być pierwszy)
        decode_plugins = [p for p in plugins if p.category == SourceCategory.VIN_DECODE]
        decode_results = await asyncio.gather(
            *[self._run_plugin(scan_id, p, vin, plate) for p in decode_plugins],
            return_exceptions=True
        )
        decoded_info = self._merge_vin_data(decode_results)

        if decoded_info:
            await self.db.update_scan_status(scan_id, "running", decoded_info)

        # Faza 2: Wszystko inne równolegle (z kontekstem decoded_info)
        other_plugins = [p for p in plugins if p.category != SourceCategory.VIN_DECODE]

        # Ograniczenie concurrent Playwright (max 3 na raz)
        semaphore = asyncio.Semaphore(3)

        async def run_with_sem(plugin):
            async with semaphore:
                return await self._run_plugin(scan_id, plugin, vin, plate, context=decoded_info)

        await asyncio.gather(
            *[run_with_sem(p) for p in other_plugins],
            return_exceptions=True
        )

        # Finalny status
        results = await self.db.get_scan_results(scan_id)
        errors = sum(1 for r in results if r["status"] == "error")
        status = "done_with_errors" if errors > 0 else "completed"

        await self.db.update_scan_status(scan_id, status, decoded_info)
        await self.ws.broadcast(scan_id, {
            "type": "scan_complete",
            "total_sources": len(results),
            "successful": sum(1 for r in results if r["status"] == "done"),
            "errors": errors,
            "no_data": sum(1 for r in results if r["status"] == "no_data"),
        })
        logger.info("scan.completed", scan_id=scan_id, status=status)

    async def _run_plugin(self, scan_id: str, plugin, vin: str, plate: Optional[str], context: Optional[dict] = None):
        await self.ws.broadcast(scan_id, {
            "type": "source_update",
            "source": plugin.name,
            "display_name": plugin.display_name,
            "status": "running",
        })

        start = datetime.utcnow()
        try:
            # Registry plugins: prefer plate search when plate is available
            if plate and plugin.category == SourceCategory.REGISTRY:
                # Detect country from plate (basic heuristic)
                country = self._detect_plate_country(plate)
                try:
                    result = await asyncio.wait_for(
                        plugin.search_by_plate(plate, country, vin=vin),
                        timeout=300  # pl_historia brute-force needs up to 5 min
                    )
                except (NotImplementedError, TypeError):
                    # Fallback: try with just plate+country, then vin
                    try:
                        result = await asyncio.wait_for(
                            plugin.search_by_plate(plate, country),
                            timeout=300
                        )
                    except NotImplementedError:
                        result = await asyncio.wait_for(
                            self._search_by_vin_safe(plugin, vin, context),
                            timeout=30
                        )
            else:
                result = await asyncio.wait_for(
                    self._search_by_vin_safe(plugin, vin, context),
                    timeout=30
                )

            # Obsługa CAPTCHA
            if result.status == SourceStatus.CAPTCHA_REQUIRED:
                await self.ws.broadcast(scan_id, {
                    "type": "captcha_request",
                    "source": plugin.name,
                    "captcha_image_base64": result.data.get("captcha_image_base64", ""),
                    "timeout_seconds": 120,
                })
                captcha_answer = await self.ws.wait_for_captcha(scan_id, plugin.name, timeout=120)
                if captcha_answer is None:
                    result.status = SourceStatus.CAPTCHA_TIMEOUT
                    result.error_message = "Użytkownik nie rozwiązał CAPTCHA w czasie"
                else:
                    result = await plugin.submit_captcha(vin, captcha_answer)

            elapsed = int((datetime.utcnow() - start).total_seconds() * 1000)
            result.execution_time_ms = elapsed

            await self.db.save_scan_result(scan_id, result)
            await self.db.increment_plugin_stats(plugin.name, error=(result.status == SourceStatus.ERROR))

            await self.ws.broadcast(scan_id, {
                "type": "source_update",
                "source": plugin.name,
                "display_name": plugin.display_name,
                "status": result.status.value,
                "data": result.data,
                "execution_time_ms": result.execution_time_ms,
            })
            return result

        except asyncio.TimeoutError:
            elapsed = int((datetime.utcnow() - start).total_seconds() * 1000)
            logger.warning("plugin.timeout", plugin=plugin.name)
            await self.ws.broadcast(scan_id, {
                "type": "source_update",
                "source": plugin.name,
                "display_name": plugin.display_name,
                "status": "error",
                "error": "Plugin timeout (30s)",
                "execution_time_ms": elapsed,
            })
        except Exception as e:
            elapsed = int((datetime.utcnow() - start).total_seconds() * 1000)
            logger.error("plugin.error", plugin=plugin.name, error=str(e))
            await self.ws.broadcast(scan_id, {
                "type": "source_update",
                "source": plugin.name,
                "display_name": plugin.display_name,
                "status": "error",
                "error": str(e),
                "execution_time_ms": elapsed,
            })

    @staticmethod
    async def _search_by_vin_safe(plugin, vin: str, context: dict | None):
        """Call search_by_vin with context kwarg, fallback without it for old plugins."""
        try:
            return await plugin.search_by_vin(vin, context=context or {})
        except TypeError:
            return await plugin.search_by_vin(vin)

    def _merge_vin_data(self, results) -> dict:
        """Merguj dane z VIN decode z priorytetami: nhtsa > manufacturer > vininfo_local."""
        priority = ["nhtsa", "manufacturer", "vininfo_local"]
        merged = {}

        ordered = []
        for name in priority:
            for r in results:
                if not isinstance(r, Exception) and hasattr(r, 'source_name') and r.source_name == name:
                    ordered.append(r)
        # Dołącz pozostałe
        for r in results:
            if not isinstance(r, Exception) and hasattr(r, 'source_name'):
                if r.source_name not in priority:
                    ordered.append(r)

        for result in ordered:
            if isinstance(result, Exception):
                continue
            if result.status.value != "done":
                continue
            for key, value in result.data.items():
                if key not in merged and value:
                    merged[key] = value

        return merged

    @staticmethod
    def _detect_plate_country(plate: str) -> str:
        """Detect country from license plate format (basic heuristic)."""
        p = plate.upper().replace(" ", "").replace("-", "")
        # Polish plates: 2-3 letter region code + 4-5 alphanumeric
        # e.g. WPI91008, KR12345, GDA1234
        if re.match(r'^[A-Z]{2,3}\d{4,5}[A-Z]?$', p) or re.match(r'^[A-Z]{2,3}[A-Z0-9]{4,5}$', p):
            return "PL"
        # Dutch: XX-999-X or similar with dashes
        if re.match(r'^[A-Z0-9]{1,3}[A-Z0-9]{1,3}[A-Z0-9]{1,2}$', p) and len(p) == 6:
            return "NL"
        # UK: XX99 XXX
        if re.match(r'^[A-Z]{2}\d{2}[A-Z]{3}$', p):
            return "GB"
        # German: X-XX-9999 or XXX-XX-9999
        if re.match(r'^[A-Z]{1,3}[A-Z]{1,2}\d{1,4}[EH]?$', p):
            return "DE"
        return "XX"
