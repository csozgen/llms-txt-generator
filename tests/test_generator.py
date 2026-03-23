from app.generator.llmstxt import generate_llms_txt
from app.models import PageData


def _page(url, title=None, desc=None, h1=None, depth=1):
    return PageData(
        url=url,
        title=title,
        description=desc,
        h1=h1,
        depth=depth,
        has_description=desc is not None,
    )


ROOT = "https://example.com/"

PAGES = [
    _page(ROOT, "Example | My Site", "Home of example.com", "Welcome", depth=0),
    _page("https://example.com/docs/api", "API Reference | My Site", "Full API docs."),
    _page("https://example.com/docs/start", "Getting Started | My Site", "Install and run."),
    _page("https://example.com/changelog", "Changelog | My Site", None),
    _page("https://example.com/blog/v2", "Introducing V2 | My Site", "A major release."),
]


def test_header():
    result = generate_llms_txt(ROOT, PAGES)
    assert result.startswith("# Example\n")
    assert "> Home of example.com" in result


def test_sections():
    result = generate_llms_txt(ROOT, PAGES)
    assert "## Docs" in result
    assert "## Blog" in result


def test_optional_section():
    result = generate_llms_txt(ROOT, PAGES)
    assert "## Optional" in result
    assert "[Changelog]" in result


def test_suffix_stripped():
    result = generate_llms_txt(ROOT, PAGES)
    assert "API Reference | My Site" not in result
    assert "[API Reference]" in result


def test_empty_pages():
    result = generate_llms_txt(ROOT, [])
    assert "# example.com" in result
    assert "No pages" in result


def test_pages_without_description_only():
    pages = [
        _page(ROOT, "Home", None, depth=0),
        _page("https://example.com/about", "About", None),
    ]
    result = generate_llms_txt(ROOT, pages)
    assert "## Optional" in result
