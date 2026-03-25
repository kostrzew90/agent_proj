"""
Offline VIN decode z biblioteki vininfo.
Szybkie, bez sieci, ograniczone dla starszych / rzadszych modeli.
"""
import time
import structlog

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult
from core.vin_decoder import decode_vin_basic

logger = structlog.get_logger()


class VininfoLocalPlugin(SourcePlugin):
    name = "vininfo_local"
    display_name = "Offline VIN Decoder"
    category = SourceCategory.VIN_DECODE
    country = "XX"
    requires_captcha = False
    requires_login = False

    async def search_by_vin(self, vin: str) -> PluginResult:
        start = time.monotonic()
        try:
            from vininfo import Vin
            v = Vin(vin)
            brand = v.brand

            data = {}

            # Check if vininfo knows the brand
            is_unsupported = hasattr(brand, '__class__') and brand.__class__.__name__ == 'UnsupportedBrand'

            if brand and not is_unsupported:
                data["make"] = brand.name if hasattr(brand, "name") else str(brand)

                for attr_name, key in [("model", "model"), ("body", "body_class"), ("engine", "engine"),
                                       ("transmission", "transmission"), ("plant", "plant"), ("region", "country_of_manufacture")]:
                    if hasattr(brand, attr_name):
                        val = getattr(brand, attr_name)
                        if val:
                            data[key] = str(val)

            # Fallback: use core VIN decoder for unsupported brands
            if not data.get("make"):
                core_info = decode_vin_basic(vin)
                if core_info.get("make"):
                    data["make"] = core_info["make"]

            # Dane z samego VIN (zawsze dostępne)
            for attr, key in [("years", "model_year"), ("wmi", "wmi"), ("vds", "vds"), ("vis", "vis"), ("region", "region"), ("country", "country")]:
                if hasattr(v, attr):
                    val = getattr(v, attr)
                    if val:
                        data[key] = str(val)

            # Usuń None
            data = {k: v for k, v in data.items() if v}

            if not data.get("make"):
                return self._make_no_data(int((time.monotonic() - start) * 1000))

            elapsed = int((time.monotonic() - start) * 1000)
            logger.info("vininfo.done", vin=vin, make=data.get("make"))
            return PluginResult(
                source_name=self.name,
                category=self.category,
                status=SourceStatus.DONE,
                data=data,
                execution_time_ms=elapsed,
            )

        except ImportError:
            return self._make_error("Biblioteka vininfo nie jest zainstalowana", int((time.monotonic() - start) * 1000))
        except Exception as e:
            logger.error("vininfo.error", vin=vin, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
