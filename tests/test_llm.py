from __future__ import annotations

import pytest

from ghostlight import llm
from ghostlight.scriptwriter import ScriptWriter

DEFAULT_HOST = "http://127.0.0.1:11434"


def test_malformed_ollama_host_falls_back(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://[::1]:11434]")
    assert llm._ollama_host() == DEFAULT_HOST
    assert llm.ollama_reachable() in {True, False}  # never raises


def test_host_without_scheme_gains_one(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    assert llm._ollama_host() == DEFAULT_HOST


def test_local_ollama_client_ignores_proxy_config(monkeypatch):
    # A malformed NO_PROXY entry (e.g. bracketed IPv6) must not break a local
    # Ollama call before the socket is opened.
    monkeypatch.setenv("NO_PROXY", "[::1],::1")
    with llm._local_client(0.1) as client:
        assert client.trust_env is False


def test_provider_errors_become_llm_errors(cfg, monkeypatch):
    cfg.set("script.provider", "ollama")
    monkeypatch.setattr(llm, "_ollama_host", lambda: "http://::1:11434")
    client = llm.LLMClient(cfg)
    with pytest.raises(llm.LLMError):
        client.complete_json("system", "user")


def test_writer_falls_back_when_the_probe_breaks(cfg, db, monkeypatch):
    def explode(_cfg):
        raise ValueError("Invalid port: ':1]'")

    monkeypatch.setattr("ghostlight.scriptwriter.provider_status", explode)
    writer = ScriptWriter(cfg, db)
    result = writer.write(fmt="short", seed=11)

    assert result.provider == "muse"
    assert result.script["title"]
    assert result.script["narration"]
