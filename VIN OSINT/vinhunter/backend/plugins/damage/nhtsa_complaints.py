"""
NHTSA Complaints API — darmowe, oficjalne, bez klucza API.
Szuka skarg konsumenckich po make/model/year (dekodowanych z VIN).
"""
import time
import httpx
import structlog

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult

logger = structlog.get_logger()

DECODE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
COMPLAINTS_URL = "https://api.nhtsa.gov/complaints/complaintsByVehicle"


class NHTSAComplaintsPlugin(SourcePlugin):
    name = "nhtsa_complaints"
    display_name = "NHTSA Complaints (USA)"
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

                # Krok 2: query complaints
                params = {"make": make, "model": model, "modelYear": year}
                r2 = await client.get(COMPLAINTS_URL, params=params)
                r2.raise_for_status()
                complaints_data = r2.json()

                results = complaints_data.get("results", [])
                if not results:
                    return self._make_no_data(int((time.monotonic() - start) * 1000))

                # Agregacja po komponentach (bo moze byc 200+ skarg)
                components = {}
                for item in results:
                    comp = item.get("components", "Unknown")
                    if comp not in components:
                        components[comp] = {"count": 0, "crashes": 0, "injuries": 0, "samples": []}
                    components[comp]["count"] += 1
                    crash_val = item.get("crash", "")
                    if crash_val is True or str(crash_val).upper() == "Y":
                        components[comp]["crashes"] += 1
                    injuries_val = item.get("injuries", 0)
                    if injuries_val:
                        try:
                            components[comp]["injuries"] += int(injuries_val)
                        except (ValueError, TypeError):
                            pass
                    # Zachowaj max 3 opisy na komponent
                    if len(components[comp]["samples"]) < 3:
                        summary = item.get("summary", "")
                        if summary:
                            components[comp]["samples"].append(summary[:300])

                # Sortuj po ilosci skarg
                sorted_components = sorted(components.items(), key=lambda x: x[1]["count"], reverse=True)

                data = {
                    "make": make,
                    "model": model,
                    "year": year,
                    "total_complaints": len(results),
                    "total_crashes": sum(c["crashes"] for _, c in sorted_components),
                    "total_injuries": sum(c["injuries"] for _, c in sorted_components),
                    "by_component": [
                        {
                            "component": comp,
                            "count": info["count"],
                            "crashes": info["crashes"],
                            "injuries": info["injuries"],
                            "sample_descriptions": info["samples"],
                        }
                        for comp, info in sorted_components[:15]
                    ],
                }

                elapsed = int((time.monotonic() - start) * 1000)
                logger.info("nhtsa_complaints.done", vin=vin, total=len(results), components=len(components))
                return PluginResult(
                    source_name=self.name,
                    category=self.category,
                    status=SourceStatus.DONE,
                    data=data,
                    execution_time_ms=elapsed,
                )

        except httpx.TimeoutException:
            return self._make_error("NHTSA Complaints API timeout", int((time.monotonic() - start) * 1000))
        except Exception as e:
            logger.error("nhtsa_complaints.error", vin=vin, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
