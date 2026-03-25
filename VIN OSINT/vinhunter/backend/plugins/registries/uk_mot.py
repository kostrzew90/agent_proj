"""
UK MOT History API — darmowe, oficjalne, wymaga klucza API (bezpłatna rejestracja).
Doskonałe dane: pełna historia MOT z przebiegami, usterkami, datami.
https://dvsa.api.gov.uk/v1/trade/vehicles/mot-tests?registration=<reg>
"""
import time
import httpx
import structlog
import os

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult

logger = structlog.get_logger()

MOT_API_URL = "https://history.mot.api.gov.uk/v1/trade/vehicles/registration/{plate}"


class UKMotPlugin(SourcePlugin):
    name = "uk_mot"
    display_name = "UK MOT History"
    category = SourceCategory.REGISTRY
    country = "GB"
    requires_captcha = False
    requires_login = False

    def __init__(self):
        self.api_key = os.environ.get("UK_MOT_API_KEY", "")

    async def search_by_vin(self, vin: str) -> PluginResult:
        # MOT API działa po tablicy, nie VIN — można też szukać po VIN przez endpoint
        return self._make_no_data()

    async def search_by_plate(self, plate: str, country: str) -> PluginResult:
        if country.upper() != "GB":
            return self._make_no_data()
        if not self.api_key:
            return self._make_error("Brak klucza UK_MOT_API_KEY w .env — zarejestruj się na https://dvsa.api.gov.uk/")

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    MOT_API_URL.format(plate=plate.upper().replace(" ", "")),
                    headers={"x-api-key": self.api_key, "Accept": "application/json+v6"},
                )

            if response.status_code == 404:
                return self._make_no_data(int((time.monotonic() - start) * 1000))
            response.raise_for_status()

            vehicle = response.json()
            mot_tests = vehicle.get("motTests", [])

            data = {
                "registration": vehicle.get("registration"),
                "make": vehicle.get("make"),
                "model": vehicle.get("model"),
                "colour": vehicle.get("primaryColour"),
                "fuel_type": vehicle.get("fuelType"),
                "mot_tests": mot_tests,
                "mot_count": len(mot_tests),
                "first_used_date": vehicle.get("firstUsedDate"),
                "engine_size": vehicle.get("engineSize"),
            }

            # Wyciągnij ostatni przebieg
            if mot_tests:
                last = mot_tests[0]
                data["last_mot_date"] = last.get("completedDate")
                data["last_mot_result"] = last.get("testResult")
                data["last_mot_mileage"] = last.get("odometerValue")

            elapsed = int((time.monotonic() - start) * 1000)
            logger.info("uk_mot.done", plate=plate, tests=len(mot_tests))
            return PluginResult(
                source_name=self.name,
                category=self.category,
                status=SourceStatus.DONE,
                data=data,
                execution_time_ms=elapsed,
            )

        except Exception as e:
            logger.error("uk_mot.error", plate=plate, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
