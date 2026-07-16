"""
HireLens — SSRF Guard (shared by verification modules)

Any module here that fetches a URL derived from resume text or a
resume-derived company name is fetching attacker-influenceable input.
This module blocks requests to private/loopback/link-local/reserved IP
ranges so a malicious resume can't trick the backend into hitting
internal infrastructure (cloud metadata endpoints, internal admin
panels, localhost services, etc.) on the candidate's behalf.
"""

import socket
import ipaddress
from urllib.parse import urlparse


def is_public_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.hostname:
        return False

    hostname = parsed.hostname.lower()
    if hostname in ("localhost", "0.0.0.0") or hostname.endswith(".local"):
        return False

    try:
        resolved_ips = {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except socket.gaierror:
        return False  # can't resolve — treat as unsafe rather than erroring the whole check

    for ip_str in resolved_ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            return False

    return True
