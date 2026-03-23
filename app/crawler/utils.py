from urllib.parse import urljoin, urlparse, urlunparse

# Extensions to skip — not web pages
_SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".css", ".js", ".json", ".xml", ".zip", ".tar", ".gz",
    ".mp4", ".mp3", ".avi", ".mov", ".woff", ".woff2", ".ttf", ".eot",
    ".ico", ".dmg", ".exe", ".pkg", ".deb", ".rpm",
}


def normalize_url(url: str) -> str:
    """Lowercase scheme+host, strip fragment and trailing slash from path."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    normalized = urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        path,
        parsed.params,
        parsed.query,
        "",  # strip fragment
    ))
    return normalized


def is_same_domain(url: str, base_url: str) -> bool:
    """Return True if url shares the exact same netloc as base_url."""
    return urlparse(url).netloc.lower() == urlparse(base_url).netloc.lower()


def get_path_prefix(url: str) -> str:
    """Return first non-empty path segment. '/docs/foo/bar' -> 'docs'. '/' -> ''."""
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0] if parts and parts[0] else ""


def is_crawlable_url(url: str) -> bool:
    """Return False for URLs with skippable extensions or non-http(s) schemes."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    path = parsed.path.lower()
    for ext in _SKIP_EXTENSIONS:
        if path.endswith(ext):
            return False
    return True


def extract_links(html: str, base_url: str) -> list[str]:
    """Parse all <a href> links, resolve relative URLs, return absolute URLs."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        absolute = urljoin(base_url, href)
        # Strip fragment
        parsed = urlparse(absolute)
        clean = urlunparse(parsed._replace(fragment=""))
        if is_crawlable_url(clean):
            links.append(clean)
    return links
