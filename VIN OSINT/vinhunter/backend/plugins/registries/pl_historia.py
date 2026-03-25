"""
HistoriaPojazdu.gov.pl — polski rejestr pojazdów (Playwright).

Site uses Orbeon nForms SPA — requires browser to render form.
API: POST https://moj.gov.pl/nforms/api/HistoriaPojazdu/1.0.18/data/vehicle-data

Strategy: brute-force first registration date using month-first approach:
1. Try 1st of each month in model_year and model_year+1 (24 attempts)
2. When month found, narrow to exact day (30 attempts)
Total: ~54 attempts max, ~3 minutes with Playwright.
"""
import asyncio
import json
import time
import structlog
from datetime import date, timedelta
from typing import Optional

from playwright.async_api import async_playwright, Page, BrowserContext
from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult
from core.vin_decoder import decode_model_year

logger = structlog.get_logger()

HISTORIA_URL = "https://historiapojazdu.gov.pl/strona-glowna"
API_MARKER = "vehicle-data"


class PLHistoriaPlugin(SourcePlugin):
    name = "pl_historia"
    display_name = "Historia Pojazdu (PL)"
    category = SourceCategory.REGISTRY
    country = "PL"
    requires_captcha = False

    async def search_by_vin(self, vin: str) -> PluginResult:
        """Wymaga tablicy rejestracyjnej — sam VIN nie wystarczy."""
        return self._make_no_data()

    async def search_by_plate(self, plate: str, country: str, vin: str = None) -> PluginResult:
        if country.upper() != "PL":
            return self._make_no_data()
        if not vin:
            return self._make_error("Wymaga VIN + tablicy rejestracyjnej")

        year_hint = self._vin_year(vin)

        start = time.monotonic()
        try:
            result = await self._brute_force_playwright(plate, vin, year_hint)
            result.execution_time_ms = int((time.monotonic() - start) * 1000)
            return result
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            logger.error("pl_historia.error", error=str(e))
            return self._make_error(str(e), elapsed)

    @staticmethod
    def _vin_year(vin: str) -> Optional[int]:
        """Decode model year from VIN — NOTE: unreliable for EU vehicles.
        EU manufacturers don't always encode model year in position 10.
        Used only as a hint for search range center."""
        if len(vin) < 11:
            return None
        info = decode_model_year(vin.upper())
        return info.get("model_year")

    def _build_year_range(self, year_hint: Optional[int]) -> list[int]:
        """Build list of years to search, centered on hint ± 5 years.
        EU VINs don't reliably encode model year, so we search wide."""
        from datetime import datetime
        current_year = datetime.now().year

        if year_hint and 1980 <= year_hint <= current_year + 1:
            # Search year_hint ± 5, but prioritize hint and nearby years
            center = year_hint
        else:
            # No usable hint — search last 10 years
            center = current_year - 5

        # Order: center first, then spiral outward
        years = [center]
        for offset in range(1, 8):
            years.append(center + offset)
            years.append(center - offset)

        # Filter to valid range
        return [y for y in years if 1990 <= y <= current_year + 1]

    async def _brute_force_playwright(self, plate: str, vin: str, year_hint: Optional[int]) -> PluginResult:
        """Brute-force date using Playwright.
        Phase 1: 1st of each month across year range (~150 attempts max).
        Phase 2: when month found, try all days in that month (31 attempts)."""
        years = self._build_year_range(year_hint)
        logger.info("pl_historia.start", plate=plate, vin=vin, year_hint=year_hint,
                     search_range=f"{years[0]}-{years[-1]}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                locale="pl-PL",
            )
            page = await context.new_page()

            try:
                # Load form page
                await page.goto(HISTORIA_URL, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)

                # Verify form loaded
                reg_input = await page.query_selector("#registrationNumber")
                if not reg_input:
                    await browser.close()
                    return self._make_error("Form nie załadował się (brak #registrationNumber)")

                attempts = 0

                # Phase 1: Try 1st of each month across all years
                found_year = None
                found_month = None

                for y in years:
                    for m in range(1, 13):
                        test_date = date(y, m, 1)
                        result = await self._try_date(page, plate, vin, test_date)
                        attempts += 1

                        if result == "found":
                            # Check if exact date (1st) matched
                            report = await self._extract_report(page)
                            if report:
                                report["first_registration_date"] = test_date.strftime("%d.%m.%Y")
                                report["brute_force_attempts"] = attempts
                                logger.info("pl_historia.found", plate=plate, date=test_date, attempts=attempts)
                                await browser.close()
                                return PluginResult(
                                    source_name=self.name,
                                    category=self.category,
                                    status=SourceStatus.DONE,
                                    data=report,
                                    execution_time_ms=0,
                                )
                            # Report empty but API said found — record month for phase 2
                            found_year = y
                            found_month = m

                        if attempts % 10 == 0:
                            await asyncio.sleep(0.5)

                        # Hard limit to prevent infinite search
                        if attempts > 250:
                            break
                    if attempts > 250 or found_month:
                        break

                # Phase 2: Found the month — now find exact day
                if found_month:
                    logger.info("pl_historia.month_found", year=found_year, month=found_month,
                                attempts=attempts)
                    import calendar
                    _, days_in_month = calendar.monthrange(found_year, found_month)
                    for d in range(2, days_in_month + 1):  # skip 1st, already tried
                        test_date = date(found_year, found_month, d)
                        result = await self._try_date(page, plate, vin, test_date)
                        attempts += 1

                        if result == "found":
                            report = await self._extract_report(page)
                            report["first_registration_date"] = test_date.strftime("%d.%m.%Y")
                            report["brute_force_attempts"] = attempts
                            logger.info("pl_historia.found", plate=plate, date=test_date, attempts=attempts)
                            await browser.close()
                            return PluginResult(
                                source_name=self.name,
                                category=self.category,
                                status=SourceStatus.DONE,
                                data=report,
                                execution_time_ms=0,
                            )

                logger.info("pl_historia.not_found", plate=plate, year_hint=year_hint,
                            attempts=attempts)
                await browser.close()
                return self._make_no_data()

            except Exception as e:
                await browser.close()
                raise

    async def _dismiss_dialog(self, page: Page):
        """Dismiss the 'not found' Angular Material dialog overlay."""
        # Try clicking "SPRAWDŹ WPISANE DANE" button (returns to form)
        retry_btn = await page.query_selector('button:has-text("SPRAWDŹ WPISANE DANE")')
        if retry_btn:
            logger.info("pl_historia.dismiss_dialog", method="retry_button")
            await retry_btn.click()
            await page.wait_for_timeout(1000)
            return

        # Fallback: press Escape to close dialog
        logger.info("pl_historia.dismiss_dialog", method="escape_key")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

        # Fallback: click backdrop
        backdrop = await page.query_selector(".cdk-overlay-backdrop")
        if backdrop:
            logger.info("pl_historia.dismiss_dialog", method="backdrop_click")
            await backdrop.click(force=True)
            await page.wait_for_timeout(500)

    async def _try_date(self, page: Page, plate: str, vin: str, test_date: date) -> Optional[str]:
        """Try a single date. Returns 'found' if vehicle found, None otherwise."""
        try:
            date_str = test_date.strftime("%d.%m.%Y")
            logger.info("pl_historia.try_date", date=date_str)

            # Dismiss any lingering dialog from previous attempt
            dialog = await page.query_selector(".cdk-overlay-backdrop")
            if dialog:
                await self._dismiss_dialog(page)

            # Check if we're on the search form
            reg_input = await page.query_selector("#registrationNumber")
            if not reg_input:
                # Navigate back to form
                back_btn = await page.query_selector('button:has-text("WYSZUKAJ INNY POJAZD")')
                if back_btn:
                    await back_btn.click()
                    await page.wait_for_timeout(1500)
                else:
                    await page.goto(HISTORIA_URL, wait_until="networkidle", timeout=20000)
                    await page.wait_for_timeout(2000)

            # Clear and fill form
            for field_id in ["#registrationNumber", "#VINNumber", "#firstRegistrationDate"]:
                field = await page.query_selector(field_id)
                if field:
                    await field.click()
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")

            await page.fill("#registrationNumber", plate.upper().replace(" ", ""))
            await page.fill("#VINNumber", vin.upper())
            await page.fill("#firstRegistrationDate", date_str)

            # Submit — use force=True to bypass any remaining overlay
            btn = await page.query_selector('button:has-text("SPRAWDŹ POJAZD")')
            if not btn:
                return None

            # Intercept API response
            response_data = {}
            response_received = asyncio.Event()

            async def capture_response(response):
                if API_MARKER in response.url:
                    response_data["status"] = response.status
                    try:
                        response_data["body"] = await response.json()
                    except Exception:
                        response_data["body"] = None
                    response_received.set()

            page.on("response", capture_response)

            await btn.click(timeout=10000)

            # Wait for API response or timeout after 8 seconds
            try:
                await asyncio.wait_for(response_received.wait(), timeout=8.0)
            except asyncio.TimeoutError:
                logger.warning("pl_historia.api_response_timeout", date=date_str)

            page.remove_listener("response", capture_response)

            # Check result from API response
            http_status = response_data.get("status")
            body = response_data.get("body")

            # HTTP 404 = vehicle not found (always)
            if http_status == 404:
                await self._dismiss_dialog(page)
                return None

            # Check body for error codes
            if body and isinstance(body, dict):
                error_code = body.get("VALIDATION_ERROR_CODE", "")
                if error_code:
                    await self._dismiss_dialog(page)
                    return None

            # HTTP 200 with data and no error code = found
            if http_status == 200 and body and isinstance(body, dict) and not body.get("VALIDATION_ERROR_CODE"):
                return "found"

            # No API response captured — check page for "not found" dialog
            await page.wait_for_timeout(1000)
            not_found_dialog = await page.query_selector('button:has-text("SPRAWDŹ WPISANE DANE")')
            if not_found_dialog:
                await self._dismiss_dialog(page)
                return None

            # If no API response and no dialog, treat as not found
            return None

        except Exception as e:
            logger.warning("pl_historia.try_date_error", date=str(test_date), error=str(e))
            # Try to recover by dismissing any dialog
            try:
                await self._dismiss_dialog(page)
            except Exception:
                pass
            return None

    async def _extract_report(self, page: Page) -> dict:
        """Extract vehicle data from the report page."""
        data = {}
        await page.wait_for_timeout(2000)

        try:
            body_text = await page.evaluate("() => document.body.innerText")

            # Parse structured data from page text
            lines = body_text.split("\n")
            key_value_patterns = {
                "marka": ["marka", "make"],
                "model": ["model"],
                "rok_produkcji": ["rok produkcji", "year of production"],
                "pojemnosc_ccm": ["pojemność", "capacity"],
                "moc_kw": ["moc", "power"],
                "paliwo": ["rodzaj paliwa", "fuel type"],
                "przebieg_km": ["przebieg", "mileage"],
                "status": ["status pojazdu", "vehicle status"],
                "data_badania": ["data badania", "inspection date"],
                "wynik_badania": ["wynik badania", "inspection result"],
                "dopuszczalna_masa": ["dopuszczalna masa", "max weight"],
                "liczba_miejsc": ["liczba miejsc", "seats"],
                "rodzaj_pojazdu": ["rodzaj pojazdu", "vehicle type"],
                "kolor": ["kolor", "color"],
                "data_pierwszej_rej_pl": ["data pierwszej rejestracji w"],
            }

            for i, line in enumerate(lines):
                line_lower = line.strip().lower()
                for field_key, patterns in key_value_patterns.items():
                    for pattern in patterns:
                        if pattern in line_lower:
                            # Value is usually in the next line or after colon
                            if ":" in line:
                                val = line.split(":", 1)[1].strip()
                            elif i + 1 < len(lines):
                                val = lines[i + 1].strip()
                            else:
                                val = ""
                            if val and val.lower() not in ["", "-", "brak danych"]:
                                data[field_key] = val
                            break

            # Also try to get timeline/history entries
            history_entries = []
            for i, line in enumerate(lines):
                if any(kw in line.lower() for kw in ["rejestracja", "wyrejestrowanie", "badanie techniczne", "zmiana"]):
                    entry = line.strip()
                    if entry:
                        history_entries.append(entry)

            if history_entries:
                data["historia_zdarzen"] = history_entries[:20]  # cap at 20

        except Exception as e:
            logger.warning("pl_historia.parse_error", error=str(e))

        return data
