"""
bidfax.info — agregator aukcji Copart/IAAI (USA).
Zdjecia powypadkowe, ceny, przebieg. Firefox bypass Cloudflare.
"""
import time
import re
import structlog
from playwright.async_api import async_playwright
from playwright_stealth.stealth import Stealth

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult

logger = structlog.get_logger()

_FIREFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"


class BidfaxPlugin(SourcePlugin):
    name = "bidfax"
    display_name = "Bidfax (aukcje USA)"
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

                url = f"https://en.bidfax.info/{vin}"
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(3000)

                content = await page.content()

                # Cloudflare challenge — Firefox can sometimes pass it
                if "challenge-platform" in content or "Just a moment" in content:
                    logger.info("bidfax.cloudflare_challenge", vin=vin)
                    await page.wait_for_timeout(8000)
                    content = await page.content()
                    if "Just a moment" in content or "challenge-platform" in content:
                        await browser.close()
                        logger.warning("bidfax.cloudflare_blocked", vin=vin)
                        return self._make_error("Cloudflare blocked", int((time.monotonic() - start) * 1000))

                data = {}
                photos = []

                # 404 / not found
                title = await page.title()
                if "404" in title or "not found" in content.lower():
                    await browser.close()
                    return self._make_no_data(int((time.monotonic() - start) * 1000))

                try:
                    # Photos — auction images
                    all_imgs = await page.query_selector_all("img[src]")
                    for img in all_imgs:
                        src = await img.get_attribute("src") or ""
                        if any(cdn in src for cdn in ["bidfax.info/images", "copart.com", "iaai.com", "cs.copart"]):
                            photos.append(src)
                        data_src = await img.get_attribute("data-src") or ""
                        if any(cdn in data_src for cdn in ["bidfax.info/images", "copart.com", "iaai.com", "cs.copart"]):
                            photos.append(data_src)

                    # Also regex search in HTML
                    img_urls = re.findall(
                        r'https?://[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)',
                        content, re.IGNORECASE
                    )
                    for u in img_urls:
                        if any(cdn in u for cdn in ["bidfax.info/images", "copart.com", "iaai.com"]):
                            if u not in photos:
                                photos.append(u)

                    photos = list(dict.fromkeys(photos))[:15]

                    # Data from tables and info blocks
                    rows = await page.query_selector_all("table tr, .lot-info tr, .vehicle-info li, .card-body li")
                    for row in rows:
                        text = await row.inner_text()
                        if ":" in text and len(text) < 200:
                            parts = text.split(":", 1)
                            key = parts[0].strip().lower()
                            val = parts[1].strip()
                            if key and val:
                                data[key] = val

                    # Page title as context
                    if title and "bidfax" not in title.lower() and "just a moment" not in title.lower():
                        data["page_title"] = title

                except Exception:
                    pass

                await browser.close()

                if not data and not photos:
                    return self._make_no_data(int((time.monotonic() - start) * 1000))

                data["photos_found"] = len(photos)
                data["photos"] = photos
                data["source_url"] = url

                elapsed = int((time.monotonic() - start) * 1000)
                logger.info("bidfax.done", vin=vin, photos=len(photos), fields=len(data))
                return PluginResult(
                    source_name=self.name,
                    category=self.category,
                    status=SourceStatus.DONE,
                    data=data,
                    execution_time_ms=elapsed,
                )

        except Exception as e:
            logger.error("bidfax.error", vin=vin, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
