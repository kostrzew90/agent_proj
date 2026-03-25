"""
vindecoderz.com — darmowy VIN decoder z dobrym pokryciem EU.
Firefox bypass Cloudflare.
"""
import time
import structlog
from playwright.async_api import async_playwright
from playwright_stealth.stealth import Stealth

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult

logger = structlog.get_logger()

_FIREFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"


class VinDecoderzPlugin(SourcePlugin):
    name = "vindecoderz"
    display_name = "VINDecoderz (EU/global)"
    category = SourceCategory.VIN_DECODE
    country = "XX"
    enabled = False  # Cloudflare blocked — Firefox+stealth insufficient

    async def search_by_vin(self, vin: str) -> PluginResult:
        start = time.monotonic()
        try:
            async with async_playwright() as p:
                browser = await p.firefox.launch(headless=True)
                ctx = await browser.new_context(
                    user_agent=_FIREFOX_UA,
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                )
                page = await ctx.new_page()
                stealth = Stealth()
                await stealth.apply_stealth_async(page)

                url = f"https://www.vindecoderz.com/EN/check-lookup/{vin}"
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(3000)

                content = await page.content()

                # Cloudflare challenge — Firefox can sometimes pass it
                if "challenge-platform" in content or "Just a moment" in content:
                    logger.info("vindecoderz.cloudflare_challenge", vin=vin)
                    await page.wait_for_timeout(8000)
                    content = await page.content()
                    if "Just a moment" in content or "challenge-platform" in content:
                        await browser.close()
                        logger.warning("vindecoderz.cloudflare_blocked", vin=vin)
                        return self._make_error("Cloudflare blocked", int((time.monotonic() - start) * 1000))

                body_text = await page.evaluate("() => document.body.innerText")

                # No results
                if "not found" in body_text.lower() or "invalid vin" in body_text.lower():
                    await browser.close()
                    return self._make_no_data(int((time.monotonic() - start) * 1000))

                data = {}

                try:
                    # Extract data from tables
                    rows = await page.query_selector_all("table tr, .specs-table tr, dl dt")
                    for row in rows:
                        text = await row.inner_text()
                        if "\t" in text:
                            parts = text.split("\t", 1)
                        elif ":" in text:
                            parts = text.split(":", 1)
                        else:
                            continue
                        if len(parts) == 2:
                            key = parts[0].strip()
                            val = parts[1].strip()
                            if key and val and len(key) < 60:
                                data[key.lower().replace(" ", "_")] = val

                    # Fallback: extract from body text
                    if not data:
                        lines = body_text.split("\n")
                        for line in lines:
                            line = line.strip()
                            if ":" in line and len(line) < 200:
                                parts = line.split(":", 1)
                                key = parts[0].strip()
                                val = parts[1].strip()
                                if key and val and len(key) < 50:
                                    data[key.lower().replace(" ", "_")] = val

                except Exception:
                    pass

                await browser.close()

                if not data:
                    return self._make_no_data(int((time.monotonic() - start) * 1000))

                data["source_url"] = url

                elapsed = int((time.monotonic() - start) * 1000)
                logger.info("vindecoderz.done", vin=vin, fields=len(data))
                return PluginResult(
                    source_name=self.name,
                    category=self.category,
                    status=SourceStatus.DONE,
                    data=data,
                    execution_time_ms=elapsed,
                )

        except Exception as e:
            logger.error("vindecoderz.error", vin=vin, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
