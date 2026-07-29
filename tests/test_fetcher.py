"""Tests for scraper/fetcher.py — HTML parsing and URL fetching."""

import pytest
from hime.scraper.fetcher import parse_html, _extract_title, _extract_content, _extract_links


class TestExtractTitle:
    def test_title_from_title_tag(self):
        html = "<html><head><title>My Page</title></head><body></body></html>"
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        assert _extract_title(tree) == "My Page"

    def test_title_from_h1_fallback(self):
        html = "<html><body><h1>First Heading</h1></body></html>"
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        assert _extract_title(tree) == "First Heading"

    def test_empty_when_no_title(self):
        html = "<html><body></body></html>"
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        assert _extract_title(tree) == ""


class TestExtractContent:
    def test_basic_paragraphs(self):
        html = "<html><body><p>Hello world</p><p>Second paragraph</p></body></html>"
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        content = _extract_content(tree)
        assert "Hello world" in content
        assert "Second paragraph" in content

    def test_strips_nav_footer(self):
        html = "<html><body><nav>Menu</nav><p>Main content</p><footer>Footer</footer></body></html>"
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        content = _extract_content(tree)
        assert "Menu" not in content
        assert "Footer" not in content
        assert "Main content" in content

    def test_prefers_article(self):
        html = "<html><body><nav>Nav</nav><article><p>Article text</p></article></body></html>"
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        content = _extract_content(tree)
        assert "Article text" in content
        assert "Nav" not in content


class TestExtractLinks:
    def test_extracts_links(self):
        html = '<html><body><a href="https://example.com">Example</a></body></html>'
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        links = _extract_links(tree, "https://test.com")
        assert len(links) == 1
        assert links[0]["url"] == "https://example.com"
        assert links[0]["title"] == "Example"

    def test_skips_anchors(self):
        html = '<html><body><a href="#section">Section</a><a href="https://real.com">Real</a></body></html>'
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        links = _extract_links(tree, "https://test.com")
        assert len(links) == 1
        assert links[0]["url"] == "https://real.com"

    def test_deduplicates(self):
        html = '<html><body><a href="https://same.com">A</a><a href="https://same.com">B</a></body></html>'
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        links = _extract_links(tree, "https://test.com")
        assert len(links) == 1


class TestParseHtml:
    def test_full_parse(self):
        html = """
        <html>
        <head><title>Test Page</title></head>
        <body>
            <h1>Main Title</h1>
            <p>This is the main content of the page.</p>
            <a href="https://example.com">Example Link</a>
        </body>
        </html>
        """
        result = parse_html(html, "https://test.com")
        assert result["title"] == "Test Page"
        assert "Main Title" in result["content"]
        assert "main content" in result["content"]
        assert len(result["links"]) == 1
        assert result["links"][0]["url"] == "https://example.com"


@pytest.mark.asyncio
class TestFetchUrl:
    async def test_fetch_google(self):
        """Test fetching a real page."""
        from hime.scraper.fetcher import fetch_url
        result = await fetch_url("https://www.google.com", timeout=10.0)
        assert result["ok"] is True
        assert result["status"] == 200
        assert result["title"] != ""
        assert len(result["content"]) > 0

    async def test_fetch_nonexistent(self):
        """Test fetching a non-existent URL."""
        from hime.scraper.fetcher import fetch_url
        result = await fetch_url("https://this-does-not-exist-12345.com", timeout=5.0)
        assert result["ok"] is False
        assert result["error"] != ""

    async def test_fetch_returns_links(self):
        """Test that links are extracted."""
        from hime.scraper.fetcher import fetch_url
        result = await fetch_url("https://www.example.com", timeout=10.0)
        assert result["ok"] is True
        assert isinstance(result["links"], list)
