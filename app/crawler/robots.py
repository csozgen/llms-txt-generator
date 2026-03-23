import io
import urllib.robotparser
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx

_USER_AGENT = "profound-llm"


async def fetch_robots(
    client: httpx.AsyncClient, base_url: str
) -> tuple[str | None, list[str]]:
    """
    Fetch /robots.txt.
    Returns (raw_robots_text_or_None, list_of_sitemap_urls).
    """
    robots_url = urljoin(base_url, "/robots.txt")
    try:
        resp = await client.get(robots_url, timeout=10.0)
        if resp.status_code != 200:
            return None, []
        text = resp.text
        sitemaps = _extract_sitemaps_from_robots(text)
        return text, sitemaps
    except Exception:
        return None, []


def _extract_sitemaps_from_robots(robots_text: str) -> list[str]:
    sitemaps: list[str] = []
    for line in robots_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("sitemap:"):
            url = stripped[len("sitemap:"):].strip()
            if url:
                sitemaps.append(url)
    return sitemaps


async def parse_sitemap(
    client: httpx.AsyncClient, sitemap_url: str, limit: int
) -> list[str]:
    """
    Fetch and parse an XML sitemap (handles sitemap index → nested sitemaps).
    Returns up to `limit` page URLs.
    """
    urls: list[str] = []
    await _parse_sitemap_recursive(client, sitemap_url, limit, urls, depth=0)
    return urls[:limit]


async def _parse_sitemap_recursive(
    client: httpx.AsyncClient,
    sitemap_url: str,
    limit: int,
    urls: list[str],
    depth: int,
) -> None:
    if len(urls) >= limit or depth > 3:
        return
    try:
        resp = await client.get(sitemap_url, timeout=15.0)
        if resp.status_code != 200:
            return
        root = ElementTree.fromstring(resp.content)
    except Exception:
        return

    ns = _extract_namespace(root.tag)

    # Sitemap index — recurse into child sitemaps
    if root.tag in (f"{ns}sitemapindex", "sitemapindex"):
        for sitemap_el in root.findall(f"{ns}sitemap"):
            loc_el = sitemap_el.find(f"{ns}loc")
            if loc_el is not None and loc_el.text:
                child_url = loc_el.text.strip()
                await _parse_sitemap_recursive(client, child_url, limit, urls, depth + 1)
                if len(urls) >= limit:
                    return
    else:
        # Regular sitemap — extract <loc> URLs
        for url_el in root.findall(f"{ns}url"):
            loc_el = url_el.find(f"{ns}loc")
            if loc_el is not None and loc_el.text:
                urls.append(loc_el.text.strip())
                if len(urls) >= limit:
                    return


def _extract_namespace(tag: str) -> str:
    if tag.startswith("{"):
        return tag[: tag.index("}") + 1]
    return ""


def is_allowed(robots_text: str, url: str) -> bool:
    """Parse robots.txt rules and return whether the given URL is crawlable."""
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(robots_text.splitlines())
    return parser.can_fetch(_USER_AGENT, url)
