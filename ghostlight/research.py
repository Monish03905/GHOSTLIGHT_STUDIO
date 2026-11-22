from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

from . import net
from .config import Config

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
OPENALEX = "https://api.openalex.org/works"
USER_AGENT = "GhostlightStudio/1.0 (local research; contact the operator of this studio)"

CAVEAT = (
    "This is automated triage, not verification. Sources are found and matched by text, "
    "not read for truth. Numbers and quotes still need a human, and a missing match is not "
    "proof that a claim is false."
)

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "in", "on", "for", "to", "with", "by",
    "from", "at", "as", "is", "are", "was", "were", "be", "been", "being", "that", "this",
    "these", "those", "it", "its", "into", "over", "under", "than", "then", "so", "we",
    "you", "they", "their", "our", "his", "her", "not", "no", "can", "could", "would",
    "should", "may", "might", "has", "have", "had", "do", "does", "did", "more", "most",
    "less", "very", "also", "about", "after", "before", "when", "where", "which", "who",
    "what", "while", "because", "there", "here", "one", "two", "all", "any", "some",
}

HEDGE_WORDS = {
    "first", "oldest", "largest", "smallest", "deepest", "highest", "fastest", "only",
    "never", "always", "discovered", "invented", "record", "recorded", "proved", "proven",
}

_NUMBER = re.compile(r"\b\d[\d,.]*\b")
_YEAR = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")
_ENTITY = re.compile(r"\b[A-Z][a-z]{2,}\b")


