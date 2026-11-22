from __future__ import annotations

import httpx

from ghostlight import net


def test_client_survives_a_malformed_no_proxy(monkeypatch) -> None:
    monkeypatch.setenv("NO_PROXY", "[::1]")
    monkeypatch.setenv("HTTP_PROXY", "")
    monkeypatch.setenv("HTTPS_PROXY", "")
    monkeypatch.setenv("ALL_PROXY", "")
    with net.client(timeout=1.0) as http:
        assert isinstance(http, httpx.Client)
