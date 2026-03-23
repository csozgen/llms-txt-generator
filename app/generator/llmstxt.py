from urllib.parse import urlparse

from app.crawler.extractor import clean_title, infer_site_suffix
from app.crawler.utils import get_path_prefix
from app.models import PageData


def generate_llms_txt(root_url: str, pages: list[PageData]) -> str:
    """Build a spec-compliant llms.txt string from a list of crawled PageData."""
    if not pages:
        domain = urlparse(root_url).netloc
        return f"# {domain}\n\n> No pages were successfully crawled.\n"

    # Find root page
    from app.crawler.utils import normalize_url
    norm_root = normalize_url(root_url)
    root_page = next(
        (p for p in pages if normalize_url(p.url) == norm_root), pages[0]
    )

    # Infer and strip common title suffix
    all_titles = [p.title for p in pages if p.title]
    site_suffix = infer_site_suffix(all_titles)

    # Determine site title
    site_title = _get_site_title(root_page, site_suffix, root_url)

    # Determine site description
    site_description = root_page.description

    # Group pages — exclude root from sections (it's in the header)
    non_root_pages = [p for p in pages if normalize_url(p.url) != norm_root]

    # Separate pages with and without descriptions
    with_desc = [p for p in non_root_pages if p.has_description]
    without_desc = [p for p in non_root_pages if not p.has_description]

    # Group with-description pages by path prefix
    sections: dict[str, list[PageData]] = {}
    for page in with_desc:
        prefix = get_path_prefix(page.url)
        section_name = _humanize_section_name(prefix)
        sections.setdefault(section_name, []).append(page)

    # Sort sections: "Pages" first, then alphabetical, "Optional" always last
    def section_sort_key(name: str) -> tuple[int, str]:
        if name == "Pages":
            return (0, name)
        return (1, name)

    sorted_section_names = sorted(sections.keys(), key=section_sort_key)

    # Build output
    lines: list[str] = []

    # Header
    lines.append(f"# {site_title}")
    lines.append("")
    if site_description:
        lines.append(f"> {site_description}")
        lines.append("")

    # Sections
    for section_name in sorted_section_names:
        section_pages = sorted(sections[section_name], key=lambda p: _display_title(p, site_suffix))
        lines.append(f"## {section_name}")
        lines.append("")
        for page in section_pages:
            lines.append(_render_list_item(page, site_suffix))
        lines.append("")

    # Optional section
    if without_desc:
        lines.append("## Optional")
        lines.append("")
        sorted_optional = sorted(without_desc, key=lambda p: _display_title(p, site_suffix))
        for page in sorted_optional:
            lines.append(_render_list_item(page, site_suffix))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _get_site_title(root_page: PageData, site_suffix: str, root_url: str) -> str:
    if root_page.title:
        cleaned = clean_title(root_page.title, site_suffix)
        if cleaned:
            return cleaned
    if root_page.h1:
        return root_page.h1
    return urlparse(root_url).netloc


def _display_title(page: PageData, site_suffix: str) -> str:
    if page.title:
        return clean_title(page.title, site_suffix)
    if page.h1:
        return page.h1
    return page.url


def _render_list_item(page: PageData, site_suffix: str) -> str:
    title = _display_title(page, site_suffix) or page.url
    url = page.url
    if page.description:
        return f"- [{title}]({url}): {page.description}"
    return f"- [{title}]({url})"


def _humanize_section_name(prefix: str) -> str:
    """Convert URL prefix to title-case section name. '' -> 'Pages'."""
    if not prefix:
        return "Pages"
    return " ".join(word.capitalize() for word in prefix.replace("-", " ").replace("_", " ").split())
