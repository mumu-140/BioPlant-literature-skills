from __future__ import annotations

import subprocess
from typing import Any, Callable
from urllib.request import Request, urlopen


def fetch_url(url: str, user_agent: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_url_via_proxy(url: str, user_agent: str, timeout: int, proxy_url: str, curl_bin: str) -> str:
    command = [
        curl_bin,
        "--fail",
        "--silent",
        "--show-error",
        "--location",
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
