"""Outbound URL safety (SSRF): the one address policy and the pinned-IP transports.

Local-first: loopback and LAN targets are allowed unless the caller passes
``block_private=True``. Link-local (cloud metadata), multicast, reserved and
unspecified addresses are always rejected.
"""

import ipaddress
import socket
import time
from typing import Callable, Iterable, List, Optional, Sequence, Tuple, cast
from urllib.parse import urlparse

import httpcore
import httpx

ALLOWED_SCHEMES = ("http", "https")

# RFC 6598 shared address space (carrier-grade NAT). CPython does not count it
# as ``is_private``, so strict mode rejects it explicitly.
_SHARED_ADDRESS_SPACE_V4 = ipaddress.ip_network("100.64.0.0/10")

# RFC 6052 Well-Known Prefix (NAT64). The low 32 bits are the IPv4 address the
# translator contacts; the prefix may only carry global IPv4 (RFC 6052 §3.1),
# so the embedded address is always judged under the strict policy. Exact /96:
# network-specific prefixes such as 64:ff9b:1::/48 stay rejected as reserved.
_NAT64_WELL_KNOWN_PREFIX_V6 = ipaddress.ip_network("64:ff9b::/96")

# Names that point inside the network whatever DNS answers; strict mode rejects
# them before trusting a resolver that may not know them.
_INTERNAL_HOSTNAMES = frozenset({"localhost", "metadata", "metadata.google.internal"})
_INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".intranet")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class OutboundAddressBlocked(PermissionError):
    """An outbound URL or host resolves into a disallowed address range."""


def _nat64_well_known_embedded_ipv4(ip: IPAddress) -> Optional[ipaddress.IPv4Address]:
    if not isinstance(ip, ipaddress.IPv6Address) or ip not in _NAT64_WELL_KNOWN_PREFIX_V6:
        return None
    return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)