def note_allowed(url: str, allowlist: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower().strip(".")
    if not host:
        return False
    for entry in allowlist:
        bare = str(entry or "").lower().strip().strip(".").lstrip(".")
        if not bare:
            continue
        if bare in {"edu", "gov"}:
            if host.endswith(f".{bare}"):
                return True
            continue
        if host == bare or host.endswith(f".{bare}"):
            return True
    return False


def narration_text(video: dict[str, Any]) -> str:
    script = video.get("script") or {}
    parts = [str(script.get("narration") or "")] if script.get("narration") else []
    for segment in script.get("segments") or []:
        if isinstance(segment, dict) and segment.get("text"):
            parts.append(str(segment["text"]))
    if not parts:
        parts = [str(video.get("hook") or ""), str(video.get("description") or "")]
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def extract_claims(video: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    text = narration_text(video)
    if not text:
        return []
    sentences = [s.strip(" —-") for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for position, sentence in enumerate(sentences):
        words = sentence.split()
        if not (5 <= len(words) <= 46):
            continue
        # Narration and segment text often repeat a sentence; one claim is enough.
        normalized = re.sub(r"\s+", " ", sentence.lower()).strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        score = 0
        numbers = _NUMBER.findall(sentence)
        years = _YEAR.findall(sentence)
        # Drop the first capitalised word: every sentence starts with one.
        entities = [
            e for e in _ENTITY.findall(sentence[1:])
            if e.lower() not in STOPWORDS
        ]
        if numbers or years:
            score += 2
        if any(word in sentence.lower() for word in HEDGE_WORDS):
            score += 2
        if len(entities) >= 1:
            score += 1
        if 10 <= len(words) <= 32:
            score += 1
        if score >= 2:
            scored.append((score, position, sentence))
    scored.sort(key=lambda row: (-row[0], row[1]))
    picked = scored[: max(0, limit)]
    picked.sort(key=lambda row: row[1])
    out = []
    for score, _position, sentence in picked:
        out.append({
            "text": sentence[:400],
            "numbers": _NUMBER.findall(sentence)[:4],
            "years": _YEAR.findall(sentence)[:3],
            "score": score,
        })
    return out


def _words(text: str) -> set[str]:
    return {
        word for word in re.findall(r"[a-z0-9']+", text.lower())
        if len(word) > 2 and word not in STOPWORDS
    }


def overlap(claim: str, source: str) -> float:
    claim_words = _words(claim)
    if not claim_words:
        return 0.0
    source_words = _words(source)
    shared = claim_words & source_words
    score = len(shared) / len(claim_words)
    claim_years = set(_YEAR.findall(claim))
    if claim_years:
        if claim_years & set(_YEAR.findall(source)):
            score = min(1.0, score + 0.12)
        else:
            score = min(score, 0.45)
    return round(score, 3)


def _status(score: float) -> str:
    if score >= 0.55:
        return "supported"
    if score >= 0.25:
        return "related"
    return "unmatched"


def _timeout(cfg: Config) -> float:
    return max(3.0, float(cfg.get("research.timeout_seconds", 12) or 12))


def _json_get(url: str, params: dict[str, Any], timeout: float) -> tuple[int, Any]:
    return net.request_json("GET", url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)


def _wikipedia(cfg: Config, query: str, notes: list[str]) -> list[dict[str, Any]]:
    timeout = _timeout(cfg)
    try:
        code, data = _json_get(WIKI_API, {
            "action": "query", "list": "search", "srsearch": query,
            "format": "json", "srlimit": 2,
        }, timeout)
    except net.NetworkError as exc:
        notes.append(f"Wikipedia search skipped: {exc}")
        return []
    if code >= 400 or not isinstance(data, dict):
        notes.append(f"Wikipedia search answered HTTP {code}.")
        return []
    hits = ((data.get("query") or {}).get("search") or [])[:2]
    sources: list[dict[str, Any]] = []
    for hit in hits:
        title = str(hit.get("title") or "").strip()
        if not title:
            continue
        page_url = f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
        snippet = re.sub(r"<[^>]+>", "", str(hit.get("snippet") or ""))[:240]
        try:
            code, summary = _json_get(
                f"{WIKI_SUMMARY}{quote(title.replace(' ', '_'))}", {}, timeout
            )
        except net.NetworkError:
            summary = {}
        if isinstance(summary, dict) and summary.get("extract"):
            snippet = str(summary["extract"])[:240]
            page_url = str(summary.get("content_urls", {}).get("desktop", {}).get("page") or page_url)
        sources.append({
            "title": title,
            "url": page_url,
            "publisher": "Wikipedia",
            "provider": "wikipedia",
            "snippet": snippet,
        })
    return sources


def _openalex(cfg: Config, query: str, notes: list[str]) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"search": query, "per-page": 2}
    mailto = str(cfg.get("research.mailto") or "").strip()
    if mailto:
        params["mailto"] = mailto
    try:
        code, data = _json_get(OPENALEX, params, _timeout(cfg))
    except net.NetworkError as exc:
        notes.append(f"OpenAlex skipped: {exc}")
        return []
    if code >= 400 or not isinstance(data, dict):
        notes.append(f"OpenAlex answered HTTP {code}.")
        return []
    sources = []
    for work in (data.get("results") or [])[:2]:
        title = str(work.get("display_name") or "").strip()
        if not title:
            continue
        doi = str(work.get("doi") or "").strip()
        url = doi if doi.startswith("http") else (f"https://doi.org/{doi}" if doi else str(work.get("id") or ""))
        year = work.get("publication_year")
        venue = (((work.get("primary_location") or {}).get("source") or {}).get("display_name")) or ""
        snippet = " · ".join(str(bit) for bit in (year, venue) if bit)
        sources.append({
            "title": title,
            "url": url,
            "publisher": venue or "OpenAlex",
            "provider": "openalex",
            "snippet": snippet[:240],
        })
    return sources


def _searxng(cfg: Config, query: str, notes: list[str]) -> list[dict[str, Any]]:
    base = str(cfg.get("research.searxng_url") or "").strip().rstrip("/")
    if not base:
        return []
    allowlist = [str(x) for x in (cfg.get("research.allowlist") or [])]
    try:
        code, data = _json_get(f"{base}/search", {
            "q": query, "format": "json", "categories": "general", "language": "en",
        }, _timeout(cfg))
    except net.NetworkError as exc:
        notes.append(f"SearXNG skipped: {exc}")
        return []
    if code >= 400 or not isinstance(data, dict):
        notes.append(f"SearXNG answered HTTP {code} (JSON may be disabled on that instance).")
        return []
    sources = []
    for result in (data.get("results") or [])[:8]:
        url = str(result.get("url") or "")
        if not note_allowed(url, allowlist):
            continue
        sources.append({
            "title": str(result.get("title") or url)[:200],
            "url": url,
            "publisher": (urlparse(url).hostname or "")[:80],
            "provider": "searxng",
            "snippet": str(result.get("content") or "")[:240],
        })
        if len(sources) >= 3:
            break
    return sources


def _dedupe(sources: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for source in sources:
        url = str(source.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(source)
        if len(out) >= limit:
            break
    return out


def analyze(cfg: Config, video: dict[str, Any]) -> dict[str, Any]:
    if not bool(cfg.get("research.enabled", True)):
        return {
            "enabled": False, "generated_at": "", "provider": "", "claims": [],
            "counts": {"claims": 0, "supported": 0, "related": 0, "unmatched": 0},
            "caveat": CAVEAT, "notes": ["Research is switched off in The knobs."],
        }
    limit = max(1, min(10, int(cfg.get("research.max_claims", 5) or 5)))
    per_claim = max(1, min(5, int(cfg.get("research.max_sources_per_claim", 3) or 3)))
    claims = extract_claims(video, limit)
    notes: list[str] = []
    providers: set[str] = set()
    if not claims:
        notes.append("No numeric, dated or superlative claims were found in this script.")
    report_claims = []
    all_sources: dict[str, dict[str, Any]] = {}
    for claim in claims:
        found: list[dict[str, Any]] = []
        found += _wikipedia(cfg, claim["text"], notes)
        found += _openalex(cfg, claim["text"], notes)
        found += _searxng(cfg, claim["text"], notes)
        ranked = sorted(
            ((overlap(claim["text"], f"{s.get('title','')} {s.get('snippet','')}"), s) for s in found),
            key=lambda pair: -pair[0],
        )
        best = ranked[0][0] if ranked else 0.0
        chosen = _dedupe([s for _, s in ranked], per_claim)
        for source in chosen:
            providers.add(str(source.get("provider") or ""))
            all_sources.setdefault(str(source["url"]), {**source, "claims": []})
            all_sources[str(source["url"])]["claims"].append(claim["text"][:120])
        report_claims.append({
            "text": claim["text"],
            "status": _status(best) if found else "unmatched",
            "confidence": best,
            "years": claim["years"],
            "sources": chosen,
        })
    counts = {
        "claims": len(report_claims),
        "supported": sum(1 for c in report_claims if c["status"] == "supported"),
        "related": sum(1 for c in report_claims if c["status"] == "related"),
        "unmatched": sum(1 for c in report_claims if c["status"] == "unmatched"),
    }
    if not claims:
        verdict = "Nothing to check yet."
    elif counts["unmatched"]:
        verdict = f"{counts['unmatched']} claim(s) found no match and need a human read."
    elif counts["related"]:
        verdict = f"{counts['related']} claim(s) have related reading, not a direct match."
    else:
        verdict = "Every checked claim has a close source match — still read them."
    if all_sources:
        notes.append("OpenAlex links can point off the allowlist; only SearXNG results are host-filtered.")
    return {
        "enabled": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": "+".join(sorted(p for p in providers if p)) or "none",
        "claims": report_claims,
        "counts": counts,
        "verdict": verdict,
        "caveat": CAVEAT,
        "notes": notes,
        "sources": list(all_sources.values()),
    }
