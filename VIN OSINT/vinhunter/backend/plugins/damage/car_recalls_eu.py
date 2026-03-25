"""
car-recalls.eu — agregat recalli EU (RAPEX + KBA).
Szuka po make+model+year (z decoded VIN context).
Prosty GET search, brak Cloudflare.
"""
import re
import time
import httpx
import structlog

from plugins.base import SourcePlugin, SourceCategory, SourceStatus, PluginResult

logger = structlog.get_logger()

SEARCH_URL = "https://car-recalls.eu/"


class CarRecallsEUPlugin(SourcePlugin):
    name = "car_recalls_eu"
    display_name = "EU Recalls (car-recalls.eu)"
    category = SourceCategory.DAMAGE
    country = "EU"

    async def search_by_vin(self, vin: str, **kwargs) -> PluginResult:
        start = time.monotonic()
        context = kwargs.get("context", {})

        make = context.get("make", "") or context.get("Make", "")
        model = context.get("model", "") or context.get("Model", "")
        year = context.get("year", "") or context.get("ModelYear", "") or context.get("model_year", "")

        if not make:
            logger.info("car_recalls_eu.no_make", vin=vin, context_keys=list(context.keys()) if context else [])
            return self._make_no_data(int((time.monotonic() - start) * 1000))

        # Build search query: "mercedes c-class 2005"
        query_parts = [make]
        if model:
            query_parts.append(model)
        if year:
            query_parts.append(str(year))
        query = " ".join(query_parts)

        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                r = await client.get(SEARCH_URL, params={"s": query})
                r.raise_for_status()
                html = r.text

                recalls = self._parse_recalls(html)
                logger.info("car_recalls_eu.parsed", query=query, articles_found=len(recalls), html_len=len(html))

                if not recalls:
                    return self._make_no_data(int((time.monotonic() - start) * 1000))

                data = {
                    "search_query": query,
                    "total_recalls": len(recalls),
                    "recalls": recalls,
                    "source_url": str(r.url),
                }

                elapsed = int((time.monotonic() - start) * 1000)
                logger.info("car_recalls_eu.done", query=query, recalls=len(recalls))
                return PluginResult(
                    source_name=self.name,
                    category=self.category,
                    status=SourceStatus.DONE,
                    data=data,
                    execution_time_ms=elapsed,
                )

        except httpx.TimeoutException:
            return self._make_error("car-recalls.eu timeout", int((time.monotonic() - start) * 1000))
        except Exception as e:
            logger.error("car_recalls_eu.error", query=query, error=str(e))
            return self._make_error(str(e), int((time.monotonic() - start) * 1000))

    @staticmethod
    def _parse_recalls(html: str) -> list[dict]:
        """Parse recall articles from search results HTML."""
        recalls = []

        # Each recall is an <article> with class containing "post-" and listing/type info
        # Title in <h2 class="entry-title"><a href="...">Title</a></h2>
        # Description in <div class="entry-summary"><p>...</p></div>
        articles = re.findall(
            r'<article[^>]*>(.*?)</article>',
            html, re.DOTALL
        )

        for article in articles:
            # Title + URL from <h2 class="entry-title">
            title_match = re.search(
                r'<h2[^>]*class="[^"]*entry-title[^"]*"[^>]*>\s*<a\s+href="([^"]+)"[^>]*>\s*(.*?)\s*</a>',
                article, re.DOTALL
            )
            if not title_match:
                continue

            url = title_match.group(1).strip()
            title = re.sub(r'<[^>]+>', '', title_match.group(2)).strip()

            if not title:
                continue

            # Make URL absolute
            if url.startswith("/"):
                url = f"https://car-recalls.eu{url}"

            # Description from <div class="entry-summary"><p>...</p></div>
            excerpt = ""
            excerpt_match = re.search(
                r'<div[^>]*class="[^"]*entry-summary[^"]*"[^>]*>\s*<p>(.*?)</p>',
                article, re.DOTALL
            )
            if excerpt_match:
                excerpt = re.sub(r'<[^>]+>', '', excerpt_match.group(1)).strip()
                excerpt = re.sub(r'\s+', ' ', excerpt)

            recalls.append({
                "title": title,
                "url": url,
                "excerpt": excerpt[:300] if excerpt else "",
            })

        return recalls[:10]  # Max 10 results