def _default_resolver(host: str) -> List[str]:
    """Resolve a hostname to the list of IP strings it maps to (A + AAAA)."""
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def classify_address(ip: IPAddress, *, block_private: bool) -> Optional[str]:
    """Return a rejection reason for an IP, or None if it is allowed."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    else:
        translated = _nat64_well_known_embedded_ipv4(ip)
        if translated is not None:
            reason = classify_address(translated, block_private=True)
            if reason:
                return f"NAT64 translated destination blocked: {reason}"
            return None
    if ip.is_link_local:
        return f"link-local address blocked (SSRF metadata risk): {ip}"
    # IPv6 loopback is also reserved; its policy must match IPv4 loopback.
    if ip.is_loopback:
        if block_private:
            return f"private/shared/loopback address blocked: {ip}"
        return None
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return f"disallowed address: {ip}"
    if block_private and (
        ip.is_private
        or (isinstance(ip, ipaddress.IPv4Address) and ip in _SHARED_ADDRESS_SPACE_V4)
    ):
        return f"private/shared/loopback address blocked: {ip}"
    return None


def resolve_outbound_url(
    url: str,
    *,
    block_private: bool = False,
    resolver: Optional[Callable[[str], Iterable]] = None,
) -> List[IPAddress]:
    """Resolve a user-supplied URL's host once and return its approved addresses.

    Raises OutboundAddressBlocked unless every resolved address passes the
    policy. Pin the connection to the returned addresses (PinnedTransport) so
    a rebinding name cannot answer differently at connect time. ``resolver``
    maps a host to IP strings or address objects; tests inject it to avoid DNS.
    """
    if not isinstance(url, str):
        raise OutboundAddressBlocked("URL must be a string")
    if not url.strip():
        raise OutboundAddressBlocked("URL is required")
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise OutboundAddressBlocked(
            f"scheme must be http or https, got '{parsed.scheme or '(none)'}'"
        )
    host = parsed.hostname
    if not host:
        raise OutboundAddressBlocked("URL has no host")

    try:
        raw_ips = [ipaddress.ip_address(host.split("%")[0])]  # a literal needs no DNS
    except ValueError:
        try:
            raw_ips = list((resolver or _default_resolver)(host))
        except Exception as e:
            raise OutboundAddressBlocked(f"host does not resolve: {e}") from e
    if not raw_ips:
        raise OutboundAddressBlocked("host does not resolve")

    ips: List[IPAddress] = []
    for raw in raw_ips:
        if isinstance(raw, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            ip = raw
        elif isinstance(raw, str):
            try:
                ip = ipaddress.ip_address(raw.split("%")[0])  # strip IPv6 zone id
            except ValueError:
                continue
        else:
            continue
        reason = classify_address(ip, block_private=block_private)
        if reason:
            raise OutboundAddressBlocked(reason)
        # getaddrinfo repeats each address once per socktype; a duplicate would
        # spend the pinned transport's shared connect deadline on a dead address.
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise OutboundAddressBlocked("host does not resolve to an IP")
    lower = host.lower()
    if block_private and (lower in _INTERNAL_HOSTNAMES or lower.endswith(_INTERNAL_SUFFIXES)):
        raise OutboundAddressBlocked(f"private/internal hostname blocked: {host}")
    return ips


def check_outbound_url(
    url: str,
    *,
    block_private: bool = False,
    resolver: Optional[Callable[[str], Iterable]] = None,
) -> Tuple[bool, str]:
    """Validate a user-supplied outbound URL. Returns ``(ok, reason)``."""
    try:
        resolve_outbound_url(url, block_private=block_private, resolver=resolver)
    except OutboundAddressBlocked as e:
        return False, str(e)
    return True, "ok"


def connect_outbound_tcp(
    host: str,
    port: int,
    *,
    timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
    block_private: bool = False,
    source_address=None,
    resolver: Optional[Callable[..., list]] = None,
) -> socket.socket:
    """Open a TCP connection to *host* under the outbound address policy.

    For raw TCP clients (IMAP/SMTP). The host is resolved once and the socket
    connects only to the judged addresses; socket.create_connection(host)
    would resolve again and let a rebinding name reach private space. TLS
    callers keep wrapping the socket with ``server_hostname=host``.
    """
    resolve = resolver or socket.getaddrinfo
    infos = resolve(host, port, 0, socket.SOCK_STREAM)
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = ipaddress.ip_address(str(sockaddr[0]).split("%")[0])
        reason = classify_address(ip, block_private=block_private)
        if reason:
            raise OutboundAddressBlocked(reason)
    last_error: Optional[OSError] = None
    for family, socktype, proto, _canon, sockaddr in infos:
        sock = socket.socket(family, socktype, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:  # same contract as create_connection
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    if last_error is not None:
        raise last_error
    raise socket.gaierror(socket.EAI_NONAME, f"{host} did not resolve to an address")


# httpcore raises its own exception hierarchy; map it back so callers'
# `except httpx.*` blocks behave as they do with the default transport.
_HTTPCORE_TO_HTTPX_EXC = {
    httpcore.ConnectError: httpx.ConnectError,
    httpcore.ConnectTimeout: httpx.ConnectTimeout,
    httpcore.LocalProtocolError: httpx.LocalProtocolError,
    httpcore.NetworkError: httpx.NetworkError,
    httpcore.PoolTimeout: httpx.PoolTimeout,
    httpcore.ProtocolError: httpx.ProtocolError,
    httpcore.ProxyError: httpx.ProxyError,
    httpcore.ReadError: httpx.ReadError,
    httpcore.ReadTimeout: httpx.ReadTimeout,
    httpcore.RemoteProtocolError: httpx.RemoteProtocolError,
    httpcore.TimeoutException: httpx.TimeoutException,
    httpcore.UnsupportedProtocol: httpx.UnsupportedProtocol,
    httpcore.WriteError: httpx.WriteError,
    httpcore.WriteTimeout: httpx.WriteTimeout,
}


def _map_httpcore_error(exc: Exception) -> Exception:
    mapped = _HTTPCORE_TO_HTTPX_EXC.get(type(exc))
    return mapped(str(exc)) if mapped is not None else exc


def _core_request(request: httpx.Request) -> httpcore.Request:
    # The URL passes through unchanged, so SNI and the Host header stay the
    # original hostname; only the socket destination is pinned.
    return httpcore.Request(
        method=request.method,
        url=httpcore.URL(
            scheme=request.url.raw_scheme,
            host=request.url.raw_host,
            port=request.url.port,
            target=request.url.raw_path,
        ),
        headers=request.headers.raw,
        content=request.stream,
        extensions=request.extensions,
    )


def _connect_targets(ips: Sequence[IPAddress], timeout: Optional[float]):
    """Yield (ip, remaining timeout) for each approved address under one shared deadline."""
    deadline = None if timeout is None else time.monotonic() + timeout
    for ip in ips:
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        yield str(ip), remaining
        if deadline is not None and time.monotonic() >= deadline:
            return


class PinnedBackend(httpcore.NetworkBackend):
    """Connects only to the approved addresses, in order."""

    def __init__(self, ips: Sequence[IPAddress]):
        self._ips = list(ips)
        self._real = httpcore.SyncBackend()

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        last_exc: Exception = httpcore.ConnectError("no validated address available")
        for ip, remaining in _connect_targets(self._ips, timeout):
            try:
                return self._real.connect_tcp(ip, port, remaining, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_exc = exc
        raise last_exc

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return self._real.connect_unix_socket(path, timeout, socket_options)

    def sleep(self, seconds: float) -> None:
        return self._real.sleep(seconds)


class PinnedAsyncBackend(httpcore.AsyncNetworkBackend):
    """Async twin of PinnedBackend."""

    def __init__(self, ips: Sequence[IPAddress]):
        self._ips = list(ips)
        self._real = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        last_exc: Exception = httpcore.ConnectError("no validated address available")
        for ip, remaining in _connect_targets(self._ips, timeout):
            try:
                return await self._real.connect_tcp(ip, port, remaining, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_exc = exc
        raise last_exc

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return await self._real.connect_unix_socket(path, timeout, socket_options)

    async def sleep(self, seconds: float) -> None:
        return await self._real.sleep(seconds)


class PinnedTransport(httpx.BaseTransport):
    """httpx transport whose TCP connects go only to addresses from resolve_outbound_url."""

    def __init__(self, ips: Sequence[IPAddress], *, http2: bool = False):
        self._pinned_ips = list(ips)
        self._pool = httpcore.ConnectionPool(
            # The CA trust a default httpx client builds (certifi, plus
            # SSL_CERT_FILE / SSL_CERT_DIR), so pinning changes no verify result.
            ssl_context=httpx.create_ssl_context(),
            http1=True,
            http2=http2,
            network_backend=PinnedBackend(ips),
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            core_resp = self._pool.handle_request(_core_request(request))
            try:
                content = b"".join(cast(Iterable[bytes], core_resp.stream))
            finally:
                core_resp.close()
        except Exception as exc:
            mapped = _map_httpcore_error(exc)
            if mapped is exc:
                raise
            raise mapped from exc
        return httpx.Response(
            status_code=core_resp.status,
            headers=core_resp.headers,
            content=content,
            extensions=core_resp.extensions,
        )

    def close(self) -> None:
        self._pool.close()


class PinnedAsyncTransport(httpx.AsyncBaseTransport):
    """Async twin of PinnedTransport (HTTP/1.1 only)."""

    def __init__(self, ips: Sequence[IPAddress]):
        self._pinned_ips = list(ips)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(),
            http1=True,
            http2=False,
            network_backend=PinnedAsyncBackend(ips),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            core_resp = await self._pool.handle_async_request(_core_request(request))
            try:
                content = b"".join([chunk async for chunk in core_resp.aiter_stream()])
            finally:
                await core_resp.aclose()
        except Exception as exc:
            mapped = _map_httpcore_error(exc)
            if mapped is exc:
                raise
            raise mapped from exc
        return httpx.Response(
            status_code=core_resp.status,
            headers=core_resp.headers,
            content=content,
            extensions=core_resp.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()
