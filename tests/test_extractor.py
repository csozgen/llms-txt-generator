from app.crawler.extractor import clean_title, extract_page_data, infer_site_suffix
from app.crawler.utils import (
    extract_links,
    get_path_prefix,
    is_crawlable_url,
    is_same_domain,
    normalize_url,
)


def test_normalize_url():
    assert normalize_url("https://Example.COM/docs/") == "https://example.com/docs"
    assert normalize_url("https://example.com#section") == "https://example.com/"
    assert normalize_url("https://example.com/page?q=1") == "https://example.com/page?q=1"


def test_is_same_domain():
    assert is_same_domain("https://example.com/page", "https://example.com")
    assert not is_same_domain("https://sub.example.com", "https://example.com")
    assert not is_same_domain("https://other.com", "https://example.com")


def test_get_path_prefix():
    assert get_path_prefix("https://example.com/docs/api") == "docs"
    assert get_path_prefix("https://example.com/") == ""
    assert get_path_prefix("https://example.com/blog") == "blog"


def test_is_crawlable_url():
    assert is_crawlable_url("https://example.com/page")
    assert not is_crawlable_url("https://example.com/file.pdf")
    assert not is_crawlable_url("https://example.com/image.jpg")
    assert not is_crawlable_url("ftp://example.com/")


def test_extract_links():
    html = """
    <html><body>
        <a href="/about">About</a>
        <a href="https://example.com/contact">Contact</a>
        <a href="https://other.com/page">Other</a>
        <a href="#anchor">Anchor</a>
        <a href="mailto:foo@bar.com">Mail</a>
        <a href="/file.pdf">PDF</a>
    </body></html>
    """
    links = extract_links(html, "https://example.com")
    assert "https://example.com/about" in links
    assert "https://example.com/contact" in links
    assert "https://other.com/page" in links  # not filtered here; domain check is in crawler
    assert not any("#anchor" in l for l in links)
    assert not any("mailto:" in l for l in links)
    assert not any(".pdf" in l for l in links)


def test_extract_page_data_full():
    html = (
        "<html><head>"
        "<title>Getting Started | My Site</title>"
        '<meta name="description" content="Learn to use it">'
        "</head><body><h1>Getting Started</h1></body></html>"
    )
    page = extract_page_data(html, "https://example.com/start", depth=1)
    assert page.title == "Getting Started | My Site"
    assert page.description == "Learn to use it"
    assert page.h1 == "Getting Started"
    assert page.has_description
    assert page.depth == 1


def test_extract_page_data_no_meta_falls_back_to_p():
    html = (
        "<html><head><title>Page</title></head>"
        "<body><h1>Hello</h1><p>First paragraph text.</p></body></html>"
    )
    page = extract_page_data(html, "https://example.com/", depth=0)
    assert page.description == "First paragraph text."
    assert page.has_description


def test_extract_page_data_no_description():
    html = "<html><head><title>Page</title></head><body><h1>Hello</h1></body></html>"
    page = extract_page_data(html, "https://example.com/", depth=0)
    assert not page.has_description
    assert page.description is None


def test_infer_site_suffix():
    titles = [
        "Getting Started | My Site",
        "API Reference | My Site",
        "Blog | My Site",
        "Changelog | My Site",
    ]
    assert infer_site_suffix(titles) == " | My Site"


def test_infer_site_suffix_no_common():
    titles = ["Page A", "Page B - Other", "Random"]
    assert infer_site_suffix(titles) == ""


def test_clean_title():
    assert clean_title("Getting Started | My Site", " | My Site") == "Getting Started"
    assert clean_title("No Suffix Here", " | My Site") == "No Suffix Here"
