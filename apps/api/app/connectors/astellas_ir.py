"""Astellas public company knowledge: press releases + IR library PDFs.

Fetches the public news listing and IR library pages, follows links to press releases and
PDF presentations / financial results, and keeps only content that mentions watch terms
(e.g. ASP3082 / setidegrasib / ASP2138 / zolbetuximab). For PDFs, page-level snippets are
extracted with pypdf. Site URLs change over time, so base URLs are module constants that can
be overridden via env (ASTELLAS_NEWS_URL, ASTELLAS_IR_URLS comma-separated).
"""
from __future__ import annotations

import io
import os
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .http import RawItem, SourceUnavailable, content_hash, get_bytes, get_text, make_client, now_utc

SOURCE_KEY = "astellas_ir"
SITE = "https://www.astellas.com"
NEWS_URL = os.environ.get("ASTELLAS_NEWS_URL", f"{SITE}/en/news")
IR_URLS = [u.strip() for u in os.environ.get(
    "ASTELLAS_IR_URLS",
    f"{SITE}/en/investors/ir-library,{SITE}/en/investors/financial-results",
).split(",") if u.strip()]
DEFAULT_TERMS = ["ASP3082", "setidegrasib", "ASP2138", "zolbetuximab"]
MAX_PRESS_PAGES = 12
MAX_PDFS = 4
SNIPPET_CHARS = 400
PDF_HINTS = ("presentation", "financial", "results", "pipeline", "r&d", "earnings",
             "business", "briefing", "fy20", "q1", "q2", "q3", "q4")


