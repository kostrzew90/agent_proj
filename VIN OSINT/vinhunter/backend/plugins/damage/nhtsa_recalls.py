"""
NHTSA Recalls API — darmowe, oficjalne, bez klucza API.
Szuka recall kampanii po make/model/year (dekodowanych z VIN).
"""
import time
import httpx
import structlog

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult

logger = structlog.get_logger()

DECODE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
RECALLS_URL = "https://api.nhtsa.gov/recalls/recallsByVehicle"


class NHTSARecallsPlugin(SourcePlugin):
    name = "nhtsa_recalls"
    display_name = "NHTSA Recalls (USA)"
    category = SourceCategory.DAMAGE
    country = "US"

    async def search_by_vin(self, vin: str) -> PluginResult:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Krok 1: szybki decode VIN -> make, model, year
                r = await client.get(DECODE_URL.format(vin=vin))
                r.raise_for_status()
                decoded = r.json().get("Results", [{}])[0]

                make = decoded.get("Make", "")
                model = decoded.get("Model", "")
                year = decoded.get("ModelYear", "")

                if not make or not model or not year:
                    return self._make_no_data(int((time.monotonic() - start) * 1000))

                # Krok 2: query recalls
                params = {"make": make, "model": model, "modelYear": year}
                r2 = await client.get(RECALLS_URL, params=params)
                r2.raise_for_status()
                recalls_data = r2.json()

                results = recalls_data.get("results", [])
                if not results:
                    return self._make_no_data(int((time.monotonic() - start) * 1000))

                # Wyciagnij istotne pola
                recalls = []
                for item in results:
                    recall = {
                        "campaign_number": item.get("NHTSACampaignNumber", ""),
                        "component": item.get("Component", ""),
                        "summary": item.get("Summary", ""),
                        "consequence": item.get("Consequence", ""),
                        "remedy": item.get("Remedy", ""),
                        "report_date": item.get("ReportReceivedDate", ""),
                    }
                    recalls.append(recall)

                data = {
                    "make": make,
                    "model": model,
                    "year": year,
                    "total_recalls": len(recalls),
                    "recalls": recalls,
                }

                elapsed = int((time.monotonic() - start) * 1000)
                logger.info("nhtsa_recalls.done", vin=vin, recalls=len(recalls))
                return PluginResult(
                    source_name=self.name,
                    category=self.category,
                    status=SourceStatus.DONE,
                    data=data,
                    execution_time_ms=elapsed,
                )

        except httpx.TimeoutException:
            return self._make_error("NHTSA Recalls API timeout", int((time.monotonic() - start) * 1000))
        except Exception as e:
            logger.error("nhtsa_recalls.error", vin=vin, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
