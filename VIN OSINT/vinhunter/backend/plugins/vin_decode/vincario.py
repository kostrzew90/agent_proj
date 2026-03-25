"""
Vincario API — profesjonalny VIN decoder z 99% pokryciem EU.
50+ pól: silnik, nadwozie, wyposazenie, historia.
Wymaga VINCARIO_API_KEY + VINCARIO_SECRET_KEY w .env ($0.25/decode).
"""
import time
import hashlib
import httpx
import structlog

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult
from core.config import settings

logger = structlog.get_logger()

API_URL = "https://api.vindecoder.eu/3.2/{api_key}/{control_sum}/decode/{vin}.json"


class VincarioPlugin(SourcePlugin):
    name = "vincario"
    display_name = "Vincario (EU decode)"
    category = SourceCategory.VIN_DECODE
    country = "EU"

    @property
    def enabled(self):
        return bool(settings.vincario_api_key and settings.vincario_secret_key)

    @enabled.setter
    def enabled(self, value):
        pass

    def _control_sum(self, vin: str) -> str:
        """SHA1(VIN|decode|apikey|secretkey) — required by Vincario auth."""
        raw = f"{vin}|decode|{settings.vincario_api_key}|{settings.vincario_secret_key}"
        return hashlib.sha1(raw.encode()).hexdigest()[:10]

    async def search_by_vin(self, vin: str) -> PluginResult:
        start = time.monotonic()

        if not settings.vincario_api_key or not settings.vincario_secret_key:
            return self._make_error("VINCARIO_API_KEY/SECRET not configured", 0)

        try:
            control = self._control_sum(vin)
            url = API_URL.format(
                api_key=settings.vincario_api_key,
                control_sum=control,
                vin=vin,
            )

            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(url)
                elapsed = int((time.monotonic() - start) * 1000)

                if r.status_code == 404:
                    return self._make_no_data(elapsed)

                if r.status_code in (401, 403):
                    return self._make_error("Invalid Vincario API credentials", elapsed)

                if r.status_code == 429:
                    return self._make_error("Vincario rate limit exceeded", elapsed)

                r.raise_for_status()
                result = r.json()

                if not result or isinstance(result, dict) and result.get("error"):
                    err = result.get("error", "Unknown error") if isinstance(result, dict) else "Empty response"
                    return self._make_error(str(err), elapsed)

                # Vincario returns flat dict with vehicle data
                data = {}
                if isinstance(result, dict):
                    raw = result
                elif isinstance(result, list) and result:
                    raw = result[0] if isinstance(result[0], dict) else {}
                else:
                    return self._make_no_data(elapsed)

                # Map known fields
                field_map = {
                    "Make": "make",
                    "Model": "model",
                    "ModelYear": "year",
                    "BodyStyle": "body",
                    "EngineDisplacement": "displacement",
                    "EnginePowerKW": "power_kw",
                    "EnginePowerHP": "power_hp",
                    "FuelType": "fuel",
                    "Transmission": "transmission",
                    "DriveType": "drivetrain",
                    "NumberOfDoors": "doors",
                    "NumberOfSeats": "seats",
                    "Weight": "weight_kg",
                    "MaxSpeed": "max_speed_kmh",
                    "CO2Emission": "co2_g_km",
                    "EngineCode": "engine_code",
                    "PlantCountry": "plant_country",
                    "ManufacturerAddress": "manufacturer_address",
                }

                for api_key, our_key in field_map.items():
                    val = raw.get(api_key)
                    if val is not None and val != "" and val != "N/A":
                        data[our_key] = val

                # Also include any extra fields not in our map
                for k, v in raw.items():
                    if v is not None and v != "" and v != "N/A":
                        clean_key = k.lower().replace(" ", "_")
                        if clean_key not in data:
                            data[clean_key] = v

                if not data:
                    return self._make_no_data(elapsed)

                logger.info("vincario.done", vin=vin, fields=len(data))
                return PluginResult(
                    source_name=self.name,
                    category=self.category,
                    status=SourceStatus.DONE,
                    data=data,
                    execution_time_ms=elapsed,
                )

        except httpx.TimeoutException:
            return self._make_error("Vincario API timeout", int((time.monotonic() - start) * 1000))
        except Exception as e:
            logger.error("vincario.error", vin=vin, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
