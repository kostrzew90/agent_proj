"""
AutoRef.eu — EU Vehicle Technical Data API.
Zwraca szczegoly techniczne: silnik, nadwozie, wymiary, waga, emisje.
Wymaga AUTOREF_API_KEY w .env (50 free/month).
"""
import time
import httpx
import structlog

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult
from core.config import settings

logger = structlog.get_logger()

API_BASE = "https://api.autoref.eu"


class AutoRefPlugin(SourcePlugin):
    name = "autoref"
    display_name = "AutoRef.eu (EU specs)"
    category = SourceCategory.VIN_DECODE
    country = "EU"

    @property
    def enabled(self):
        return bool(settings.autoref_api_key)

    @enabled.setter
    def enabled(self, value):
        # Allow registry to set, but actual state depends on API key
        pass

    async def search_by_vin(self, vin: str) -> PluginResult:
        start = time.monotonic()

        if not settings.autoref_api_key:
            return self._make_error("AUTOREF_API_KEY not configured", 0)

        try:
            headers = {"X-API-Key": settings.autoref_api_key}
            async with httpx.AsyncClient(timeout=15, headers=headers) as client:
                r = await client.get(f"{API_BASE}/vehicles/{vin}", params={"lang": "en"})

                elapsed = int((time.monotonic() - start) * 1000)

                if r.status_code == 404:
                    return self._make_no_data(elapsed)

                if r.status_code == 401:
                    return self._make_error("Invalid AUTOREF_API_KEY", elapsed)

                if r.status_code == 429:
                    return self._make_error("AutoRef rate limit / quota exceeded", elapsed)

                r.raise_for_status()
                result = r.json()

                if not result.get("success"):
                    return self._make_no_data(elapsed)

                raw = result.get("data", {})
                if not raw:
                    return self._make_no_data(elapsed)

                # Map to clean output
                data = {
                    "brand": raw.get("BRAND", ""),
                    "model": raw.get("MODEL", ""),
                    "brand_model": raw.get("BRAND_MODEL", ""),
                    "body": raw.get("BODY", ""),
                    "fuel": raw.get("FUEL", ""),
                    "gearbox": raw.get("GEARBOX", ""),
                    "drivetrain": raw.get("DRIVETRAIN", ""),
                    "displacement_cc": raw.get("DISPLACEMENT"),
                    "power_kw": raw.get("POWER_KW"),
                    "power_hp": raw.get("POWER_DIN"),
                    "seats": raw.get("SEATS"),
                    "doors": raw.get("DOORS"),
                    "length_mm": raw.get("LENGTH"),
                    "width_mm": raw.get("WIDTH"),
                    "height_mm": raw.get("HEIGHT"),
                    "wheelbase_mm": raw.get("WHEELBASE"),
                    "curb_weight_kg": raw.get("CURB_WEIGHT"),
                    "max_weight_kg": raw.get("MAX_AUTHORIZED_WEIGHT"),
                    "towable_weight_kg": raw.get("TOWABLE_WEIGHT"),
                    "category": raw.get("CATEGORY", ""),
                    "vehicle_type": raw.get("TYPE_VEHICLE", ""),
                    "first_circulation": raw.get("DATE_FIRST_CIRCULATION", ""),
                    "manufacture_date": raw.get("MANUFACTURE_DATE", ""),
                    "transmission": raw.get("TRANSMISSION", ""),
                    "suspension": raw.get("SUSPENSION", ""),
                    "brakes": raw.get("BRAKES", ""),
                    "steering": raw.get("STEERING_TYPE", ""),
                }

                # Remove None/empty values
                data = {k: v for k, v in data.items() if v is not None and v != ""}

                if not data:
                    return self._make_no_data(elapsed)

                logger.info("autoref.done", vin=vin, fields=len(data))
                return PluginResult(
                    source_name=self.name,
                    category=self.category,
                    status=SourceStatus.DONE,
                    data=data,
                    execution_time_ms=elapsed,
                )

        except httpx.TimeoutException:
            return self._make_error("AutoRef API timeout", int((time.monotonic() - start) * 1000))
        except Exception as e:
            logger.error("autoref.error", vin=vin, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
