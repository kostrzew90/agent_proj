"""
RAG System — X (Twitter) Post Scraper + GitHub README Fetcher
Extracts post content via FxTwitter API, finds GitHub links, fetches READMEs.
"""

import re
import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("rag.ingestion.xpost")

FXTWITTER_API = "https://api.fxtwitter.com"


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


async def fetch_post(url: str) -> XPostData:
    """Fetch X post content via FxTwitter API."""
    post = XPostData(url=url)

    info = extract_tweet_info(url)
    if not info:
        raise ValueError(f"Cannot parse X/Twitter URL: {url}")

    username, tweet_id = info

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Try FxTwitter API
        try:
            resp = await client.get(f"{FXTWITTER_API}/{username}/status/{tweet_id}")
            if resp.status_code == 200:
                data = resp.json()
                tweet = data.get("tweet", {})
                post.text = tweet.get("text", "")
                post.author = tweet.get("author", {}).get("name", username)
                logger.info("Fetched X post by %s: %d chars", post.author, len(post.text))
            else:
                logger.warning("FxTwitter returned %d, trying direct scrape", resp.status_code)
                raise ValueError(f"FxTwitter API returned {resp.status_code}")
        except Exception as e:
            # Fallback: try nitter or basic scrape
            logger.warning("FxTwitter failed (%s), trying Nitter", e)
            for nitter_host in ["nitter.privacydev.net", "nitter.poast.org"]:
                try:
                    nitter_url = f"https://{nitter_host}/{username}/status/{tweet_id}"
                    resp = await client.get(nitter_url, follow_redirects=True)
                    if resp.status_code == 200:
                        # Basic extraction from HTML
                        text = resp.text
                        # Find tweet content div
                        match = re.search(r'class="tweet-content[^"]*"[^>]*>(.*?)</div>', text, re.DOTALL)
                        if match:
                            content = re.sub(r"<[^>]+>", " ", match.group(1)).strip()
                            post.text = content
                            post.author = username
                            logger.info("Fetched via Nitter (%s): %d chars", nitter_host, len(post.text))
                            break
                except Exception:
                    continue

    if not post.text:
        raise ValueError("Could not fetch post content from any source")

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
