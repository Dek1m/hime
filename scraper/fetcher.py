"""Universal HTTP fetcher with HTML parsing."""

import logging
import time
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
}

# Noise tags to strip from content extraction
_STRIP_TAGS = {"nav", "footer", "header", "script", "style", "noscript", "aside", "form"}


def _extract_title(tree: HTMLParser) -> str:
    tag = tree.css_first("title")
    if tag and tag.text(strip=True):
        return tag.text(strip=True)
    tag = tree.css_first("h1")
    if tag and tag.text(strip=True):
        return tag.text(strip=True)
    return ""


def _extract_content(tree: HTMLParser) -> str:
    """Extract main text, stripping noise elements."""
    for tag in tree.css(",".join(_STRIP_TAGS)):
        tag.decompose()

    # Try search engine result snippets first (Bing: li.b_algo, Google: div.g)
    for selector in ["li.b_algo", "div.g", "div.result", "article", "main"]:
        root = tree.css_first(selector)
        if root:
            lines: list[str] = []
            for node in root.iter():
                if node.tag in ("p", "h2", "h3", "span", "div"):
                    text = node.text(strip=True)
                    if text and len(text) > 10:
                        lines.append(text)
            if lines:
                return "\n".join(lines[:20])

    # Fallback to body
    root = tree.css_first("body")
    if root is None:
        return ""

    lines: list[str] = []
    for node in root.iter():
        if node.tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th", "blockquote", "pre", "code"):
            text = node.text(strip=True)
            if text and len(text) > 2:
                lines.append(text)
    return "\n".join(lines)


def _extract_links(tree: HTMLParser, base_url: str) -> list[dict]:
    seen: set[str] = set()
    links: list[dict] = []
    for a in tree.css("a[href]"):
        href = a.attributes.get("href", "")
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        title = a.attributes.get("title", "")
        if not title:
            title = a.text(strip=True)[:200]
        links.append({"url": url, "title": title, "description": ""})
    return links


def _extract_meta_desc(tree: HTMLParser) -> str:
    tag = tree.css_first('meta[name="description"]')
    if tag:
        return tag.attributes.get("content", "")
    tag = tree.css_first('meta[property="og:description"]')
    if tag:
        return tag.attributes.get("content", "")
    return ""


def parse_html(html: str, url: str) -> dict:
    """Parse HTML and return structured data."""
    tree = HTMLParser(html)
    title = _extract_title(tree)
    content = _extract_content(tree)
    links = _extract_links(tree, url)
    desc = _extract_meta_desc(tree)

    # Fill description for first few links (top-level page links)
    if desc and links:
        for link in links[:5]:
            if not link["description"]:
                link["description"] = desc

    logger.debug("Parsed HTML: title='%s', content=%d chars, %d links", title[:50], len(content), len(links))
    return {"title": title, "content": content, "links": links}


async def fetch_url(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str = "",
    proxy: str | None = None,
    timeout: float = 15.0,
) -> dict:
    """Fetch URL and parse response.

    Returns dict with: ok, url, status, title, content, links, headers, timing_ms, error.
    """
    req_headers = {**_HEADERS, **(headers or {})}
    start = time.monotonic()

    logger.info("Fetching %s %s (proxy=%s, timeout=%s)", method, url[:100], proxy or "none", timeout)

    try:
        async with httpx.AsyncClient(
            proxy=proxy,
            timeout=timeout,
            follow_redirects=True,
            headers=req_headers,
        ) as client:
            if method == "POST":
                resp = await client.post(url, content=body)
            else:
                resp = await client.get(url)

            timing_ms = (time.monotonic() - start) * 1000
            resp_headers = dict(resp.headers)

            if resp.status_code >= 400:
                logger.warning("Fetch failed: %s %s — HTTP %d (%.0fms)", method, url[:100], resp.status_code, timing_ms)
                return {
                    "ok": False,
                    "url": str(resp.url),
                    "status": resp.status_code,
                    "headers": resp_headers,
                    "timing_ms": timing_ms,
                    "error": f"HTTP {resp.status_code}",
                }

            content_type = resp_headers.get("content-type", "")
            if "text/html" in content_type or "xhtml" in content_type:
                parsed = parse_html(resp.text, str(resp.url))
                logger.info("Fetch OK: %s %s — %d chars, %d links (%.0fms)", method, url[:100], len(parsed["content"]), len(parsed["links"]), timing_ms)
                return {
                    "ok": True,
                    "url": str(resp.url),
                    "status": resp.status_code,
                    "title": parsed["title"],
                    "content": parsed["content"],
                    "links": parsed["links"],
                    "headers": resp_headers,
                    "timing_ms": timing_ms,
                }

            # Non-HTML: return raw text
            logger.info("Fetch OK: %s %s — raw %d chars (%.0fms)", method, url[:100], len(resp.text), timing_ms)
            return {
                "ok": True,
                "url": str(resp.url),
                "status": resp.status_code,
                "content": resp.text[:50000],
                "headers": resp_headers,
                "timing_ms": timing_ms,
            }

    except httpx.TimeoutException:
        timing_ms = (time.monotonic() - start) * 1000
        logger.warning("Fetch timeout: %s %s (%.0fms)", method, url[:100], timing_ms)
        return {
            "ok": False,
            "url": url,
            "status": 0,
            "timing_ms": timing_ms,
            "error": "Timeout",
        }
    except httpx.RequestError as e:
        timing_ms = (time.monotonic() - start) * 1000
        logger.error("Fetch error: %s %s — %s (%.0fms)", method, url[:100], e, timing_ms)
        return {
            "ok": False,
            "url": url,
            "status": 0,
            "timing_ms": timing_ms,
            "error": str(e),
        }
