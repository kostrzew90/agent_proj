"""
stat.vin — agregator aukcji USA (Copart/IAAI).
Firefox bypass Cloudflare.
"""
import time
import re
import structlog
from playwright.async_api import async_playwright
from playwright_stealth.stealth import Stealth

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult

logger = structlog.get_logger()

_FIREFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"


class StatVinPlugin(SourcePlugin):
    name = "statvin"
    display_name = "Stat.vin (aukcje USA)"
    category = SourceCategory.DAMAGE
    country = "US"
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

                url = f"https://stat.vin/vin/{vin}"
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(3000)

                content = await page.content()

                # Cloudflare challenge — Firefox can sometimes pass it
                if "challenge-platform" in content or "Just a moment" in content:
                    logger.info("statvin.cloudflare_challenge", vin=vin)
                    await page.wait_for_timeout(8000)
                    content = await page.content()
                    if "Just a moment" in content or "challenge-platform" in content:
                        await browser.close()
                        logger.warning("statvin.cloudflare_blocked", vin=vin)
                        return self._make_error("Cloudflare blocked", int((time.monotonic() - start) * 1000))

                # Get rendered text to check for actual results
                body_text = await page.evaluate("() => document.body.innerText")

                # No results detection — stat.vin shows generic page with no lot data
                has_lot_data = False
                for indicator in ["Lot #", "lot #", "Odometer", "Primary Damage", "Sale Date",
                                  "Пробег", "Повреждени", "Дата продажи", "Номер лота"]:
                    if indicator in body_text:
                        has_lot_data = True
                        break

                if not has_lot_data:
                    await browser.close()
                    elapsed = int((time.monotonic() - start) * 1000)
                    logger.info("statvin.no_data", vin=vin)
                    return self._make_no_data(elapsed)

                data = {}
                photos = []

                try:
                    # Photos — actual vehicle images from auction CDNs
                    all_imgs = await page.query_selector_all("img[src]")
                    for img in all_imgs:
                        src = await img.get_attribute("src") or ""
                        if any(cdn in src for cdn in ["cs.copart.com", "iaai.com", "cdn.copart", "vimg.copart"]):
                            photos.append(src)
                        data_src = await img.get_attribute("data-src") or ""
                        if any(cdn in data_src for cdn in ["cs.copart.com", "iaai.com", "cdn.copart", "vimg.copart"]):
                            photos.append(data_src)

                    # Also search HTML for image URLs
                    cdn_urls = re.findall(
                        r'https?://(?:cs\.copart\.com|cdn\.copart|vimg\.copart|iaai\.com)[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)',
                        content, re.IGNORECASE
                    )
                    for u in cdn_urls:
                        if u not in photos:
                            photos.append(u)

                    photos = list(dict.fromkeys(photos))[:15]

                    # Extract text data from rendered page
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

                if not data and not photos:
                    return self._make_no_data(int((time.monotonic() - start) * 1000))

                data["photos_found"] = len(photos)
                data["photos"] = photos
                data["source_url"] = url

                elapsed = int((time.monotonic() - start) * 1000)
                logger.info("statvin.done", vin=vin, photos=len(photos), fields=len(data))
                return PluginResult(
                    source_name=self.name,
                    category=self.category,
                    status=SourceStatus.DONE,
                    data=data,
                    execution_time_ms=elapsed,
                )

        except Exception as e:
            logger.error("statvin.error", vin=vin, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
