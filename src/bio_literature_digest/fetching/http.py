from __future__ import annotations

import ipaddress
import socket
import subprocess
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


FORBIDDEN_HOST_SUFFIXES = (".home", ".internal", ".lan", ".local", ".localhost")


def validate_public_http_url(url: str, *, resolve_host: bool = True) -> None:
    """Reject URLs that can target local files, credentials, or non-public networks."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source_locator must use http or https")
    if parsed.username or parsed.password:
        raise ValueError("source_locator must not contain credentials")
    hostname = parsed.hostname.rstrip(".").lower()
    if "." not in hostname or hostname == "localhost" or hostname.endswith(FORBIDDEN_HOST_SUFFIXES):
        raise ValueError("source_locator must use a public hostname")
    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        literal_address = None
    if literal_address is not None and not literal_address.is_global:
        raise ValueError("source_locator must not target a private or local address")
    if resolve_host:
        validate_resolved_addresses(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))


def validate_resolved_addresses(hostname: str, port: int) -> None:
    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"source_locator hostname cannot be resolved: {hostname}") from exc
    if not addresses:
        raise ValueError(f"source_locator hostname cannot be resolved: {hostname}")
    for address in addresses:
        if not ipaddress.ip_address(address[4][0]).is_global:
            raise ValueError("source_locator resolves to a private or local address")


class PublicRedirectHandler(HTTPRedirectHandler):
    """Validate every redirect before urllib follows it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        validate_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url(url: str, user_agent: str, timeout: int) -> str:
    validate_public_http_url(url)
    request = Request(url, headers={"User-Agent": user_agent})
    with build_opener(PublicRedirectHandler()).open(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_url_via_proxy(url: str, user_agent: str, timeout: int, proxy_url: str, curl_bin: str) -> str:
    validate_public_http_url(url)
    command = [
        curl_bin,
        "--fail",
        "--silent",
        "--show-error",
        "--max-time",
        str(timeout),
        "--user-agent",
        user_agent,
        "--proxy",
        proxy_url,
        url,
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout


def fetch_and_parse_locator(
    journal: dict[str, Any],
    locator: str,
    *,
    user_agent: str,
    timeout: int,
    route: str,
    parse_payload: Callable[[str, dict[str, Any], str], list[dict[str, Any]]],
    proxy_url: str = "",
    curl_bin: str = "curl",
) -> list[dict[str, Any]]:
    if route == "proxy":
        payload = fetch_url_via_proxy(locator, user_agent, timeout, proxy_url, curl_bin)
    else:
        payload = fetch_url(locator, user_agent, timeout)
    records = parse_payload(payload, journal, locator)
    for record in records:
        record["fetch_route"] = route
    return records
