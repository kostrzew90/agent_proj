"""
RAG System — Web Crawler
Fetches URL content and converts to clean Markdown using trafilatura.
No external services needed — pure Python.
"""

import hashlib
import logging

import httpx
import trafilatura
import html2text

logger = logging.getLogger("rag.ingestion.crawler")

# User-agent that works with most sites
_USER_AGENT = (
    "Mozilla/5.0 (compatible; RAGBot/1.0; +https://github.com/example/rag)"
)


class WebCrawler:
    """
    Fetches a URL and extracts clean Markdown content using trafilatura.
    trafilatura removes navigation, ads, footers — leaves only main content.
    Falls back to html2text if trafilatura returns nothing.
    """

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def fetch_markdown(self, url: str) -> dict:
        """
        Fetch and extract main content from a URL as Markdown.

        Returns dict with: url, title, markdown, content_hash
        Raises ValueError if no content could be extracted.
        Raises httpx.HTTPError on network failure.
        """
        logger.info("Crawling: %s", url)

        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        # Try trafilatura first (best content extraction)
        markdown = trafilatura.extract(
            html,
            output_format="markdown",
            include_links=False,
            include_images=False,
            include_tables=True,
            no_fallback=False,
        )

        # Fallback to html2text if trafilatura returned nothing
        if not markdown or len(markdown.strip()) < 100:
            logger.debug("trafilatura returned little content, trying html2text")
            h = html2text.HTML2Text()
            h.ignore_links = True
            h.ignore_images = True
            h.body_width = 0
            markdown = h.handle(html)

        if not markdown or not markdown.strip():
            raise ValueError(f"No content extracted from {url}")

        # Extract title
        title = _extract_title(html) or url
        content_hash = hashlib.sha256(markdown.encode()).hexdigest()

        logger.info(
            "Crawled %s — title=%r, %d chars, hash=%s",
            url, title, len(markdown), content_hash[:8],
        )
        return {
            "url": url,
            "title": title,
            "markdown": markdown,
            "content_hash": content_hash,
        }

    async def health_check(self) -> bool:
        """Always available — pure Python, no external service."""
        return True


def _extract_title(html: str) -> str | None:
    """Quick regex-free title extraction."""
    lower = html.lower()
    start = lower.find("<title")
    if start == -1:
        return None
    start = lower.find(">", start) + 1
    end = lower.find("</title>", start)
    if end == -1:
        return None
    return html[start:end].strip()[:200] or None
