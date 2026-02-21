"""Extract structured data from a rendered Playwright page."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin, parse_qs

from bs4 import BeautifulSoup
from playwright.async_api import Page


@dataclass
class ExtractedPage:
    url: str
    guid: str | None
    title: str
    content: str
    links: list[tuple[str, str]] = field(default_factory=list)  # (href, text)


# CSS selectors tried in priority order
TITLE_SELECTORS = [
    "h1.co_heading",
    ".co_title",
    "h1.document-title",
    ".documentTitle",
    "h1",
    "h2",
]

CONTENT_SELECTORS = [
    ".co_document",       # Full regulation text on Document/FullText pages
    ".co_contentBlock",   # TOC listing on Browse pages
    "article",
    "main",
    '[role="main"]',
    ".content",
    "#content",
    ".regulation-text",
]

# Elements to strip before extracting text
STRIP_SELECTORS = [
    "nav", "header", "footer", "script", "style", "noscript",
    ".co_breadcrumb", ".co_toolbar", ".co_navigation",
    ".co_header", ".co_footer", ".co_sidebar",
    "[aria-hidden='true']",
]

# Only follow links matching this domain + path prefix
ALLOWED_DOMAIN = "shared-govt.westlaw.com"
ALLOWED_PATH_PREFIX = "/calregs/"


def _extract_guid(url: str) -> str | None:
    parsed = urlparse(url)
    # Browse URLs: ?guid=XXXX
    qs = parse_qs(parsed.query)
    if qs.get("guid"):
        return qs["guid"][0]
    # Document URLs: /calregs/Document/XXXX  (GUID is last path segment)
    parts = parsed.path.rstrip("/").split("/")
    if len(parts) >= 2 and parts[-2].lower() == "document":
        return parts[-1]
    return None


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def extract_page(page: Page, base_url: str) -> ExtractedPage:
    html = await page.content()
    soup = BeautifulSoup(html, "html.parser")
    current_url = page.url or base_url
    guid = _extract_guid(current_url)

    # ── Extract links from the FULL soup BEFORE stripping anything ────────────
    # Navigation panels (co_navigation) contain the section-level links
    # (§ 1950, § 1952, etc.) that lead to actual regulation text. If we strip
    # first, those links are lost and section pages are never crawled.
    links: list[tuple[str, str]] = []
    seen_hrefs: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#"):
            continue
        full_url = urljoin(current_url, href)
        parsed = urlparse(full_url)
        if parsed.netloc != ALLOWED_DOMAIN:
            continue
        if not parsed.path.startswith(ALLOWED_PATH_PREFIX):
            continue
        # Normalise: strip fragment
        normalised = full_url.split("#")[0]
        if normalised in seen_hrefs:
            continue
        # Only follow links with an extractable GUID — keeps us within CARB
        # content. Browse pages have ?guid=XXXX; Document/section pages embed
        # the GUID in the path as /calregs/Document/XXXX.
        if not _extract_guid(normalised):
            continue
        seen_hrefs.add(normalised)
        link_text = _clean_text(a.get_text()) or normalised
        # Skip "Title X." links — these go UP to a parent Title page, which
        # then links out to all other Divisions (e.g. Division 1 DMV, Division 2
        # CHP) that are outside Division 3 Air Resources Board scope.
        if re.match(r'^Title\s+\d+', link_text, re.IGNORECASE):
            continue
        links.append((normalised, link_text))

    # ── Strip noisy elements for content extraction only ──────────────────────
    for sel in STRIP_SELECTORS:
        for el in soup.select(sel):
            el.decompose()

    # Extract title
    title = ""
    for sel in TITLE_SELECTORS:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            title = _clean_text(el.get_text())
            break
    if not title:
        tag = soup.find("title")
        title = _clean_text(tag.get_text()) if tag else "Untitled"

    # Extract main content
    content = ""
    for sel in CONTENT_SELECTORS:
        el = soup.select_one(sel)
        if el:
            raw = el.get_text(separator="\n")
            cleaned = _clean_text(raw)
            if len(cleaned) > 50:  # meaningful content threshold
                content = cleaned
                break

    # Fallback: body text
    if not content:
        body = soup.find("body")
        if body:
            content = _clean_text(body.get_text(separator="\n"))[:5000]

    # Strip leading breadcrumb noise ("Home Title 13. Motor Vehicles Division 3...")
    # Find the first § section marker and start content from there;
    # for TOC pages with no §, strip just the "Home ..." first line.
    if content.startswith('Home '):
        sec_match = re.search(r'(?=§\s*\d)', content)
        if sec_match:
            content = content[sec_match.start():].strip()
        else:
            content = re.sub(r'^Home[^\n]+\n?', '', content).strip()

    return ExtractedPage(
        url=current_url,
        guid=guid,
        title=title,
        content=content,
        links=links,
    )
