"""
RAG System — X (Twitter) Post Scraper + GitHub README Fetcher
Extracts post content via VxTwitter API (primary) or Twitter oEmbed (fallback),
finds GitHub links, and fetches READMEs.
"""

import re
import logging
from dataclasses import dataclass, field
from html.parser import HTMLParser

import httpx

logger = logging.getLogger("rag.ingestion.xpost")

VXTWITTER_API = "https://api.vxtwitter.com"
OEMBED_API = "https://publish.twitter.com/oembed"


@dataclass
class GitHubRepo:
    owner: str
    name: str
    url: str
    readme: str = ""
    description: str = ""


@dataclass
class XPostData:
    url: str
    author: str = ""
    text: str = ""
    repos: list[GitHubRepo] = field(default_factory=list)
    raw_content: str = ""


def extract_tweet_info(url: str) -> tuple[str, str] | None:
    """Extract (username, tweet_id) from X/Twitter URL."""
    patterns = [
        r"(?:twitter\.com|x\.com)/(\w+)/status/(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), match.group(2)
    return None


def extract_github_urls(text: str) -> list[tuple[str, str]]:
    """Extract GitHub owner/repo pairs from text. Returns [(owner, repo), ...]."""
    pattern = r"github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)"
    matches = re.findall(pattern, text)
    seen = set()
    result = []
    for owner, repo in matches:
        repo = repo.rstrip("/").split("#")[0].split("?")[0]
        # Skip common non-repo paths
        if repo in ("issues", "pulls", "actions", "settings", "blob", "tree", "wiki"):
            continue
        key = f"{owner}/{repo}".lower()
        if key not in seen:
            seen.add(key)
            result.append((owner, repo))
    return result


class _HTMLTextStripper(HTMLParser):
    """Minimal HTML-to-text converter for oEmbed html field."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(part.strip() for part in self._parts if part.strip())


def _strip_html(html: str) -> str:
    parser = _HTMLTextStripper()
    parser.feed(html)
    return parser.get_text()


async def fetch_post(url: str) -> XPostData:
    """Fetch X post content via VxTwitter API (primary) or Twitter oEmbed (fallback)."""
    post = XPostData(url=url)

    info = extract_tweet_info(url)
    if not info:
        raise ValueError(f"Cannot parse X/Twitter URL: {url}")

    username, tweet_id = info

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        # 1. Try VxTwitter API
        try:
            resp = await client.get(f"{VXTWITTER_API}/{username}/status/{tweet_id}")
            if resp.status_code == 200:
                data = resp.json()
                post.text = data.get("text", "")
                post.author = data.get("user_name", username)
                logger.info("Fetched X post via VxTwitter by %s: %d chars", post.author, len(post.text))
                return post
            logger.warning("VxTwitter returned HTTP %d", resp.status_code)
        except Exception as exc:
            logger.warning("VxTwitter request failed: %s", exc)

        # 2. Fallback: Twitter oEmbed API
        try:
            oembed_url = f"{OEMBED_API}?url={url}&omit_script=true"
            resp = await client.get(oembed_url)
            if resp.status_code == 200:
                data = resp.json()
                raw_html = data.get("html", "")
                post.text = _strip_html(raw_html)
                post.author = data.get("author_name", username)
                logger.info("Fetched X post via oEmbed by %s: %d chars", post.author, len(post.text))
                return post
            logger.warning("oEmbed returned HTTP %d", resp.status_code)
        except Exception as exc:
            logger.warning("oEmbed request failed: %s", exc)

    raise ValueError(f"Could not fetch post content from any source for: {url}")


async def create_post_from_text(url: str, text: str, author: str = "unknown") -> XPostData:
    """Create XPostData from user-provided text (paste fallback).

    Extracts GitHub URLs from the text and fetches their READMEs,
    then composes raw_content exactly like process_xpost does.
    """
    post = XPostData(url=url, author=author, text=text)

    github_pairs = extract_github_urls(text)
    logger.info("Found %d GitHub repos in pasted text", len(github_pairs))

    for owner, repo in github_pairs:
        try:
            github_repo = await fetch_github_readme(owner, repo)
            post.repos.append(github_repo)
        except Exception as exc:
            logger.warning("Failed to fetch %s/%s: %s", owner, repo, exc)

    parts = [
        f"# X Post by {post.author}\n",
        f"Source: {post.url}\n",
        f"\n{post.text}\n",
    ]
    for repo in post.repos:
        parts.append(f"\n---\n\n## GitHub: {repo.owner}/{repo.name}\n")
        if repo.description:
            parts.append(f"**{repo.description}**\n")
        parts.append(f"URL: {repo.url}\n")
        if repo.readme:
            parts.append(f"\n{repo.readme}\n")

    post.raw_content = "\n".join(parts)
    return post


async def fetch_github_readme(owner: str, repo: str) -> GitHubRepo:
    """Fetch GitHub repo README and description."""
    github_repo = GitHubRepo(owner=owner, name=repo, url=f"https://github.com/{owner}/{repo}")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Fetch repo metadata
        try:
            resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
            if resp.status_code == 200:
                data = resp.json()
                github_repo.description = data.get("description", "") or ""
        except Exception:
            pass

        # Fetch README (try main, then master)
        for branch in ["main", "master"]:
            try:
                url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
                resp = await client.get(url)
                if resp.status_code == 200:
                    readme = resp.text
                    # Truncate very long READMEs
                    if len(readme) > 15000:
                        readme = readme[:15000] + "\n\n... (truncated)"
                    github_repo.readme = readme
                    logger.info("Fetched README for %s/%s (%d chars)", owner, repo, len(readme))
                    break
            except Exception:
                continue

    return github_repo


async def process_xpost(url: str) -> XPostData:
    """Full pipeline: fetch post → extract GitHub links → fetch READMEs."""
    post = await fetch_post(url)

    # Extract GitHub URLs from post text
    github_pairs = extract_github_urls(post.text)
    logger.info("Found %d GitHub repos in post", len(github_pairs))

    for owner, repo in github_pairs:
        try:
            github_repo = await fetch_github_readme(owner, repo)
            post.repos.append(github_repo)
        except Exception as e:
            logger.warning("Failed to fetch %s/%s: %s", owner, repo, e)

    # Compose raw content for embedding
    parts = [
        f"# X Post by {post.author}\n",
        f"Source: {post.url}\n",
        f"\n{post.text}\n",
    ]
    for repo in post.repos:
        parts.append(f"\n---\n\n## GitHub: {repo.owner}/{repo.name}\n")
        if repo.description:
            parts.append(f"**{repo.description}**\n")
        parts.append(f"URL: {repo.url}\n")
        if repo.readme:
            parts.append(f"\n{repo.readme}\n")

    post.raw_content = "\n".join(parts)
    return post
