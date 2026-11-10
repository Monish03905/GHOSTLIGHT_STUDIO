from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

TOKEN_RE = re.compile(r"[a-z0-9']+")
IP_TERMS = [
    "marvel",
    "mcu",
    "dc comics",
    "star wars",
    "star trek",
    "harry potter",
    "hogwarts",
    "lord of the rings",
    "game of thrones",
    "pokemon",
    "pokémon",
    "nintendo",
    "zelda",
    "minecraft",
    "fortnite",
    "disney",
    "pixar",
    "stranger things",
    "black mirror",
    "twilight zone",
    "rick and morty",
    "spongebob",
    "simpsons",
    "netflix",
    "avengers",
    "batman",
    "superman",
    "spider-man",
    "spiderman",
    "jurassic park",
    "indiana jones",
    "the matrix",
    "breaking bad",
    "better call saul",
    "squid game",
    "the office",
    "friends",
    "taylor swift",
    "beyonce",
    "elon musk",
]

CONTINUITY_PATTERNS = [
    r"\bpart\s+(?:one|two|three|four|five|\d+|[ivx]+)\b",
    r"\bepisode\s+\d+\b",
    r"\b(?:sequel|prequel|spin[- ]?off|reboot|franchise)\b",
    r"\bto be continued\b",
    r"\bpreviously on\b",
    r"\bnext time on\b",
    r"\bin (?:this|our) series\b",
    r"\bthe series continues\b",
    r"\bas (?:we|i) (?:saw|discussed|mentioned) (?:last|before|earlier)\b",
    r"\b(?:chapter|part) (?:two|three|2|3)\b",
]

CLICHE_PHRASES = [
    "in this video",
    "welcome back",
    "smash that",
    "like and subscribe",
    "subscribe now",
    "you won't believe",
    "you wont believe",
    "mind-blowing",
    "mind blowing",
    "game-changer",
    "game changer",
    "let's dive in",
    "lets dive in",
    "without further ado",
    "buckle up",
    "did you know",
    "top 10",
    "hidden gem",
    "life-changing",
    "life changing",
    "shocking truth",
    "nobody talks about",
    "here's why",
    "here is why",
    "this is why",
    "what happens next",
    "gone wrong",
    "you need to know",
    "the truth about",
    "strap in",
    "hold on tight",
    "prepare to be amazed",
    "take a look at",
    "let's take a look",
    "first things first",
    "at the end of the day",
    "in today's video",
    "number one",
    "last but not least",
]

STOPWORDS = set(
    """
    a about above after again against all am an and any are aren't as at be because been before being below
    between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each
    few for from further had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself
    him himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself let's me more most
    mustn't my myself no nor not of off on once only or other ought our ours ourselves out over own same shan't
    she she'd she'll she's should shouldn't so some such than that that's the their theirs them themselves then
    there there's these they they'd they'll they're they've this those through to too under until up very was
    wasn't we we'd we'll we're we've were weren't what what's when when's where where's which while who who's whom
    why why's with won't would wouldn't you you'd you'll you're you've your yours yourself yourselves just really
    also still even ever every much many one two three like make makes made get gets got go goes going come comes
    know know thing things way ways something someone maybe perhaps often always never sometimes now then
    """.split()
)


def normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("—", " ").replace("–", " ")
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str, drop_stopwords: bool = True) -> list[str]:
    out = TOKEN_RE.findall(normalize(text))
    if drop_stopwords:
        out = [t for t in out if t not in STOPWORDS and len(t) > 1]
    return out


def _hash(token: str) -> str:
    return hashlib.blake2b(token.encode("utf-8"), digest_size=8).hexdigest()


def shingles(text: str, size: int = 3, limit: int = 700) -> list[str]:
    words = tokens(text)
    if not words:
        return []
    grams: Iterable[str]
    if len(words) < size:
        grams = words
    else:
        grams = (" ".join(words[i : i + size]) for i in range(len(words) - size + 1))
    seen = {_hash(g) for g in grams}
    return sorted(seen)[:limit]


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    left, right = set(a), set(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def make_fingerprint(
    script: dict[str, Any],
    brief: dict[str, Any],
    title_terms: bool = True,
) -> dict[str, Any]:
    narration = " ".join(
        [script.get("hook", "")]
        + [seg.get("text", "") for seg in script.get("segments", []) if isinstance(seg, dict)]
    )
    title = script.get("title", "")
    premise_parts = {
        "niche": brief.get("niche", ""),
        "subject": brief.get("subject", ""),
        "lens": brief.get("lens", ""),
        "format": brief.get("format", ""),
    }
    premise_key = "|".join(normalize(str(premise_parts[k])) for k in ("niche", "subject", "lens", "format"))
    return {
        "v": 1,
        "title": title,
        "title_terms": sorted(set(tokens(title))) if title_terms else [],
        "shingles": shingles(narration),
        "premise_key": premise_key,
        "premise_parts": premise_parts,
    }


def similarity(fp: dict[str, Any], other: dict[str, Any]) -> float:
    if not fp or not other:
        return 0.0
    j = jaccard(fp.get("shingles", []), other.get("shingles", []))
    title_j = jaccard(fp.get("title_terms", []), other.get("title_terms", []))
    score = max(j, 0.6 * title_j)

    a = fp.get("premise_parts") or _parts_from_key(fp.get("premise_key", ""))
    b = other.get("premise_parts") or _parts_from_key(other.get("premise_key", ""))
    if a.get("subject") and normalize(str(a.get("subject"))) == normalize(str(b.get("subject", ""))):
        score = max(score, 0.58)
    if fp.get("premise_key") and fp.get("premise_key") == other.get("premise_key"):
        score = max(score, 0.9)
    return min(1.0, score)


def _parts_from_key(key: str) -> dict[str, str]:
    chunks = key.split("|")
    keys = ("niche", "subject", "lens", "format")
    return {k: v for k, v in zip(keys, chunks)} if chunks else {}


def evaluate(
    fp: dict[str, Any],
    prior: list[dict[str, Any]],
    threshold: float = 0.30,
) -> dict[str, Any]:
    """Compare a fingerprint against the ledger.

    ``prior`` items are rows with an ``id``, ``title`` and ``fingerprint`` object.
    Returns the best score, nearest neighbour, and a pass/fail verdict.
    """
    best_score = 0.0
    nearest: dict[str, Any] | None = None
    for row in prior:
        other = row.get("fingerprint") or {}
        score = similarity(fp, other)
        if score > best_score:
            best_score = score
            nearest = row
    accepted = best_score <= threshold
    return {
        "accepted": accepted,
        "score": round(best_score, 4),
        "novelty": round(max(0.0, 1.0 - best_score), 4),
        "nearest_id": (nearest or {}).get("id", ""),
        "nearest_title": (nearest or {}).get("title", ""),
        "threshold": threshold,
    }


def continuity_hits(text: str) -> list[str]:
    lowered = normalize(text)
    hits: list[str] = []
    for pattern in CONTINUITY_PATTERNS:
        found = re.findall(pattern, lowered)
        if found:
            hits.append(found[0] if isinstance(found[0], str) else pattern)
    for term in IP_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            hits.append(term)
    # de-duplicate while preserving order
    return list(dict.fromkeys(hits))


def cliche_hits(text: str) -> list[str]:
    lowered = normalize(text)
    return [phrase for phrase in CLICHE_PHRASES if phrase in lowered]
