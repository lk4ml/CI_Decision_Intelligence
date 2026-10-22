"""Shared async HTTP layer for all live connectors.

- async httpx, timeout 20s, UA ``ZS-DecisionIntelligence/0.1 (contact: admin)``
- TLS verify from ``SSL_CERT_FILE`` / ``REQUESTS_CA_BUNDLE`` (else system default)
- ``trust_env=True`` so HTTPS_PROXY / HTTP_PROXY are honoured
- retry with backoff on 429/5xx (max 2 retries)
- any connect error, 4xx (incl. proxy 403) or exhausted retry -> ``SourceUnavailable``

Connectors never fabricate data: on failure they raise, and the pipeline records an
``AgentRun(status="source_unreachable")``.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import httpx

USER_AGENT = "ZS-DecisionIntelligence/0.1 (contact: admin)"
TIMEOUT_S = 20.0
MAX_RETRIES = 2
BACKOFF_S = 1.0

# Test hook: tests may set a transport (e.g. httpx.MockTransport). Never set by the app.
_TRANSPORT_OVERRIDE: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Install a transport override (unit tests only)."""
    global _TRANSPORT_OVERRIDE, BACKOFF_S
    _TRANSPORT_OVERRIDE = transport
    if transport is not None:
        BACKOFF_S = 0.0
    else:
        BACKOFF_S = 1.0


class SourceUnavailable(Exception):
    """A live source could not be reached or refused the request."""

    def __init__(self, source_key: str, host: str, detail: str):
        self.source_key = source_key
        self.host = host
        self.detail = detail
        super().__init__(f"{source_key} unreachable ({host}): {detail}")


@dataclass
class RawItem:
    source_key: str
    external_id: str
    url: str
    title: str
    published_at: str | None
    kind: str
    text: str
    data: dict[str, Any] = field(default_factory=dict)
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = content_hash(self.data or {"title": self.title, "text": self.text})

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["retrieved_at"] = self.retrieved_at.isoformat()
        return d


def content_hash(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _verify() -> str | bool:
    return os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE") or True


def make_client() -> httpx.AsyncClient:
    kwargs: dict[str, Any] = dict(
        timeout=httpx.Timeout(TIMEOUT_S),
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        follow_redirects=True,
        trust_env=True,
    )
    if _TRANSPORT_OVERRIDE is not None:
        kwargs["transport"] = _TRANSPORT_OVERRIDE
    else:
        kwargs["verify"] = _verify()
    return httpx.AsyncClient(**kwargs)


REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5
MAX_BYTES = 20 * 1024 * 1024  # 20 MB hard cap on any response body


def _ip_is_internal(ip: ipaddress._BaseAddress) -> bool:
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified)


async def check_url(source_key: str, url: str,
                    allow_host: Callable[[str], bool] | None = None) -> None:
    """Validate a request target (initial URL and every redirect hop).

    Always: http(s) only, no localhost / literal private, loopback or link-local IPs.
    With ``allow_host``: https only, host must satisfy the allowlist predicate, and the
    host's resolved addresses (best effort) must not be internal.
    """
    u = urlparse(url)
    host = (u.hostname or "").lower().rstrip(".")
    scheme = u.scheme.lower()
    if scheme not in ("http", "https") or not host:
        raise SourceUnavailable(source_key, host or url, f"blocked URL scheme/host: {url[:200]}")
    if host == "localhost" or host.endswith(".localhost"):
        raise SourceUnavailable(source_key, host, "blocked internal host")
    try:
        lit = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        lit = None
    if lit is not None and _ip_is_internal(lit):
        raise SourceUnavailable(source_key, host, "blocked internal IP address")
    if allow_host is None:
        return
    if scheme != "https":
        raise SourceUnavailable(source_key, host, "blocked non-https URL")
    if not allow_host(host):
        raise SourceUnavailable(source_key, host, f"host not in allowlist: {host}")
    if lit is None and _TRANSPORT_OVERRIDE is None:
        try:
            infos = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(host, 443), timeout=5)
        except (OSError, asyncio.TimeoutError):
            infos = []  # resolution may only be possible at the egress proxy
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if _ip_is_internal(ip):
                raise SourceUnavailable(source_key, host, f"host resolves to internal IP {ip}")


