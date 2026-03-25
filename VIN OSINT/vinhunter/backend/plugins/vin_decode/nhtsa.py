"""
NHTSA vPIC API — darmowe, oficjalne, bez kluczy API.
Najlepsza baza VIN decode dla aut sprzedawanych w USA, działa też dla wielu EU aut.
https://vpic.nhtsa.dot.gov/api/
"""
import time
import httpx
import structlog

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult

logger = structlog.get_logger()

NHTSA_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinExtended/{vin}?format=json"


class NHTSAPlugin(SourcePlugin):
    name = "nhtsa"
    display_name = "NHTSA vPIC (USA)"
    category = SourceCategory.VIN_DECODE
    country = "US"
    requires_captcha = False
    requires_login = False

    async def search_by_vin(self, vin: str) -> PluginResult:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(NHTSA_URL.format(vin=vin))
                response.raise_for_status()
                json_data = response.json()

            results = json_data.get("Results", [])
            if not results:
                return self._make_no_data(int((time.monotonic() - start) * 1000))

            # Zamień listę {Variable, Value} na słownik
            decoded = {r["Variable"]: r["Value"] for r in results if r.get("Value") and r["Value"] != "Not Applicable"}

            # Wyciągamy WSZYSTKO co NHTSA zwróciło (nie tylko wybrane pola)
            SKIP_FIELDS = {
                "Error Code", "Error Text", "Additional Error Text",
                "Suggested VIN", "Vehicle Descriptor",
                "Possible Values", "Note",
            }
            SKIP_VALUES = {"Not Applicable", "", "0", "0.0"}

            data = {}
            for r in results:
                var = r.get("Variable", "")
                val = r.get("Value")
                if var and val and val not in SKIP_VALUES and var not in SKIP_FIELDS:
                    # Ustandaryzuj klucz
                    key = var.lower().replace(" ", "_").replace("-", "_").replace("(", "").replace(")", "")
                    data[key] = val

            # Sprawdź czy NHTSA cokolwiek zwróciło sensownego
            if not any([data.get("make"), data.get("manufacturer_name"), data.get("vehicle_type")]):
                return self._make_no_data(int((time.monotonic() - start) * 1000))

            elapsed = int((time.monotonic() - start) * 1000)
            logger.info("nhtsa.done", vin=vin, make=data.get("make"), model=data.get("model"))
            return PluginResult(
                source_name=self.name,
                category=self.category,
                status=SourceStatus.DONE,
                data=data,
                execution_time_ms=elapsed,
            )

        except httpx.TimeoutException:
            return self._make_error("NHTSA API timeout", int((time.monotonic() - start) * 1000))
        except Exception as e:
            logger.error("nhtsa.error", vin=vin, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
