from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from . import prompts


class LLMError(RuntimeError):
    pass


@dataclass
class ProviderStatus:
    name: str
    model: str
    available: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "model": self.model, "available": self.available, "detail": self.detail}


_OLLAMA_CACHE: tuple[float, bool] = (0.0, False)
_OLLAMA_MODELS_CACHE: tuple[float, list[str]] = (0.0, [])


def _ollama_host() -> str:
    raw = (os.environ.get("OLLAMA_HOST") or "").strip().strip("\"'")
    if not raw:
        raw = "http://127.0.0.1:11434"
    if "://" not in raw:
        raw = f"http://{raw}"
    raw = raw.rstrip("/")
    # A malformed OLLAMA_HOST (bad brackets, stray port) must not take the
    # studio down; fall back to the default and let the probe report offline.
    try:
        httpx.URL(raw).port
    except Exception:
        return "http://127.0.0.1:11434"
    return raw


def ollama_models(timeout: float = 1.5) -> list[str]:
    """Names of locally installed models, largest first, cached briefly."""
    global _OLLAMA_MODELS_CACHE
    stamp, cached = _OLLAMA_MODELS_CACHE
    if time.time() - stamp < 30:
        return cached
    names: list[str] = []
    try:
        response = httpx.get(f"{_ollama_host()}/api/tags", timeout=timeout)
        models = response.json().get("models", []) if response.status_code == 200 else []
        models.sort(key=lambda m: int(m.get("size", 0) or 0), reverse=True)
        names = [str(m.get("name", "")).strip() for m in models if m.get("name")]
    except Exception:
        names = []
    _OLLAMA_MODELS_CACHE = (time.time(), names)
    return names


def ollama_reachable(timeout: float = 0.6) -> bool:
    global _OLLAMA_CACHE
    stamp, cached = _OLLAMA_CACHE
    if time.time() - stamp < 20:
        return cached
    reachable = False
    try:
        parsed = urlparse(_ollama_host())
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 11434
        with socket.create_connection((host, port), timeout=timeout):
            reachable = True
    except (OSError, ValueError):
        reachable = False
    _OLLAMA_CACHE = (time.time(), reachable)
    return reachable


def resolve_provider(cfg: Any) -> str:
    requested = str(cfg.get("script.provider", "auto")).lower()
    if requested in {"openai", "anthropic", "gemini", "ollama", "offline"}:
        return requested
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if ollama_reachable():
        return "ollama"
    return "offline"


def default_model(provider: str) -> str:
    if provider == "ollama":
        override = os.environ.get("OLLAMA_MODEL")
        if override:
            return override
        installed = ollama_models()
        if installed:
            return installed[0]
        return "llama3.1"
    return {
        "openai": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "anthropic": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        "gemini": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        "offline": "the muse",
    }[provider]


def provider_status(cfg: Any) -> ProviderStatus:
    provider = resolve_provider(cfg)
    model = str(cfg.get("script.model", "")).strip() or default_model(provider)
    if provider == "offline":
        return ProviderStatus(provider, "the muse", True, "offline writer, no key needed")
    if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        return ProviderStatus(provider, model, False, "OPENAI_API_KEY is not set")
    if provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        return ProviderStatus(provider, model, False, "ANTHROPIC_API_KEY is not set")
    if provider == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        return ProviderStatus(provider, model, False, "GEMINI_API_KEY is not set")
    if provider == "ollama" and not ollama_reachable():
        return ProviderStatus(provider, model, False, f"no Ollama server at {_ollama_host()}")
    return ProviderStatus(provider, model, True)


def extract_json(text: str) -> dict[str, Any]:
    if not isinstance(text, str):
        raise LLMError("model returned no text")
    cleaned = text.strip().lstrip("\ufeff")
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start < 0:
        raise LLMError("model did not return JSON")
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(cleaned)):
        char = cleaned[idx]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start : idx + 1]
                try:
                    data = json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise LLMError(f"model returned invalid JSON: {exc}") from exc
                if not isinstance(data, dict):
                    raise LLMError("model returned JSON that is not an object")
                return data
    raise LLMError("model returned truncated JSON")


