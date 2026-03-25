"""
Yandex Images — lepsze wyniki dla aut z EU/RU.
Playwright headless.
"""
import time
import re
import urllib.parse
import structlog
from playwright.async_api import async_playwright

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult

logger = structlog.get_logger()


class YandexImagesPlugin(SourcePlugin):
    name = "yandex_images"
    display_name = "Yandex Images"
    category = SourceCategory.PHOTO_OSINT
    country = "XX"

    async def search_by_vin(self, vin: str) -> PluginResult:
        start = time.monotonic()
        try:
            photos = []
            links_data = []
            query = f'"{vin}"'
            encoded = urllib.parse.quote(query)

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
                ctx = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                    locale="en-US",
                )
                page = await ctx.new_page()

                # Yandex Images
                url = f"https://yandex.com/images/search?text={encoded}"
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000)

                content = await page.content()

                # Check if captcha/blocked
                if "captcha" in content.lower() or "smartcaptcha" in content.lower():
                    await browser.close()
                    logger.warning("yandex_images.captcha", vin=vin)
                    return self._make_error("Yandex CAPTCHA required", int((time.monotonic() - start) * 1000))

                # Extract thumbnails — try multiple selectors for current Yandex layout
                img_selectors = [
                    "img.serp-item__thumb",
                    "img[class*='thumb']",
                    "img[class*='Thumb']",
                    "img[class*='preview']",
                    "img[class*='Preview']",
                    ".serp-item img",
                    "[class*='SerpItem'] img",
                    "[role='listitem'] img",
                ]
                for selector in img_selectors:
                    imgs = await page.query_selector_all(selector)
                    for img in imgs[:15]:
                        src = await img.get_attribute("src") or ""
                        if not src:
                            src = await img.get_attribute("data-src") or ""
                        if src:
                            if src.startswith("//"):
                                src = "https:" + src
                            if src.startswith("http") and "yastatic" not in src:
                                if not any(p["url"] == src for p in photos):
                                    photos.append({"url": src, "source": "yandex_images"})
                    if photos:
                        break

                # Also extract image URLs from HTML/JSON embedded data
                img_urls = re.findall(
                    r'"(?:url|src|thumb|preview)":\s*"(https?://[^"]+\.(?:jpg|jpeg|png|webp))"',
                    content
                )
                for u in img_urls:
                    if "yastatic" not in u and not any(p["url"] == u for p in photos):
                        photos.append({"url": u, "source": "yandex_images"})

                # Fallback: Yandex web search
                if not photos:
                    url2 = f"https://yandex.com/search/?text={encoded}"
                    await page.goto(url2, wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(2000)

                    anchors = await page.query_selector_all("a[href^='http']")
                    seen = set()
                    for a in anchors[:40]:
                        href = await a.get_attribute("href") or ""
                        if "yandex" in href or href in seen:
                            continue
                        seen.add(href)
                        text = (await a.inner_text()).strip()
                        if text and len(text) > 5:
                            links_data.append({"url": href, "text": text[:120]})

                await browser.close()

            elapsed = int((time.monotonic() - start) * 1000)

            if not photos and not links_data:
                return self._make_no_data(elapsed)

            data = {
                "query": query,
                "photos": photos[:10],
                "photos_found": len(photos),
            }
            if links_data:
                data["related_links"] = links_data[:10]
                data["links_found"] = len(links_data)

            logger.info("yandex_images.done", vin=vin, photos=len(photos))
            return PluginResult(
                source_name=self.name,
                category=self.category,
                status=SourceStatus.DONE,
                data=data,
                execution_time_ms=elapsed,
            )

        except Exception as e:
            logger.error("yandex_images.error", vin=vin, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
