"""Public page reader fallback for property websites that refuse automated reading.

When the building's own public page gives no usable plan images (the site refuses our fetcher, or loads plans with
scripts), the SAME public page URL can be read through a public page-to-Markdown reader: Jina Reader's default
anonymous route, `GET https://r.jina.ai/<public page URL>`. This is deterministic page reading, not a model: no
image captions, OCR or generated text are requested, and no API key, cookies, proxies, custom agents or CAPTCHA
solving are used. Turn it off with FURNISHAI_PUBLIC_READER=off.

Privacy/safety, enforced in code:
- Only a public building page is ever sent: the target must pass the SafeFetcher URL + DNS checks (no localhost,
  private or metadata addresses, credentials or odd ports) and must not be a sign-in/applicant/resident/payment/auth
  page, a unit-specific page or carry secret-looking query parameters. Unit labels, photos and cookies never are.
- The reader request itself goes through a SafeFetcher; every hop must stay on https://r.jina.ai. Bytes, time and
  the number of reads per lookup are capped.
- The reply must be the reader's format for THAT site (its "URL Source" on the same site as the target); challenge,
  login or error pages are rejected. The reader host is never recorded as the plan's source.
- Everything in the reply is untrusted evidence. Image URLs found in it are fetched later only through the normal
  SafeFetcher plan-image import (SSRF, redirects, media type and pixel limits unchanged).
Whether the reader served a fresh or cached copy is unknown; its "Published Time" is recorded when given.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlsplit

from .safe_fetch import FetchBlocked, FetchFailed, FetchResult, Opener, Resolver, SafeFetcher, validate_url

READER_PREFIX = "https://r.jina.ai/"
READER_HOST = "r.jina.ai"
READER_NAME = "Jina Reader (r.jina.ai), public anonymous route"
READER_METHOD = "public-reader-v1"
READER_TYPES = ("text/plain", "text/markdown")
MAX_READER_BYTES = 2_000_000
READER_TIMEOUT_S = 25.0
MAX_READER_PAGES = 3  # the selected page + at most 2 floor-plan links observed in its reader text
MAX_READER_PLANS = 40


class ReaderRejected(Exception):
    """The reader replied, but not with a usable copy of the requested public page."""


class ReaderRateLimited(Exception):
    """The reader's free tier refused for now (HTTP 429)."""


# ------------------------------------------------------------------ what may be sent to the reader
_PRIVATE_PATH = re.compile(
    r"(?i)/(?:log-?in|sign-?in|sign-?up|register|apply|application|applicants?|portal|residents?|account|my-account|"
    r"payments?|pay|auth|oauth2?|sso|checkout|cart|guestlogin|userlogin|residentservices|onlineleasing|admin|wp-admin)"
    r"(?:[/?#._-]|$)")
_PRIVATE_HOST_LABEL = {"portal", "login", "account", "accounts", "resident", "residents", "my", "pay", "auth", "sso", "secure",
                       "securecafe", "applicant", "apply"}
_UNIT_PATH = re.compile(r"(?i)/(?:units?|apartments?|apt|suites?)/(?:#?\d{2,}[a-z]?|[a-z]?\d{3,}[a-z]?)(?:/|$)")
_SECRET_KEY = re.compile(r"(?i)token|secret|key|sig|auth|session|sid$|pass|pwd|code|email|phone|user|lead|ticket|nonce|jwt|"
                         r"otp|unit|apt|login|redirect|return")