async def _once(c: httpx.AsyncClient, source_key: str, url: str, params, headers,
                allow_host, max_bytes: int) -> httpx.Response:
    """One logical GET with manual, validated redirects and a streamed size cap."""
    current, cur_params = url, params
    for _hop in range(MAX_REDIRECTS + 1):
        await check_url(source_key, current, allow_host)
        async with c.stream("GET", current, params=cur_params, headers=headers,
                            follow_redirects=False) as r:
            if r.status_code in REDIRECT_CODES and r.headers.get("location"):
                current = urljoin(str(r.url), r.headers["location"])
                cur_params = None
                continue
            host = r.url.host or current
            declared = r.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise SourceUnavailable(source_key, host, f"response too large ({declared} bytes)")
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > max_bytes:
                    raise SourceUnavailable(source_key, host, f"response exceeds {max_bytes} bytes")
            hdrs = [(k, v) for k, v in r.headers.items()
                    if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
            return httpx.Response(r.status_code, headers=hdrs, content=bytes(buf), request=r.request)
    raise SourceUnavailable(source_key, urlparse(url).hostname or url, "too many redirects")


async def _request(
    source_key: str,
    url: str,
    params: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
    headers: dict[str, str] | None = None,
    allow_host: Callable[[str], bool] | None = None,
    max_bytes: int = MAX_BYTES,
) -> httpx.Response:
    host = urlparse(url).hostname or url
    own = client is None
    c = client or make_client()
    try:
        last_detail = "unknown error"
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await _once(c, source_key, url, params, headers, allow_host, max_bytes)
            except httpx.ProxyError as e:
                raise SourceUnavailable(source_key, host, f"proxy error: {e}") from e
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
                last_detail = f"{type(e).__name__}: {e}"
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(BACKOFF_S * (2**attempt))
                    continue
                raise SourceUnavailable(source_key, host, last_detail) from e
            except httpx.HTTPError as e:
                raise SourceUnavailable(source_key, host, f"{type(e).__name__}: {e}") from e

            if resp.status_code == 429 or resp.status_code >= 500:
                last_detail = f"HTTP {resp.status_code}"
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(BACKOFF_S * (2**attempt))
                    continue
                raise SourceUnavailable(source_key, host, last_detail)
            if resp.status_code >= 400:
                snippet = (resp.text or "")[:200].replace("\n", " ")
                raise SourceUnavailable(source_key, host, f"HTTP {resp.status_code}: {snippet}")
            return resp
        raise SourceUnavailable(source_key, host, last_detail)
    finally:
        if own:
            await c.aclose()


async def get_response(source_key: str, url: str, params: dict[str, Any] | None = None,
                       client: httpx.AsyncClient | None = None,
                       allow_host: Callable[[str], bool] | None = None,
                       max_bytes: int = MAX_BYTES) -> httpx.Response:
    """Full response (``resp.url`` is the final URL after validated redirects)."""
    return await _request(source_key, url, params, client, None, allow_host, max_bytes)


async def get_json(source_key: str, url: str, params: dict[str, Any] | None = None,
                   client: httpx.AsyncClient | None = None) -> Any:
    resp = await _request(source_key, url, params, client, {"Accept": "application/json"})
    try:
        return resp.json()
    except ValueError as e:
        host = urlparse(url).hostname or url
        raise SourceUnavailable(source_key, host, f"invalid JSON: {e}") from e


async def get_text(source_key: str, url: str, params: dict[str, Any] | None = None,
                   client: httpx.AsyncClient | None = None) -> str:
    resp = await _request(source_key, url, params, client)
    return resp.text


async def get_bytes(source_key: str, url: str, params: dict[str, Any] | None = None,
                    client: httpx.AsyncClient | None = None) -> bytes:
    resp = await _request(source_key, url, params, client)
    return resp.content
