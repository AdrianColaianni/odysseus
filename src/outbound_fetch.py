"""SSRF-guarded synchronous HTTP fetching: per-hop DNS pinning, redirects, body budgets.

The address policy and pinned transport live in src/url_safety.py; the names
below are the seams services/search/content.py and its tests patch.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Callable
from urllib.parse import urljoin

import httpx

from src.constants import WEB_FETCH_HARD_MAX_BYTES, WEB_FETCH_SOFT_MAX_BYTES
from src.url_safety import (
    OutboundAddressBlocked,
    PinnedBackend as _PinnedBackend,  # noqa: F401
    PinnedTransport as _PinnedTransport,
    classify_address,
    resolve_outbound_url,
)


def _is_private_address(addr: ipaddress._BaseAddress) -> bool:
    return classify_address(addr, block_private=True) is not None


def _resolve_hostname_ips(hostname: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except Exception:
        return []
    out = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return out


def _resolve_public_ips(
    url: str,
    *,
    resolver: Callable[[str], list[ipaddress._BaseAddress]] | None = None,
) -> list[ipaddress._BaseAddress]:
    try:
        return resolve_outbound_url(
            url, block_private=True, resolver=resolver or _resolve_hostname_ips
        )
    except OutboundAddressBlocked as e:
        raise httpx.RequestError(f"Blocked non-public URL: {url} ({e})") from e


def _public_http_url(
    url: str,
    *,
    resolver: Callable[[str], list[ipaddress._BaseAddress]] | None = None,
) -> bool:
    try:
        _resolve_public_ips(url, resolver=resolver)
    except httpx.RequestError:
        return False
    return True


class BodyTooLargeError(Exception):
    """The server declared a body larger than the hard fetch ceiling."""

    def __init__(self, url: str, declared_bytes: int):
        self.url = url
        self.declared_bytes = declared_bytes
        super().__init__(
            f"response body is {declared_bytes:,} bytes, over the "
            f"{WEB_FETCH_HARD_MAX_BYTES:,}-byte hard cap"
        )


class _CappedFetch:
    """Result of a size-capped streaming GET."""

    __slots__ = (
        "status_code",
        "headers",
        "content",
        "truncated",
        "declared_bytes",
        "encoding",
        "url",
    )

    def __init__(
        self,
        status_code,
        headers,
        content,
        truncated,
        declared_bytes,
        encoding,
        url,
    ):
        self.status_code = status_code
        self.headers = headers
        self.content = content
        self.truncated = truncated
        self.declared_bytes = declared_bytes
        self.encoding = encoding
        self.url = url

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8", errors="replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", self.url)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code} for {self.url}",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )


def _get_public_url(
    url: str,
    headers: dict,
    timeout: int,
    max_redirects: int = 5,
    max_bytes: int | None = None,
    *,
    resolve_public_ips: Callable[[str], list[ipaddress._BaseAddress]] | None = None,
    transport_factory: Callable[[list[ipaddress._BaseAddress]], httpx.BaseTransport] | None = None,
) -> _CappedFetch:
    """Capped streaming GET with SSRF-guarded, DNS-pinned redirects."""
    resolve_public_ips = resolve_public_ips or _resolve_public_ips
    transport_factory = transport_factory or _PinnedTransport
    cap = min(max_bytes or WEB_FETCH_SOFT_MAX_BYTES, WEB_FETCH_HARD_MAX_BYTES)
    current = url
    for _ in range(max_redirects + 1):
        ips = resolve_public_ips(current)
        req_headers = dict(headers or {})

        with httpx.Client(
            headers=req_headers,
            timeout=timeout,
            follow_redirects=False,
            transport=transport_factory(ips),
        ) as client:
            with client.stream("GET", current) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        return _CappedFetch(
                            response.status_code,
                            response.headers,
                            b"",
                            False,
                            None,
                            response.encoding,
                            str(response.url),
                        )
                    current = urljoin(str(response.url), location)
                    continue

                enc = (response.headers.get("content-encoding") or "").strip().lower()

                declared = None
                raw_len = response.headers.get("content-length")
                if raw_len and raw_len.isdigit():
                    declared = int(raw_len)

                if (
                    (not enc or enc == "identity")
                    and declared is not None
                    and declared > WEB_FETCH_HARD_MAX_BYTES
                ):
                    raise BodyTooLargeError(current, declared)

                chunks = []
                read = 0
                truncated = False
                for chunk in response.iter_bytes():
                    read += len(chunk)
                    if read > cap:
                        keep = cap - (read - len(chunk))
                        if keep > 0:
                            chunks.append(chunk[:keep])
                        truncated = True
                        break
                    chunks.append(chunk)

                return _CappedFetch(
                    response.status_code,
                    response.headers,
                    b"".join(chunks),
                    truncated,
                    declared,
                    response.encoding,
                    str(response.url),
                )

    raise httpx.RequestError(
        "Too many redirects", request=httpx.Request("GET", current)
    )
