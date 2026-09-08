"""
HireLens — SSRF Guard (shared by verification modules)

Any module here that fetches a URL derived from resume text or a
resume-derived company name is fetching attacker-influenceable input.
This module blocks requests to private/loopback/link-local/reserved IP
ranges so a malicious resume can't trick the backend into hitting
internal infrastructure (cloud metadata endpoints, internal admin
panels, localhost services, etc.) on the candidate's behalf.

DNS-rebinding note: is_public_http_url() resolves a hostname and checks
it at validation time — but the actual HTTP request that follows
re-resolves DNS moments later. An attacker controlling their own DNS
with a very short TTL could have the first lookup return a public IP
(passing validation) and the second lookup — used for the real
connection — return an internal address. safe_get() below closes that
gap: it resolves ONCE, validates that result, and pins the exact
validated IP for the connection that actually gets made, via
pinned_dns() — so there is no second, separately-timed DNS lookup for
an attacker's rebinding window to land in. This does not touch TLS/SNI
or certificate validation at all: pinned_dns() only changes what
socket.getaddrinfo() resolves the hostname to for the connection's
underlying socket; the hostname used for the TLS handshake, SNI, and
the Host header is completely unchanged, so certificate validation
happens exactly as it would without pinning.
"""

import socket
import ipaddress
import contextlib
from urllib.parse import urlparse


def _validated_ips(hostname: str) -> set[str] | None:
    """Resolves `hostname` and returns its IPs if ALL of them are public,
    or None if any are blocked / resolution fails. Does not check scheme
    or hostname blocklist — see is_public_http_url() for the full check."""
    try:
        resolved_ips = {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except socket.gaierror:
        return None  # can't resolve — treat as unsafe rather than erroring the whole check

    for ip_str in resolved_ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return None
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            return None

    return resolved_ips


def _hostname_allowed(hostname: str) -> bool:
    hostname = hostname.lower()
    BLOCKED_HOSTNAMES = {
        "localhost", "0.0.0.0", "169.254.169.254", "metadata.google.internal",
        "metadata.gcp.internal", "instance-data",
    }
    return not (hostname in BLOCKED_HOSTNAMES or hostname.endswith(".local") or hostname.endswith(".internal"))


def is_public_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.hostname:
        return False
    if not _hostname_allowed(parsed.hostname):
        return False

    return _validated_ips(parsed.hostname) is not None


@contextlib.contextmanager
def pinned_dns(hostname: str, allowed_ips: set[str]):
    """
    Forces socket.getaddrinfo() to resolve `hostname` to exactly the
    already-validated `allowed_ips` for the duration of the context —
    every other hostname passes through to the real resolver unchanged.
    Scoped as narrowly as possible (one hostname, restored immediately
    after) rather than a global patch left in place.

    httpx's async client (via anyio's asyncio backend) calls this with
    `host` as BYTES, not str — asyncio's own event loop encodes the
    hostname before handing it to socket.getaddrinfo under the hood.
    Comparing directly against the str `hostname` without decoding would
    silently never match and this would silently do nothing (which is
    exactly what happened during development — the patch fired, the
    comparison just never matched, and it noiselessly fell through to a
    real, unpinned lookup instead of raising anything).
    """
    real_getaddrinfo = socket.getaddrinfo

    def _pinned_getaddrinfo(host, *args, **kwargs):
        target = host.decode() if isinstance(host, bytes) else host
        if target == hostname:
            ip = next(iter(allowed_ips))
            return real_getaddrinfo(ip, *args, **kwargs)
        return real_getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = _pinned_getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = real_getaddrinfo


async def safe_fetch(client, url: str, method: str = "GET", **kwargs):
    """
    Async equivalent of safe_get(), for the httpx.AsyncClient used by the
    verification modules. Validates `url` against the SSRF blocklist AND
    pins the connection to the exact IP that was just validated, closing
    the DNS-rebinding gap between "check" and "connect" — an attacker
    controlling their own DNS with a short TTL could otherwise have the
    validation lookup return a public IP and the connection's own
    (separately timed) lookup return an internal one.

    This only changes what socket.getaddrinfo() resolves the hostname to
    for the underlying connection — the hostname itself, used for the TLS
    handshake (SNI) and the Host header, is completely unchanged, so
    certificate validation happens exactly as it would without pinning.

    Does not follow redirects (matches how every caller already handles
    redirects — manually, re-validating and re-pinning each hop, since a
    redirect target is itself attacker-influenceable input).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Unsupported or malformed URL: {url}")
    if not _hostname_allowed(parsed.hostname):
        raise ValueError(f"Blocked hostname: {parsed.hostname}")

    ips = _validated_ips(parsed.hostname)
    if ips is None:
        raise ValueError(f"URL resolves to a blocked or unresolvable address: {url}")

    kwargs.setdefault("follow_redirects", False)
    with pinned_dns(parsed.hostname, ips):
        return await client.request(method, url, **kwargs)