class _LinkText(HTMLParser):
    """Collect <a href> links with anchor text and visible page text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._anchor: list[str] = []
        self._skip = 0
        self.text: list[str] = []
        self.title = ""
        self._in_title = False
        self.h1 = ""
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor = []
        elif tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        elif tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._anchor).split())))
            self._href = None
        elif tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False

    def handle_data(self, data):
        if self._skip:
            return
        if self._href is not None:
            self._anchor.append(data)
        if self._in_title:
            self.title += data
        if self._in_h1:
            self.h1 += data
        s = data.strip()
        if s:
            self.text.append(s)


def parse_html(html: str) -> _LinkText:
    p = _LinkText()
    p.feed(html)
    return p


def _terms_re(terms: list[str]) -> re.Pattern:
    return re.compile("|".join(re.escape(t) for t in terms if t), re.IGNORECASE)


def _is_press_link(abs_url: str) -> bool:
    u = urlparse(abs_url)
    return (u.hostname or "").endswith("astellas.com") and bool(
        re.search(r"/news/\d+|/news/[a-z0-9-]{6,}|/press-?release", u.path, re.I)
    ) and not u.path.lower().endswith(".pdf")


def _is_pdf(abs_url: str) -> bool:
    return urlparse(abs_url).path.lower().endswith(".pdf")


def _date_in(text: str) -> str | None:
    m = re.search(r"(20\d\d)[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(January|February|March|April|May|June|July|August|September|October|"
                  r"November|December) (\d{1,2}), (20\d\d)", text)
    if m:
        months = ["January", "February", "March", "April", "May", "June", "July", "August",
                  "September", "October", "November", "December"]
        return f"{m.group(3)}-{months.index(m.group(1)) + 1:02d}-{int(m.group(2)):02d}"
    return None


def snippets(text: str, rx: re.Pattern, width: int = SNIPPET_CHARS) -> list[str]:
    out = []
    flat = " ".join(text.split())
    for m in rx.finditer(flat):
        a = max(0, m.start() - width // 2)
        s = flat[a:a + width]
        if not out or s[:60] not in out[-1]:
            out.append(s)
        if len(out) >= 5:
            break
    return out


def press_item(url: str, html: str, rx: re.Pattern) -> RawItem | None:
    p = parse_html(html)
    body = " ".join(p.text)
    hits = snippets(body, rx)
    if not hits:
        return None
    title = (p.h1 or p.title or url).strip()
    terms = sorted({m.group(0).upper() for m in rx.finditer(body)})
    d = {"url": url, "title": title, "date": _date_in(body[:3000]), "snippets": hits,
         "terms": terms, "type": "press_release"}
    return RawItem(source_key=SOURCE_KEY, external_id=url, url=url, title=title,
                   published_at=d["date"], kind="company_ir",
                   text=" ".join([title] + hits), data=d, retrieved_at=now_utc(),
                   content_hash=content_hash(d))


def pdf_pages(pdf_bytes: bytes) -> list[str]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for pg in reader.pages:
        try:
            pages.append(pg.extract_text() or "")
        except Exception:  # noqa: BLE001 - malformed page, keep going
            pages.append("")
    return pages


def pdf_item(url: str, anchor: str, pdf_bytes: bytes, rx: re.Pattern) -> RawItem | None:
    try:
        pages = pdf_pages(pdf_bytes)
    except Exception as e:  # noqa: BLE001
        raise SourceUnavailable(SOURCE_KEY, urlparse(url).hostname or url,
                                f"PDF parse failed: {e}") from e
    page_hits = []
    for i, txt in enumerate(pages, start=1):
        for s in snippets(txt, rx)[:2]:
            page_hits.append({"page": i, "snippet": s})
    if not page_hits:
        return None
    title = anchor or urlparse(url).path.rsplit("/", 1)[-1]
    terms = sorted({m.group(0).upper() for h in page_hits for m in rx.finditer(h["snippet"])})
    d = {"url": url, "title": title, "type": "ir_pdf", "pages": len(pages),
         "page_hits": page_hits[:15], "terms": terms, "date": _date_in(title + " " + url)}
    return RawItem(source_key=SOURCE_KEY, external_id=url,
                   url=f"{url}#page={page_hits[0]['page']}", title=f"Astellas IR: {title}",
                   published_at=d["date"], kind="company_ir",
                   text=" ".join([title] + [h["snippet"] for h in page_hits]), data=d,
                   retrieved_at=now_utc(), content_hash=content_hash(d))


async def fetch(terms: list[str] | None = None,
                client: httpx.AsyncClient | None = None) -> list[RawItem]:
    terms = [t for t in (terms or DEFAULT_TERMS) if t]
    rx = _terms_re(terms)
    own = client is None
    c = client or make_client()
    try:
        items: list[RawItem] = []
        # 1) press releases (listing failure = source unreachable)
        listing = parse_html(await get_text(SOURCE_KEY, NEWS_URL, client=c))
        seen: set[str] = set()
        press: list[tuple[str, str]] = []
        for href, anchor in listing.links:
            if not href:
                continue
            u = urljoin(NEWS_URL, href).split("#")[0]
            if u in seen or not _is_press_link(u):
                continue
            seen.add(u)
            press.append((u, anchor))
        # term-matching anchors first, then most recent (listing order)
        press.sort(key=lambda x: 0 if rx.search(x[1] or "") else 1)
        for u, _a in press[:MAX_PRESS_PAGES]:
            try:
                it = press_item(u, await get_text(SOURCE_KEY, u, client=c), rx)
            except SourceUnavailable:
                continue  # one broken article does not invalidate the listing
            if it:
                items.append(it)
        # 2) IR library PDFs
        pdfs: list[tuple[str, str]] = []
        ir_errors = []
        for ir_url in IR_URLS:
            try:
                page = parse_html(await get_text(SOURCE_KEY, ir_url, client=c))
            except SourceUnavailable as e:
                ir_errors.append(e)
                continue
            for href, anchor in page.links:
                if not href:
                    continue
                u = urljoin(ir_url, href).split("#")[0]
                if _is_pdf(u) and u not in seen:
                    seen.add(u)
                    pdfs.append((u, anchor))
        if ir_errors and len(ir_errors) == len(IR_URLS) and not items:
            raise ir_errors[0]

        def _prio(x: tuple[str, str]) -> int:
            s = (x[1] + " " + x[0]).lower()
            if rx.search(s):
                return 0
            return 1 if any(h in s for h in PDF_HINTS) else 2

        pdfs.sort(key=_prio)
        for u, anchor in pdfs[:MAX_PDFS]:
            try:
                it = pdf_item(u, anchor, await get_bytes(SOURCE_KEY, u, client=c), rx)
            except SourceUnavailable:
                continue
            if it:
                items.append(it)
        return items
    finally:
        if own:
            await c.aclose()