class LLMClient:
    def __init__(self, cfg: Any, timeout: float = 180.0):
        self.cfg = cfg
        self.timeout = timeout
        self.provider = resolve_provider(cfg)
        self.model = str(cfg.get("script.model", "")).strip() or default_model(self.provider)

    @property
    def available(self) -> bool:
        return provider_status(self.cfg).available

    def complete_json(self, system: str, user: str, temperature: float | None = None) -> dict[str, Any]:
        if self.provider == "offline":
            raise LLMError("offline provider does not call a model")
        temp = float(self.cfg.get("script.temperature", 1.0) if temperature is None else temperature)
        try:
            if self.provider == "openai":
                text = self._openai(system, user, temp)
            elif self.provider == "anthropic":
                text = self._anthropic(system, user, temp)
            elif self.provider == "gemini":
                text = self._gemini(system, user, temp)
            elif self.provider == "ollama":
                text = self._ollama(system, user, temp)
            else:
                raise LLMError(f"unknown provider {self.provider}")
        except LLMError:
            raise
        except Exception as exc:
            # Transport, URL and payload bugs all become a normal provider
            # miss so the writer can fall back to the Muse.
            raise LLMError(f"{self.provider} call failed: {exc}") from exc
        return extract_json(text)

    # -- providers ------------------------------------------------------
    def _openai(self, system: str, user: str, temperature: float) -> str:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            if response.status_code == 400 and "response_format" in response.text:
                payload.pop("response_format", None)
                response = client.post(
                    f"{base}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
        if response.status_code >= 400:
            raise LLMError(f"OpenAI error {response.status_code}: {_short_error(response)}")
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("OpenAI returned an unexpected payload") from exc

    def _anthropic(self, system: str, user: str, temperature: float) -> str:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": min(1.0, temperature),
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if response.status_code >= 400:
            raise LLMError(f"Anthropic error {response.status_code}: {_short_error(response)}")
        data = response.json()
        try:
            blocks = [block.get("text", "") for block in data["content"] if block.get("type") == "text"]
        except (KeyError, TypeError) as exc:
            raise LLMError("Anthropic returned an unexpected payload") from exc
        return "\n".join(blocks)

    def _gemini(self, system: str, user: str, temperature: float) -> str:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": 4096,
                "responseMimeType": "application/json",
            },
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, params={"key": api_key}, json=payload)
        if response.status_code >= 400:
            raise LLMError(f"Gemini error {response.status_code}: {_short_error(response)}")
        data = response.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "\n".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Gemini returned an unexpected payload") from exc

    def _ollama(self, system: str, user: str, temperature: float) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature},
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{_ollama_host()}/api/chat", json=payload)
        if response.status_code >= 400:
            raise LLMError(f"Ollama error {response.status_code}: {_short_error(response)}")
        data = response.json()
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise LLMError("Ollama returned an unexpected payload") from exc


def _short_error(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message", err))[:300]
        if err:
            return str(err)[:300]
        if data.get("message"):
            return str(data["message"])[:300]
    return str(data)[:300]


def direct(cfg: Any, instruction: str) -> dict[str, Any]:
    """Interpret a free-form instruction from the director."""
    provider = resolve_provider(cfg)
    if provider == "offline":
        return {"action": "noop", "args": {}, "reply": ""}
    client = LLMClient(cfg, timeout=60)
    system = prompts.directive_prompt(cfg)
    user = f"Director's note: {instruction}"
    data = client.complete_json(system, user, temperature=0.2)
    action = str(data.get("action", "noop")).lower()
    allowed = {"generate", "pause", "resume", "status", "upload", "set_setting", "noop"}
    if action not in allowed:
        action = "noop"
    data["action"] = action
    if not isinstance(data.get("args"), dict):
        data["args"] = {}
    if not isinstance(data.get("reply"), str):
        data["reply"] = ""
    return data
