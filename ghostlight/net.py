from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


class NetworkError(Exception):
    """The request never reached a usable answer (DNS, TLS, timeout, 5xx)."""


# Tests inject an httpx.MockTransport here; production leaves it as None so
# httpx builds its normal transport. Kept module-level so every provider
# shares one seam and no test needs to reach inside a client.
_TRANSPORT: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    global _TRANSPORT
    _TRANSPORT = transport


def reset_transport() -> None:
    set_transport(None)


def client(timeout: float = 30.0, headers: dict[str, str] | None = None) -> httpx.Client:
    options = {
        "timeout": timeout,
        "headers": headers or {},
        "transport": _TRANSPORT,
        "follow_redirects": True,
    }
    try:
        return httpx.Client(**options)
    except httpx.InvalidURL:
        # A malformed NO_PROXY entry (say, a bracketed [::1]) makes httpx's
        # proxy parser raise before any request is sent. Go direct rather than
        # lose every provider call to one bad environment value.
        return httpx.Client(**options, trust_env=False)


def request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    body: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    """Return (status, parsed JSON or raw text). Remote errors are not raised."""
    try:
        with client(timeout=timeout, headers=headers) as http:
            response = http.request(method, url, params=params, json=body)
    except httpx.HTTPError as exc:
        raise NetworkError(f"{method} {url} did not answer: {exc}") from exc
    try:
        payload: Any = response.json()
    except ValueError:
        payload = response.text[:2000]
    return response.status_code, payload


def download(
    url: str,
    dest: str | Path,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 180.0,
) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with client(timeout=timeout, headers=headers) as http:
            with http.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise NetworkError(f"Download failed with HTTP {response.status_code}.")
                with dest.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
    except httpx.HTTPError as exc:
        raise NetworkError(f"Download from {url} failed: {exc}") from exc
    if not dest.is_file() or dest.stat().st_size == 0:
        raise NetworkError("The download finished but the file is empty.")
    return dest
