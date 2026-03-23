from bs4 import BeautifulSoup

from app.models import PageData


def extract_page_data(html: str, url: str, depth: int) -> PageData:
    """Parse HTML and extract title, meta description, h1."""
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    # Meta description
    meta = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "description"})
    description: str | None = None
    if meta and meta.get("content"):
        description = meta["content"].strip() or None

    # H1
    h1_tag = soup.find("h1")
    h1 = h1_tag.get_text(strip=True) if h1_tag else None

    # If no meta description, try first paragraph after h1
    if not description and h1_tag:
        next_p = h1_tag.find_next("p")
        if next_p:
            text = next_p.get_text(strip=True)
            if text:
                description = text[:200]

    return PageData(
        url=url,
        title=title,
        description=description,
        h1=h1,
        depth=depth,
        has_description=description is not None,
    )


def infer_site_suffix(titles: list[str]) -> str:
    """
    Find the longest common trailing suffix shared by >50% of titles.
    E.g. [" | My Site", " | My Site", " | My Site"] -> " | My Site"
    """
    if len(titles) < 2:
        return ""

    # Common separators that precede site suffixes
    separators = [" | ", " - ", " – ", " — ", " · ", " • "]

    candidate_counts: dict[str, int] = {}
    for title in titles:
        for sep in separators:
            idx = title.find(sep)
            if idx > 0:
                suffix = title[idx:]
                candidate_counts[suffix] = candidate_counts.get(suffix, 0) + 1

    if not candidate_counts:
        return ""

    best_suffix = max(candidate_counts, key=lambda s: candidate_counts[s])
    if candidate_counts[best_suffix] > len(titles) * 0.5:
        return best_suffix
    return ""


def clean_title(title: str, site_suffix: str) -> str:
    """Strip the site-wide suffix from a page title."""
    if site_suffix and title.endswith(site_suffix):
        return title[: -len(site_suffix)].strip()
    return title
