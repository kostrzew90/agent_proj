"""
RDW Open Data — Holandia.
Publiczne, darmowe, bez klucza API. Doskonałe dane dla aut z NL.
"""
import time
import httpx
import structlog

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult

logger = structlog.get_logger()

RDW_VEHICLE_URL = "https://opendata.rdw.nl/resource/m9d7-ebf2.json?kenteken={plate}"
RDW_FUEL_URL = "https://opendata.rdw.nl/resource/8ys7-d773.json?kenteken={plate}"


class NLRdwPlugin(SourcePlugin):
    name = "nl_rdw"
    display_name = "RDW Open Data (NL)"
    category = SourceCategory.REGISTRY
    country = "NL"
    requires_captcha = False
    requires_login = False

    async def search_by_vin(self, vin: str) -> PluginResult:
        return self._make_no_data()

    async def search_by_plate(self, plate: str, country: str) -> PluginResult:
        if country.upper() != "NL":
            return self._make_no_data()

        plate = plate.upper().replace("-", "").replace(" ", "")
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r1 = await client.get(RDW_VEHICLE_URL.format(plate=plate))
                r2 = await client.get(RDW_FUEL_URL.format(plate=plate))

            if r1.status_code != 200 or not r1.json():
                return self._make_no_data(int((time.monotonic() - start) * 1000))

            vehicle = r1.json()[0] if r1.json() else {}
            fuel = r2.json()[0] if r2.json() else {}

            data = {
                "registration": plate,
                "make": vehicle.get("merk"),
                "model": vehicle.get("handelsbenaming"),
                "colour": vehicle.get("eerste_kleur"),
                "first_registration": vehicle.get("datum_eerste_toelating"),
                "first_registration_nl": vehicle.get("datum_eerste_tenaamstelling_in_nederland"),
                "body_type": vehicle.get("inrichting"),
                "fuel_type": fuel.get("brandstof_omschrijving"),
                "engine_cc": fuel.get("cilinderinhoud"),
                "power_kw": fuel.get("nettomaximumvermogen"),
                "apk_expiry": vehicle.get("vervaldatum_apk"),
                "status": vehicle.get("voertuigsoort"),
                "mass_empty": vehicle.get("massa_ledig_voertuig"),
                "seats": vehicle.get("aantal_zitplaatsen"),
            }
            data = {k: v for k, v in data.items() if v}

            elapsed = int((time.monotonic() - start) * 1000)
            logger.info("nl_rdw.done", plate=plate)
            return PluginResult(
                source_name=self.name,
                category=self.category,
                status=SourceStatus.DONE,
                data=data,
                execution_time_ms=elapsed,
            )

        except Exception as e:
            logger.error("nl_rdw.error", plate=plate, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
