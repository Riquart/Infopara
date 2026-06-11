"""Auto-detect RSS feeds and HTML article selectors from a URL."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger
from selectolax.parser import HTMLParser

USER_AGENT = "InfoPara/1.0 (+contact: benoit.riquart@cgm.com)"
TIMEOUT = 15.0

# Common RSS path suffixes to probe
RSS_PROBE_PATHS = [
    "/feed/", "/feed", "/rss.xml", "/rss", "/atom.xml", "/atom",
    "/feed/rss/", "/feeds/posts/default", "/blog/feed/", "/actualites/feed/",
    "/news/feed/", "/wp-json/feed/", "/?feed=rss2",
]

RSS_MIME_TYPES = {"application/rss+xml", "application/atom+xml", "text/xml", "application/xml"}


@dataclass
class DetectionResult:
    url: str                          # original URL submitted
    feed_url: Optional[str] = None    # RSS/Atom URL found, or None
    kind: str = "html"                # "rss" or "html"
    site_title: Optional[str] = None
    # HTML-mode hints
    selector_hint: Optional[str] = None
    title_sel_hint: Optional[str] = None
    link_sel_hint: Optional[str] = None
    date_sel_hint: Optional[str] = None
    summary_sel_hint: Optional[str] = None
    sample_titles: List[str] = field(default_factory=list)
    error: Optional[str] = None


def detect(url: str) -> DetectionResult:
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    result = DetectionResult(url=url)

    try:
        with httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
            follow_redirects=True,
        ) as client:
            # Fetch the page
            resp = client.get(url)
    except httpx.RequestError as exc:
        result.error = f"Impossible de joindre l'URL : {exc}"
        return result

    if resp.status_code >= 400:
        result.error = f"HTTP {resp.status_code}"
        return result

    html = resp.text
    final_url = str(resp.url)

    result.site_title = _extract_title(html)

    # 1. Check if the URL itself is already a feed
    content_type = resp.headers.get("content-type", "")
    if any(m in content_type for m in ("rss", "atom", "xml")):
        result.feed_url = final_url
        result.kind = "rss"
        return result

    # 2. Look for <link rel="alternate" type="application/rss+xml"> in HTML
    feed_url = _find_feed_in_html(html, final_url)
    if feed_url:
        result.feed_url = feed_url
        result.kind = "rss"
        return result

    # 3. Probe common RSS paths
    base = f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}"
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=8.0, follow_redirects=True) as client:
        for path in RSS_PROBE_PATHS:
            probe_url = base + path
            try:
                r = client.head(probe_url)
                ct = r.headers.get("content-type", "")
                if r.status_code == 200 and any(m in ct for m in ("rss", "atom", "xml")):
                    result.feed_url = probe_url
                    result.kind = "rss"
                    return result
                # Some servers return text/html even for feeds — try GET
                if r.status_code == 200:
                    r2 = client.get(probe_url)
                    ct2 = r2.headers.get("content-type", "")
                    if any(m in ct2 for m in ("rss", "atom", "xml")):
                        result.feed_url = probe_url
                        result.kind = "rss"
                        return result
                    # Check if the body looks like XML/RSS
                    snippet = r2.text[:500]
                    if "<rss" in snippet or "<feed" in snippet or "<channel>" in snippet:
                        result.feed_url = probe_url
                        result.kind = "rss"
                        return result
            except httpx.RequestError:
                continue

    # 4. Fall back to HTML scraping — guess selectors
    result.kind = "html"
    _guess_html_selectors(html, final_url, result)
    return result


def _extract_title(html: str) -> Optional[str]:
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    return m.group(1).strip() if m else None


def _find_feed_in_html(html: str, base_url: str) -> Optional[str]:
    tree = HTMLParser(html)
    for node in tree.css('link[rel="alternate"]'):
        ct = node.attributes.get("type", "")
        href = node.attributes.get("href", "")
        if href and any(m in ct for m in ("rss", "atom")):
            return urljoin(base_url, href)
    # Also check <a> tags pointing to feed URLs
    for node in tree.css("a[href]"):
        href = node.attributes.get("href", "")
        if href and re.search(r"/(feed|rss|atom)(/|\.xml)?$", href, re.I):
            return urljoin(base_url, href)
    return None


def _guess_html_selectors(html: str, base_url: str, result: DetectionResult) -> None:
    tree = HTMLParser(html)

    # Common article container candidates, in priority order
    container_candidates = [
        "article",
        ".post", ".entry", ".news-item", ".actualite",
        "[class*='article']", "[class*='post-item']",
        "li.post", "div.post",
    ]

    best_sel: Optional[str] = None
    best_nodes = []

    for sel in container_candidates:
        try:
            nodes = tree.css(sel)
        except Exception:
            continue
        if len(nodes) >= 2:
            best_sel = sel
            best_nodes = nodes
            break

    if not best_sel:
        result.selector_hint = "article"
        result.title_sel_hint = "h2, h3"
        result.link_sel_hint = "a"
        result.date_sel_hint = "time, .date"
        result.summary_sel_hint = "p"
        return

    result.selector_hint = best_sel

    # Try to find title/link/date/summary selectors from sample nodes
    sample = best_nodes[:3]

    # Title + link
    for title_sel in ("h2 a", "h3 a", "h1 a", "h2", "h3", ".title a", ".entry-title a"):
        found = [n.css_first(title_sel) for n in sample if n.css_first(title_sel)]
        if len(found) >= 2:
            texts = [f.text(strip=True)[:80] for f in found if f.text(strip=True)]
            if texts:
                result.title_sel_hint = title_sel
                result.sample_titles = texts[:3]
                # Extract href
                href_node = found[0]
                href = href_node.attributes.get("href", "")
                if href:
                    result.link_sel_hint = title_sel
                break

    if not result.title_sel_hint:
        result.title_sel_hint = "h2, h3"
        result.link_sel_hint = "a"

    if not result.link_sel_hint:
        result.link_sel_hint = "a"

    # Date
    for date_sel in ("time[datetime]", "time", "[class*='date']", "[class*='Date']", ".meta"):
        found = [n.css_first(date_sel) for n in sample if n.css_first(date_sel)]
        if found:
            result.date_sel_hint = date_sel
            break
    if not result.date_sel_hint:
        result.date_sel_hint = "time, .date"

    # Summary
    for summary_sel in (".excerpt", ".entry-summary", "p.summary", "p"):
        found = [n.css_first(summary_sel) for n in sample if n.css_first(summary_sel)]
        if found:
            result.summary_sel_hint = summary_sel
            break
    if not result.summary_sel_hint:
        result.summary_sel_hint = "p"
