"""
Google Images — wyszukiwanie zdjec po VIN.
Szuka w Google Images + zwyklym Google, zbiera linki do stron z VIN.
"""
import time
import re
import urllib.parse
import structlog
from playwright.async_api import async_playwright

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult

logger = structlog.get_logger()


class GoogleImagesPlugin(SourcePlugin):
    name = "google_images"
    display_name = "Google Images"
    category = SourceCategory.PHOTO_OSINT
    country = "XX"
    enabled = False  # Always blocked from Docker IP (unusual traffic captcha)

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
                page = await browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                )

                # 1) Google Images search
                url = f"https://www.google.com/search?q={encoded}&udm=2&num=20"
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000)

                # Extract thumbnail images — Google uses data: URIs initially,
                # but some load as http after render. Also extract from scripts.
                content = await page.content()

                # Find image URLs embedded in page JS (Google stores originals in script blocks)
                # Pattern: "https://example.com/photo.jpg" in JSON-like structures
                img_urls_in_scripts = re.findall(
                    r'\["(https?://[^"]+\.(?:jpg|jpeg|png|webp))",[0-9]+,[0-9]+\]',
                    content
                )
                for u in img_urls_in_scripts:
                    if "google" not in u and "gstatic" not in u and "googleapis" not in u:
                        photos.append({"url": u, "source": "google_images"})

                # Also try img elements with http src
                imgs = await page.query_selector_all("img[src^='http']")
                for img in imgs[:30]:
                    src = await img.get_attribute("src") or ""
                    if src and "google" not in src and "gstatic" not in src:
                        if not any(p["url"] == src for p in photos):
                            photos.append({"url": src, "source": "google_images"})

                # 2) Regular Google search for related links
                url2 = f"https://www.google.com/search?q={encoded}&num=10"
                await page.goto(url2, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)

                # Extract search result links
                anchors = await page.query_selector_all("a[href^='http']")
                seen_domains = set()
                for a in anchors[:50]:
                    href = await a.get_attribute("href") or ""
                    if "google" in href or not href.startswith("http"):
                        continue
                    # Get domain to deduplicate
                    domain = re.match(r'https?://([^/]+)', href)
                    if domain:
                        d = domain.group(1)
                        if d in seen_domains:
                            continue
                        seen_domains.add(d)
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
                "related_links": links_data[:10],
                "photos_found": len(photos),
                "links_found": len(links_data),
            }

            logger.info("google_images.done", vin=vin, photos=len(photos), links=len(links_data))
            return PluginResult(
                source_name=self.name,
                category=self.category,
                status=SourceStatus.DONE,
                data=data,
                execution_time_ms=elapsed,
            )

        except Exception as e:
            logger.error("google_images.error", vin=vin, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