def reader_target_problem(url: str, resolver: Resolver) -> str | None:
    """Why `url` must NOT be sent to the public reader, or None if it's a plain public page."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return "not a valid web address"
    if parts.scheme not in ("http", "https") or parts.username or parts.password or "@" in parts.netloc:
        return "only plain public http(s) pages are read"
    if port not in (None, 80, 443):
        return "only default web ports are read"
    host = (parts.hostname or "").lower()
    if host == READER_HOST:
        return "already a reader address"
    full = unquote(url)
    if _PRIVATE_PATH.search(full) or set(host.split(".")[:-1]) & _PRIVATE_HOST_LABEL or "securecafe" in host:
        return "sign-in, application, resident, account and payment pages are never sent to the reader"
    if _UNIT_PATH.search(parts.path or ""):
        return "unit-specific pages are never sent to the reader"
    if len(parts.query) > 200 or any(_SECRET_KEY.search(k) for k, _ in parse_qsl(parts.query, keep_blank_values=True)):
        return "addresses with private-looking query parameters are never sent to the reader"
    try:
        validate_url(url.strip(), resolver)
    except FetchBlocked as exc:
        return f"not a public address ({exc})"
    except FetchFailed as exc:
        return str(exc)
    return None


def _reader_hop(url: str) -> str | None:
    p = urlsplit(url)
    if p.scheme != "https" or (p.hostname or "").lower() != READER_HOST or p.username or p.port not in (None, 443):
        return "the reader redirected outside r.jina.ai"
    return None


# ------------------------------------------------------------------ reader reply
# Bot challenges of any kind (Cloudflare, AWS WAF, Anubis proof-of-work, CAPTCHAs...). They are REJECTED, never
# executed, solved or retried with other headers or proxies.
_CHALLENGE = re.compile(r"(?i)just a moment\.\.\.|attention required|access denied|verify (?:that )?you are (?:a )?human|"
                        r"captcha|are you a robot|enable javascript and cookies|request blocked|403 forbidden|"
                        r"cloudflare ray id|checking your browser|unusual traffic|not a (?:ro)?bot|\banubis\b|"
                        r"proof[- ]of[- ]work|awswaf|aws waf|verify (?:that )?you(?:'|’)?re not a robot")
_LOGIN_TITLE = re.compile(r"(?i)^\s*(?:log ?in|sign ?in|resident login|applicant login)\b")
_WARN_BAD = re.compile(r"(?i)\b(?:40[13]|429|45[01]|5\d\d)\b|captcha|blocked|forbidden|error")


@dataclass
class ReaderPage:
    target_url: str
    reader_url: str
    title: str
    url_source: str
    published_time: str | None
    markdown: str
    fetch: FetchResult

    def meta(self) -> dict:
        return {"service": READER_NAME, "method": READER_METHOD, "reader_url": self.reader_url, "target_url": self.target_url,
                "url_source": self.url_source, "title": self.title[:200], "published_time": self.published_time,
                "retrieved_at": self.fetch.retrieved_at, "sha256": self.fetch.sha256, "bytes": len(self.fetch.body),
                "cache_age": "unknown"}


def parse_reader_reply(res: FetchResult, target: str) -> ReaderPage:
    from .sources import same_site

    text = res.body.decode("utf-8", "replace")
    head, sep, body = text.partition("Markdown Content:")
    if not sep or len(head) > 6000:
        raise ReaderRejected("the reader's reply isn't in its page format")
    fields: dict[str, str] = {}
    warnings: list[str] = []
    for line in head.splitlines():
        k, colon, v = line.partition(":")
        if not colon:
            continue
        k, v = k.strip().lower(), v.strip()
        if k == "warning":
            warnings.append(v)
        elif k in ("title", "url source", "published time") and k not in fields:
            fields[k] = v
    source = fields.get("url source", "")
    if not source.startswith(("https://", "http://")) or not same_site(source, target):
        raise ReaderRejected("the reader returned a different website than the one requested")
    if any(_WARN_BAD.search(w) for w in warnings):
        raise ReaderRejected("the reader couldn't read the page either (" + warnings[0][:120] + ")")
    title = fields.get("title", "")
    if _LOGIN_TITLE.search(title) or _CHALLENGE.search(title + " " + body[:1500]):
        raise ReaderRejected("the reader got a sign-in or bot-check page, not the public page")
    if len(body.strip()) < 40:
        raise ReaderRejected("the reader's copy of the page is empty")
    return ReaderPage(target, res.final_url, title, source, fields.get("published time") or None, body, res)


class PublicReader:
    """Bounded public page reader. `resolver`/`opener` are the app's (fake in tests), so no hidden network use.
    Recent replies are reused for a few minutes (in memory only), so checking a building's page and then looking up
    its plans costs one reader request, not two."""

    CACHE_S = 900
    CACHE_MAX = 32

    def __init__(self, resolver: Resolver, opener: Opener, timeout_s: float = READER_TIMEOUT_S, clock=None):
        import threading
        import time

        self.resolver = resolver
        self.fetcher = SafeFetcher(resolver=resolver, opener=opener, max_redirects=2, timeout_s=timeout_s)
        self._clock = clock or time.monotonic
        self._cache: dict[str, tuple[float, ReaderPage]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_fetcher(cls, f: SafeFetcher) -> "PublicReader":
        return cls(f.resolver, f.opener)

    def read(self, target: str) -> ReaderPage:
        target = target.strip().split("#", 1)[0]
        why = reader_target_problem(target, self.resolver)
        if why:
            raise FetchBlocked(why)
        with self._lock:
            hit = self._cache.get(target)
            if hit and self._clock() - hit[0] < self.CACHE_S:
                return hit[1]
        try:
            res = self.fetcher.fetch(READER_PREFIX + target, allowed_types=READER_TYPES, max_bytes=MAX_READER_BYTES,
                                     url_guard=_reader_hop)
        except FetchBlocked as exc:  # e.g. a reader redirect off r.jina.ai: refused before connecting
            raise ReaderRejected(str(exc)) from exc
        except FetchFailed as exc:
            if "HTTP 429" in str(exc):
                raise ReaderRateLimited("the public reader is rate-limiting requests right now; try again later") from exc
            raise
        page = parse_reader_reply(res, target)
        with self._lock:
            if len(self._cache) >= self.CACHE_MAX:
                self._cache.pop(min(self._cache, key=lambda k: self._cache[k][0]))
            self._cache[target] = (self._clock(), page)
        return page


# ------------------------------------------------------------------ Markdown scanning (balanced brackets/parentheses)
def _bracket(s: str, i: int) -> tuple[str | None, int]:
    """s[i] == '[': (inner text, index after the matching ']') or (None, i)."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "[":
            depth += 1
        elif s[j] == "]":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
    return None, i


def _paren(s: str, i: int) -> tuple[str | None, int]:
    """s[i] == '(': (URL, index after the closing ')'). Parentheses inside the URL are balanced, so
    ".../517_plan_s(1).png" is kept whole; an optional "title" after a space is skipped."""
    depth, j, url = 0, i + 1, None
    while j < len(s):
        ch = s[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                url = url if url is not None else s[i + 1:j]
                return url.strip() or None, j + 1
            depth -= 1
        elif ch.isspace() and depth == 0 and url is None:
            url = s[i + 1:j]
        j += 1
    return None, i


def scan_line(line: str) -> list[tuple[str, str, str]]:
    """[("image", alt, url) | ("link", text, url)] in order; images inside link text are included."""
    out: list[tuple[str, str, str]] = []
    i = 0
    while i < len(line):
        if line.startswith("![", i):
            alt, j = _bracket(line, i + 1)
            if alt is not None and line.startswith("(", j):
                url, k = _paren(line, j)
                if url:
                    out.append(("image", alt, url))
                    i = k
                    continue
            i += 2
            continue
        if line[i] == "[":
            text, j = _bracket(line, i)
            if text is not None and line.startswith("(", j):
                url, k = _paren(line, j)
                if url:
                    inner = scan_line(text)
                    out.extend(t for t in inner if t[0] == "image")
                    out.append(("link", _strip_images(text), url))
                    i = k
                    continue
        i += 1
    return out


def _strip_images(text: str) -> str:
    """Link text without its embedded image markup (balanced, so "…/a(1).png" doesn't leave fragments)."""
    out, i = [], 0
    while i < len(text):
        if text.startswith("![", i):
            alt, j = _bracket(text, i + 1)
            if alt is not None and text.startswith("(", j):
                url, k = _paren(text, j)
                if url:
                    i = k
                    continue
        out.append(text[i])
        i += 1
    return "".join(out).strip()


_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_OTHER_PROPS = re.compile(r"(?i)\b(?:similar|nearby|other|related|more)\s+(?:properties|communities|apartments|buildings|listings|rentals)\b|"
                          r"you may also like|people also viewed")
_HEADING_NOT_PLAN = re.compile(r"(?i)\b(?:apartments|homes|living|luxury|community|downtown|neighborhood|amenit\w*|available|"
                               r"floor\s*plans|filters?|video|tour|gallery|photos?|contact|address|specials?)\b|,|&")
_IMG_PREFIX = re.compile(r"(?i)^\s*image\s+\d+\s*:\s*")


# Words that describe a plan TYPE or price, not an individual plan: "2 bedroom From", "Studio", "1 Bed 1 Bath $2,100".
_TYPE_WORDS = re.compile(r"(?i)\b(?:studios?|efficiency|\d+(?:\.\d)?\s*(?:bed(?:room)?s?|br|bd|bath(?:room)?s?|ba)|bed(?:room)?s?|"
                         r"bath(?:room)?s?|from|starting|at|and|with|plus|den|loft|apartments?|plans?|floor|the|furnished|"
                         r"total|price|rent|per|month|mo|available|now)\b|\$[\d,.]+|[•|·,&/–—:()+-]")
_PLAN_ID = re.compile(r"(?i)\b(?:[a-z]{1,3}\d{0,3}[a-z]?|\d{1,4}[a-z]?)\b")


def is_plan_heading(h: str) -> bool:
    """A short heading that names ONE unit plan ("Studio S", "1 Bedroom 1 Bath R", "Plan B2", "3 Bed 2 Bath PH-G"),
    not a page/section heading ("Studio, 1, 2 & 3-Bedroom Apartments in …", "Floor Plans", "Unit Video") and not a
    type or price category ("2 bedroom From", "Studio"): an individual plan has its own letter/number designator."""
    from .sources import _PHOTO_WORDS, _UNIT_CODE, plan_type

    if not h or len(h) > 48 or _HEADING_NOT_PLAN.search(h) or _PHOTO_WORDS.search(h):
        return False
    if not (plan_type(h) or _UNIT_CODE.search(h) or re.search(r"(?i)\bplan\s+[a-z]{0,3}\d{0,3}[a-z]?\b", h)):
        return False
    return bool(_UNIT_CODE.search(h) or _PLAN_ID.search(_TYPE_WORDS.sub(" ", h)))


_GENERIC_ALT = re.compile(r"(?i)^\s*(?:floor[\s_-]?plan|plan|image|photo|picture|unit|layout)?\s*$")
_LINK_MD = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def _type_hint(lines: list[str], i: int) -> str | None:
    """The plan-type words in the listing text right AFTER an image (e.g. AVA-style cards: image, then a unit
    heading, then "Studio • 1 bath • 628 sqft"). Only type words are kept; sizes are never used."""
    from .sources import plan_type

    seen = 0
    for line in lines[i + 1:i + 9]:
        t = _LINK_MD.sub(r"\1", line).strip().lstrip("#").strip()
        if not t:
            continue
        if line.lstrip().startswith("![") or seen >= 5:  # card badges ("Special", "Available to Tour") may come first
            break
        seen += 1
        if plan_type(t):
            parts = [p.strip() for p in re.split(r"[•|·]", t) if re.search(r"(?i)studio|efficiency|\bbed|\bbath|\bbr\b", p)]
            return " • ".join(parts)[:40] or None
    return None


def _file_stem(url: str) -> str:
    """The image file's own name, even when the URL continues after it ("…/s8-628sf-apt264.jpg/1024/768")."""
    from urllib.parse import unquote

    segs = [unquote(x) for x in urlsplit(url).path.split("/") if x]
    named = [x for x in segs if re.search(r"(?i)\.(?:jpe?g|png|webp|gif|svg)$", x)]
    stem = (named[-1] if named else (segs[-1] if segs else "")).rsplit(".", 1)[0]
    return "" if re.fullmatch(r"[\d._-]*", stem) else stem[:60]


def reader_plans(md: str, page_url: str) -> tuple[list[dict], list[tuple[str, str]], list[dict]]:
    """(plan image candidates, same-site links, unsupported plan files) from a reader Markdown copy of `page_url`.

    A plan image is named or labelled as a floor plan itself (always recognized), or sits under a heading that names
    one individual plan (at most 2 per heading). Its NAME comes from that heading; otherwise from the plan-type words
    right after it plus its file name. The image's own alt text is kept as raw provenance (it can be wrong, e.g. a
    "Studio S" section whose image alt says "1 bedroom"). Logos, icons, banners, photos, price/type category headings
    and anything after a "similar/nearby properties" heading don't count. SVG plan drawings are reported as
    unsupported (this build can't import them). Square footage is never turned into geometry."""
    from .research import public_url_ok
    from .sources import _NO_CRAWL, _NOT_PLAN, _PHOTO_WORDS, _PLAN_IMG, _classify_image, plan_type, same_site

    images: list[dict] = []
    links: list[tuple[str, str]] = []
    unsupported: list[dict] = []
    heading, plan_heading, per_heading, stop = "", False, 0, False
    lines = md.splitlines()
    for i, line in enumerate(lines):
        m = _HEADING.match(line)
        if m:
            heading = re.sub(r"[*_`]", "", _LINK_MD.sub(r"\1", m.group(2))).strip()
            if _OTHER_PROPS.search(heading):
                stop = True
            plan_heading, per_heading = is_plan_heading(heading), 0
        if stop:
            continue
        for kind, text, url in scan_line(line):
            if kind == "link":
                if (url.startswith("https://") and same_site(url, page_url) and not _NO_CRAWL.search(url)
                        and len(links) < 60 and (url, text) not in links):
                    links.append((url.split("#", 1)[0], text[:120]))
                continue
            alt = _IMG_PREFIX.sub("", text).strip()
            if not url.startswith("https://") or not public_url_ok(url):
                continue
            path = urlsplit(url).path.lower()
            if path.endswith(".svg"):
                if (not re.search(r"(?i)logo|icon|sprite|badge|social", url + " " + alt)
                        and (_PLAN_IMG.search(alt) or plan_heading) and len(unsupported) < 40):
                    unsupported.append({"url": url, "alt": alt[:200], "heading": heading[:120] or None})
                continue
            if _NOT_PLAN.search(url) or _NOT_PLAN.search(alt) or _PHOTO_WORDS.search(alt):
                continue
            hit = _classify_image(url, alt, plan_heading)
            strong = hit is not None and hit[0] in ("named_floor_plan", "unit_size_label", "unit_code_label")
            if plan_heading and (strong or per_heading < 2):
                per_heading += 1
                label = f"Under the page’s plan heading “{heading}” (likely a plan; check it)"
                alt_type, head_type = plan_type(alt), plan_type(heading)
                if alt_type and head_type and alt_type != head_type:
                    label += f". The image’s own description (“{alt[:80]}”) disagrees; the heading is used"
                images.append({"url": url, "name": heading[:120], "heading": heading[:120], "alt": alt[:200],
                               "kind": hit[0] if strong else "plan_heading_label", "label": label, "found_on": page_url})
            elif strong:
                hint = _type_hint(lines, i) if _GENERIC_ALT.match(alt) else None
                stem = _file_stem(url)
                name = (f"{hint} · {stem}" if hint and stem else hint or stem) if _GENERIC_ALT.match(alt) else alt
                item = {"url": url, "name": (name or alt or "Floor plan")[:120], "heading": None, "alt": alt[:200],
                        "kind": hit[0], "label": hit[1], "found_on": page_url}
                if hint:
                    item["type_hint"] = hint
                    item["label"] = hit[1] + f"; type from the listing text after it (“{hint}”)"
                images.append(item)
            if len(images) >= MAX_READER_PLANS * 2:
                break
    return images, links, unsupported


_PLAN_LINK = re.compile(r"(?i)floor[\s_-]?plans?|floorplans?|\blayouts?\b")


def plan_links(links: list[tuple[str, str]], page_url: str, tried: set[str], resolver: Resolver, limit: int = 2,
               in_scope=None) -> list[str]:
    """At most `limit` floor-plan pages ACTUALLY linked from the page's reader text (same site; never guessed paths;
    `in_scope(url)` keeps them inside the chosen building's part of an operator's site), overview pages
    ("/floorplans") before single-plan pages."""
    out = []
    for url, text in links:
        key = url.rstrip("/")
        if key in tried or key == page_url.split("#")[0].rstrip("/") or not _PLAN_LINK.search(urlsplit(url).path + " " + text):
            continue
        if reader_target_problem(url, resolver) or (in_scope is not None and not in_scope(url)):
            continue
        out.append(url)
        tried.add(key)
    out.sort(key=lambda u: (not _PLAN_LINK.search(urlsplit(u).path), len([s for s in urlsplit(u).path.split("/") if s]), len(u)))
    return list(dict.fromkeys(out))[:limit]
