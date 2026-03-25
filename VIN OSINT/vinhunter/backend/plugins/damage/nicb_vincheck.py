"""
NICB VINCheck — US National Insurance Crime Bureau.
Sprawdza czy pojazd jest stolen/salvage. Limit: 5 queries/24h per IP.
Wymaga Playwright (strona blokuje httpx z 403).
"""
import time
import structlog
from playwright.async_api import async_playwright
from playwright_stealth.stealth import Stealth

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult

logger = structlog.get_logger()

VINCHECK_URL = "https://www.nicb.org/vincheck"


class NICBVINCheckPlugin(SourcePlugin):
    name = "nicb_vincheck"
    display_name = "NICB VINCheck (US stolen/salvage)"
    category = SourceCategory.DAMAGE
    country = "US"
    enabled = False  # Cloudflare blocked — Playwright+stealth insufficient

    async def search_by_vin(self, vin: str, **kwargs) -> PluginResult:
        start = time.monotonic()
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                ctx = await browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    locale="en-US",
                )
                page = await ctx.new_page()
                stealth = Stealth()
                await stealth.apply_stealth_async(page)

                await page.goto(VINCHECK_URL, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2000)

                content = await page.content()

                # Check for Cloudflare
                if "challenge-platform" in content or "Just a moment" in content:
                    await browser.close()
                    return self._make_error("Cloudflare blocked", int((time.monotonic() - start) * 1000))

                # Find VIN input field — try common selectors
                vin_input = (
                    await page.query_selector('input[name="vin"]')
                    or await page.query_selector('input[name="VIN"]')
                    or await page.query_selector('input[name="vin_number"]')
                    or await page.query_selector('input[id*="vin" i]')
                    or await page.query_selector('input[placeholder*="VIN" i]')
                    or await page.query_selector('input[type="text"]')
                )

                if not vin_input:
                    await browser.close()
                    return self._make_error(
                        "VIN input field not found",
                        int((time.monotonic() - start) * 1000),
                    )

                # Type VIN
                await vin_input.fill(vin)
                await page.wait_for_timeout(500)

                # Accept terms checkbox if present
                terms_cb = (
                    await page.query_selector('input[type="checkbox"][name*="agree" i]')
                    or await page.query_selector('input[type="checkbox"][name*="terms" i]')
                    or await page.query_selector('input[type="checkbox"][id*="agree" i]')
                    or await page.query_selector('input[type="checkbox"]')
                )
                if terms_cb:
                    checked = await terms_cb.is_checked()
                    if not checked:
                        await terms_cb.click()
                        await page.wait_for_timeout(300)

                # Submit
                submit_btn = (
                    await page.query_selector('button[type="submit"]')
                    or await page.query_selector('input[type="submit"]')
                    or await page.query_selector('button:has-text("Search")')
                    or await page.query_selector('button:has-text("Check")')
                )
                if submit_btn:
                    await submit_btn.click()
                else:
                    await page.keyboard.press("Enter")

                # Wait for results
                await page.wait_for_timeout(5000)
                result_html = await page.content()
                await browser.close()

                # Parse result
                result_lower = result_html.lower()
                data = {"vin": vin, "source_url": VINCHECK_URL}

                if "no records found" in result_lower or "no active" in result_lower:
                    data["status"] = "clean"
                    data["description"] = "No theft or salvage records found"
                elif "stolen" in result_lower and "record" in result_lower:
                    data["status"] = "stolen"
                    data["description"] = "Vehicle has active theft record"
                elif "salvage" in result_lower:
                    data["status"] = "salvage"
                    data["description"] = "Vehicle has salvage/total loss record"
                elif "limit" in result_lower and ("exceeded" in result_lower or "5" in result_lower):
                    return self._make_error(
                        "NICB daily query limit exceeded (5/day)",
                        int((time.monotonic() - start) * 1000),
                    )
                else:
                    data["status"] = "unknown"
                    data["description"] = "Could not determine vehicle status"

                elapsed = int((time.monotonic() - start) * 1000)
                logger.info("nicb_vincheck.done", vin=vin, status=data["status"])
                return PluginResult(
                    source_name=self.name,
                    category=self.category,
                    status=SourceStatus.DONE,
                    data=data,
                    execution_time_ms=elapsed,
                )

        except Exception as e:
            logger.error("nicb_vincheck.error", vin=vin, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))
