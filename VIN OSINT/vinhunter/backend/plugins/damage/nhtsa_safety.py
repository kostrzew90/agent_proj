"""
NHTSA Safety Ratings (NCAP) — darmowe, oficjalne, bez klucza API.
Zwraca gwiazdki crash-testow (1-5): frontal, side, rollover, pole.
2-krokowe: decode VIN -> make/model/year, potem szukaj VehicleId -> ratings.
"""
import time
import httpx
import structlog

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult

logger = structlog.get_logger()

DECODE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
SAFETY_SEARCH_URL = "https://api.nhtsa.gov/SafetyRatings/modelyear/{year}/make/{make}/model/{model}?format=json"
SAFETY_VEHICLE_URL = "https://api.nhtsa.gov/SafetyRatings/VehicleId/{vehicle_id}?format=json"


class NHTSASafetyPlugin(SourcePlugin):
    name = "nhtsa_safety"
    display_name = "NHTSA Safety Ratings (USA)"
    category = SourceCategory.DAMAGE
    country = "US"

    async def search_by_vin(self, vin: str) -> PluginResult:
        start = time.monotonic()
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            async with httpx.AsyncClient(timeout=15, headers=headers) as client:
                # Step 1: decode VIN -> make, model, year
                r = await client.get(DECODE_URL.format(vin=vin))
                r.raise_for_status()
                decoded = r.json().get("Results", [{}])[0]

                make = decoded.get("Make", "")
                model = decoded.get("Model", "")
                year = decoded.get("ModelYear", "")

                if not make or not model or not year:
                    return self._make_no_data(int((time.monotonic() - start) * 1000))

                # Step 2: search for VehicleId by year/make/model
                search_url = SAFETY_SEARCH_URL.format(year=year, make=make, model=model)
                r2 = await client.get(search_url)
                r2.raise_for_status()
                search_data = r2.json()

                vehicles = search_data.get("Results", [])
                if not vehicles:
                    return self._make_no_data(int((time.monotonic() - start) * 1000))

                # Step 3: get ratings for first VehicleId (best match)
                vehicle_id = vehicles[0].get("VehicleId")
                if not vehicle_id:
                    return self._make_no_data(int((time.monotonic() - start) * 1000))

                r3 = await client.get(SAFETY_VEHICLE_URL.format(vehicle_id=vehicle_id))
                r3.raise_for_status()
                rating_data = r3.json()

                ratings = rating_data.get("Results", [{}])[0]

                # Extract key fields
                data = {
                    "make": make,
                    "model": model,
                    "year": year,
                    "vehicle_description": ratings.get("VehicleDescription", ""),
                    "vehicle_picture": ratings.get("VehiclePicture", ""),
                    "overall_rating": ratings.get("OverallRating", "Not Rated"),
                    "frontal_crash_rating": ratings.get("OverallFrontCrashRating", "Not Rated"),
                    "frontal_crash_driver": ratings.get("FrontCrashDriversideRating", "Not Rated"),
                    "frontal_crash_passenger": ratings.get("FrontCrashPassengersideRating", "Not Rated"),
                    "side_crash_rating": ratings.get("OverallSideCrashRating", "Not Rated"),
                    "side_crash_driver": ratings.get("SideCrashDriversideRating", "Not Rated"),
                    "side_crash_passenger": ratings.get("SideCrashPassengersideRating", "Not Rated"),
                    "side_pole_rating": ratings.get("SidePoleCrashRating", "Not Rated"),
                    "rollover_rating": ratings.get("RolloverRating", "Not Rated"),
                    "rollover_probability": ratings.get("RolloverPossibility", None),
                    "complaints_count": ratings.get("ComplaintsCount", 0),
                    "recalls_count": ratings.get("RecallsCount", 0),
                    "investigation_count": ratings.get("InvestigationCount", 0),
                    "nhtsa_electronic_stability_control": ratings.get("NHTSAElectronicStabilityControl", ""),
                    "nhtsa_forward_collision_warning": ratings.get("NHTSAForwardCollisionWarning", ""),
                    "nhtsa_lane_departure_warning": ratings.get("NHTSALaneDepartureWarning", ""),
                    # All available variants for this year/make/model
                    "all_variants": [
                        {"description": v.get("VehicleDescription", ""), "vehicle_id": v.get("VehicleId")}
                        for v in vehicles
                    ],
                }

                elapsed = int((time.monotonic() - start) * 1000)
                logger.info("nhtsa_safety.done", vin=vin, overall=data["overall_rating"])
                return PluginResult(
                    source_name=self.name,
                    category=self.category,
                    status=SourceStatus.DONE,
                    data=data,
                    execution_time_ms=elapsed,
                )

        except httpx.TimeoutException:
            return self._make_error("NHTSA Safety Ratings API timeout", int((time.monotonic() - start) * 1000))
        except Exception as e:
            logger.error("nhtsa_safety.error", vin=vin, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
