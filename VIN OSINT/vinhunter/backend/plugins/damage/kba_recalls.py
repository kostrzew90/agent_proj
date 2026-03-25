"""
KBA (Kraftfahrt-Bundesamt) — niemieckie recalle pojazdów.
Szuka po marce + modelu + roku (z decoded VIN context).
Korzysta z REST API KBA z Altcha proof-of-work CAPTCHA (rozwiązywanym programowo).
"""
import base64
import hashlib
import json
import time
import httpx
import structlog

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult

logger = structlog.get_logger()

BASE_URL = "https://www.kba-online.de/rrdb/buerger/api"
ALTCHA_URL = f"{BASE_URL}/altcha"
SEARCH_URL = f"{BASE_URL}/rueckruf/verkaufsbezeichnungBaujahr"


class KBARecallsPlugin(SourcePlugin):
    name = "kba_recalls"
    display_name = "KBA Recalls (Germany)"
    category = SourceCategory.DAMAGE
    country = "DE"

    async def search_by_vin(self, vin: str, **kwargs) -> PluginResult:
        start = time.monotonic()
        context = kwargs.get("context", {})

        make = context.get("make", "") or context.get("Make", "")
        model = context.get("model", "") or context.get("Model", "")
        year = context.get("year", "") or context.get("ModelYear", "") or context.get("model_year", "")

        if not make:
            return self._make_no_data(int((time.monotonic() - start) * 1000))

        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                # Step 1: Get Altcha challenge
                altcha_payload = await self._solve_altcha(client)
                if not altcha_payload:
                    return self._make_error(
                        "Failed to solve Altcha CAPTCHA",
                        int((time.monotonic() - start) * 1000),
                    )

                # Step 2: POST search
                body = {
                    "altchaPayload": altcha_payload,
                    "marke": make,
                    "verkaufsbezeichnungen": [model] if model else [],
                }
                if year:
                    body["baujahr"] = str(year)

                r = await client.post(
                    SEARCH_URL,
                    json=body,
                    headers={
                        "Content-Type": "application/json",
                        "Origin": "https://www.kba-online.de",
                        "Referer": "https://www.kba-online.de/rrdb/buerger/",
                    },
                )
                r.raise_for_status()
                results = r.json()

                # Parse results — KBA returns a list of recall objects
                recalls = self._parse_results(results)

                if not recalls:
                    return self._make_no_data(int((time.monotonic() - start) * 1000))

                data = {
                    "make": make,
                    "model": model or "all",
                    "year": year or "all",
                    "total_recalls": len(recalls),
                    "recalls": recalls,
                    "source_url": "https://www.kba-online.de/rrdb/buerger/",
                }

                elapsed = int((time.monotonic() - start) * 1000)
                logger.info("kba_recalls.done", make=make, model=model, recalls=len(recalls))
                return PluginResult(
                    source_name=self.name,
                    category=self.category,
                    status=SourceStatus.DONE,
                    data=data,
                    execution_time_ms=elapsed,
                )

        except httpx.TimeoutException:
            return self._make_error("KBA API timeout", int((time.monotonic() - start) * 1000))
        except Exception as e:
            logger.error("kba_recalls.error", make=make, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))

    @staticmethod
    async def _solve_altcha(client: httpx.AsyncClient) -> str | None:
        """Fetch Altcha challenge and solve proof-of-work."""
        try:
            r = await client.get(ALTCHA_URL)
            r.raise_for_status()
            challenge = r.json()

            algorithm = challenge.get("algorithm", "SHA-256")
            salt = challenge.get("salt", "")
            target_challenge = challenge.get("challenge", "")
            max_number = challenge.get("maxnumber", 1_000_000)

            # Proof of work: find number N such that hash(salt + N) == challenge
            solve_start = time.monotonic()
            for n in range(max_number + 1):
                candidate = f"{salt}{n}"
                if algorithm == "SHA-256":
                    h = hashlib.sha256(candidate.encode()).hexdigest()
                elif algorithm == "SHA-384":
                    h = hashlib.sha384(candidate.encode()).hexdigest()
                elif algorithm == "SHA-512":
                    h = hashlib.sha512(candidate.encode()).hexdigest()
                else:
                    h = hashlib.sha256(candidate.encode()).hexdigest()

                if h == target_challenge:
                    took = int((time.monotonic() - solve_start) * 1000)
                    payload = {
                        "algorithm": algorithm,
                        "challenge": target_challenge,
                        "number": n,
                        "salt": salt,
                        "signature": challenge.get("signature", ""),
                        "took": took,
                    }
                    return base64.b64encode(json.dumps(payload).encode()).decode()

            logger.warning("kba_recalls.altcha_unsolved", max_number=max_number)
            return None

        except Exception as e:
            logger.error("kba_recalls.altcha_error", error=str(e))
            return None

    @staticmethod
    def _parse_results(results) -> list[dict]:
        """Parse KBA API response into recall list."""
        recalls = []
        if isinstance(results, list):
            items = results
        elif isinstance(results, dict):
            items = results.get("rueckrufDtos", results.get("results", results.get("data", [])))
        else:
            return recalls
        if not isinstance(items, list):
            return recalls

        for item in items:
            recall = {}
            # KBA fields vary — extract what's available
            recall["publication_date"] = (
                item.get("veroeffentlichungsDatum")
                or item.get("publicationDate", "")
            )
            recall["defect"] = (
                item.get("mangelbeschreibung")
                or item.get("defectDescription", "")
            )
            recall["production_period"] = (
                item.get("produktionszeitraum")
                or item.get("productionPeriod", "")
            )
            recall["manufacturer_code"] = (
                item.get("herstellerRueckrufCode")
                or item.get("manufacturerRecallCode", "")
            )
            recall["kba_ref"] = (
                item.get("kbaReferenznummer")
                or item.get("kbaReferenceNumber", "")
            )

            # Only add if we have at least some content
            if recall.get("defect") or recall.get("manufacturer_code") or recall.get("kba_ref"):
                recalls.append(recall)

        return recalls[:20]
