"""Bounded public-web fetching with private-network (SSRF) defenses.

Defenses, all enforced in code:
- Only http/https, no URL credentials, only ports 80/443.
- Hostnames are resolved once; EVERY resolved address must be globally routable (rejects
  loopback, RFC1918, link-local incl. 169.254.169.254 metadata, CGNAT, ULA, multicast,
  reserved, IPv4-mapped private IPv6).
- The TCP connection is pinned to the validated IP (TLS still verifies the hostname via SNI),
  so a second DNS answer (rebinding) can never redirect the connection.
- Redirects are followed manually (bounded), and each hop is re-validated from scratch.
- Response bytes are capped while streaming, compression is refused (identity only),
  media types are allow-listed, and there is a timeout per connection.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable
from urllib.parse import urljoin, urlsplit

USER_AGENT = "FurnitureAI/0.1 (personal furniture-planning tool; single-page evidence fetch)"
ALLOWED_PORTS = {80, 443}
MAX_URL_LENGTH = 2048

HTML_TYPES = ("text/html", "application/xhtml+xml")
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")
PDF_TYPES = ("application/pdf",)


class FetchBlocked(Exception):
    """The URL or a redirect target violated the network policy."""


class FetchFailed(Exception):
    """Network/protocol failure, oversize content, or disallowed media type."""


Resolver = Callable[[str, int], list[str]]


def default_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchFailed(f"DNS lookup failed for {host}") from exc
    return sorted({info[4][0] for info in infos})


def ip_is_public(raw: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped or ip.sixtofour
        if mapped is not None:
            return ip_is_public(str(mapped))
        if ip.teredo:
            return False
    return bool(
        ip.is_global
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_private
        and not ip.is_unspecified
    )


@dataclass(frozen=True)
class ValidatedTarget:
    url: str
    scheme: str
    host: str
    port: int
    path: str  # path + query
    ip: str


def validate_url(url: str, resolver: Resolver = default_resolver) -> ValidatedTarget:
    if not isinstance(url, str) or len(url) > MAX_URL_LENGTH:
        raise FetchBlocked("URL missing or too long")
    if any(ch in url for ch in ("\r", "\n", "\t", " ")):
        raise FetchBlocked("URL contains whitespace/control characters")
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise FetchBlocked(f"Scheme '{scheme or 'none'}' is not allowed")
    if parts.username or parts.password or "@" in parts.netloc:
        raise FetchBlocked("Credentials in URLs are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise FetchBlocked("URL has no host")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        raise FetchBlocked("Local hostnames are not allowed")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise FetchBlocked("Invalid port") from exc
    if port not in ALLOWED_PORTS:
        raise FetchBlocked(f"Port {port} is not allowed")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
        addresses = [str(literal)]
    except ValueError:
        addresses = resolver(host, port)
    if not addresses:
        raise FetchFailed(f"No addresses for {host}")
    bad = [a for a in addresses if not ip_is_public(a)]
    if bad:
        raise FetchBlocked(f"Host {host} resolves to a non-public address")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return ValidatedTarget(url=url, scheme=scheme, host=host, port=port, path=path, ip=addresses[0])


@dataclass
class RawResponse:
    status: int
    headers: dict[str, str]
    body: bytes


Opener = Callable[[ValidatedTarget, dict[str, str], float, int], RawResponse]


def _tls_context() -> ssl.SSLContext:
    try:  # python.org macOS builds ship without a system CA bundle
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, ip: str, host: str, port: int, timeout: float):
        super().__init__(host, port, timeout=timeout, context=_tls_context())
        self._pinned_ip = ip

    def connect(self) -> None:  # connect to the validated IP, verify cert for the hostname
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, ip: str, host: str, port: int, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._pinned_ip = ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


def pinned_opener(target: ValidatedTarget, headers: dict[str, str], timeout: float, max_bytes: int) -> RawResponse:
    cls = _PinnedHTTPSConnection if target.scheme == "https" else _PinnedHTTPConnection
    conn = cls(target.ip, target.host, target.port, timeout)
    try:
        conn.request("GET", target.path, headers=headers)
        resp = conn.getresponse()
        body = bytearray()
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > max_bytes:
                raise FetchFailed(f"Response exceeded {max_bytes} bytes")
        return RawResponse(resp.status, {k.lower(): v for k, v in resp.getheaders()}, bytes(body))
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        raise FetchFailed(f"Network error: {type(exc).__name__}") from exc
    finally:
        conn.close()


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    sha256: str
    retrieved_at: str
    redirect_chain: list[str] = field(default_factory=list)


class SafeFetcher:
    def __init__(
        self,
        resolver: Resolver = default_resolver,
        opener: Opener = pinned_opener,
        max_redirects: int = 4,
        timeout_s: float = 12.0,
    ):
        self.resolver = resolver
        self.opener = opener
        self.max_redirects = max_redirects
        self.timeout_s = timeout_s

    def fetch(
        self,
        url: str,
        allowed_types: Iterable[str] = HTML_TYPES,
        max_bytes: int = 3_000_000,
        user_agent: str = USER_AGENT,
        url_guard=None,
    ) -> FetchResult:
        """`url_guard(url) -> reason | None` (optional) is applied to the first URL and EVERY redirect hop BEFORE any
        connection is made to it (e.g. an approved-sites boundary)."""
        allowed = tuple(allowed_types)
        chain: list[str] = []
        current = url
        for _ in range(self.max_redirects + 1):
            if url_guard is not None:
                why = url_guard(current)
                if why:
                    raise FetchBlocked(why)
            target = validate_url(current, self.resolver)
            headers = {
                "User-Agent": user_agent,
                "Accept": ", ".join(allowed) + ";q=1.0, */*;q=0.1",
                "Accept-Encoding": "identity",
                "Connection": "close",
            }
            raw = self.opener(target, headers, self.timeout_s, max_bytes)
            if raw.status in (301, 302, 303, 307, 308):
                location = raw.headers.get("location")
                if not location:
                    raise FetchFailed("Redirect without Location")
                chain.append(current)
                current = urljoin(current, location)
                continue
            if raw.headers.get("content-encoding", "identity").lower() not in ("identity", ""):
                raise FetchFailed("Compressed responses are refused")
            if len(raw.body) > max_bytes:
                raise FetchFailed(f"Response exceeded {max_bytes} bytes")
            ctype = raw.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if raw.status >= 400:
                raise FetchFailed(f"HTTP {raw.status} from {target.host}")
            if ctype not in allowed:
                raise FetchFailed(f"Media type '{ctype or 'unknown'}' not allowed here")
            return FetchResult(
                requested_url=url,
                final_url=current,
                status=raw.status,
                content_type=ctype,
                body=raw.body,
                sha256=hashlib.sha256(raw.body).hexdigest(),
                retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                redirect_chain=chain,
            )
        raise FetchBlocked(f"Too many redirects (> {self.max_redirects})")
