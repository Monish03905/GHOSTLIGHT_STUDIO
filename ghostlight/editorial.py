from __future__ import annotations

import re
from typing import Any

# A deterministic second read of a script. No model is called and nothing here
# is presented as a forecast: these are structural signals an editor can check.

_CURIOSITY = {
    "why", "what", "how", "hidden", "secret", "strange", "impossible", "forgotten",
    "vanished", "beneath", "inside", "never", "last", "first", "only", "vanishing",
    "unseen", "quiet", "wrong", "missing",
}
_PAYOFF = {
    "so", "therefore", "which means", "that's why", "next time", "remember",
    "the trick", "in the end", "turn it", "listen", "here's", "now you",
}
_CTA = {"subscribe", "follow", "comment", "share", "save", "join"}
_RISK_TERMS = {
    "lyrics": "song lyrics need a licence",
    "soundtrack": "commercial music needs a licence",
    "footage from": "third-party footage needs permission",
    "excerpt from": "long excerpts need permission",
    "adapted from": "adaptations need rights review",
    "based on the book": "adaptations need rights review",
    "based on a true story": "verify the source before claiming this",
    "study says": "name and link the study",
    "scientists say": "name the scientists and the paper",
}
_STOP = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "it", "its", "this", "that", "you", "we", "they",
    "as", "at", "by", "from", "not", "be", "been", "has", "have", "had", "do",
}

_TERMINAL = re.compile(r"[.!?…]['\"”’)]?$")
_WORD = re.compile(r"[A-Za-z0-9'’\-]+")


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(str(text or ""))]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+|\n+", str(text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _band(value: float, ideal_low: float, ideal_high: float, span: float = 30.0) -> float:
    """100 inside the ideal band, falling to 0 `span` away from it."""
    if ideal_low <= value <= ideal_high:
        return 100.0
    distance = ideal_low - value if value < ideal_low else value - ideal_high
    return _clamp(100.0 - (distance / span) * 100.0)


def _script_segments(script: dict[str, Any]) -> list[str]:
    segments = script.get("segments") if isinstance(script, dict) else None
    if isinstance(segments, list):
        out = [str(s.get("text") or "").strip() for s in segments if isinstance(s, dict)]
        out = [s for s in out if s]
        if out:
            return out
    narration = str((script or {}).get("narration") or "").strip()
    return [narration] if narration else []


def _grade(score: float) -> str:
    if score >= 72:
        return "pass"
    if score >= 48:
        return "warn"
    return "fail"


def _check(key: str, label: str, score: float, detail: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "score": int(round(_clamp(score))),
        "grade": _grade(score),
        "detail": detail,
    }


def _hook_variants(title: str, hook: str) -> list[str]:
    words = [w for w in re.findall(r"[A-Za-z0-9'’\-]+", title) if w]
    subject = " ".join(words[:7]).strip(" .,:;!?") or "this"
    core = subject[0].lower() + subject[1:] if len(subject) > 1 else subject.lower()
    existing = str(hook or "").strip().lower()
    options = [
        f"What if {core} is not what it seems?",
        f"The strange truth about {core}.",
        f"Nobody tells you what really happens with {core}.",
    ]
    return [o for o in options if o.lower() != existing][:3]


def analyze(script: dict[str, Any] | None, *, title: str = "", duration: float = 0.0,
            fmt: str = "short") -> dict[str, Any]:
    """Read a script's structure. Deterministic, cheap, and explicit about limits."""
    script = script if isinstance(script, dict) else {}
    segments = _script_segments(script)
    text = " ".join(segments).strip()
    hook = str(script.get("hook") or "").strip()
    if not text and not hook:
        return {
            "ok": False,
            "score": 0,
            "checks": [],
            "suggestions": ["There is no script text to read yet."],
            "hook_variants": [],
            "retention": {"band": "—", "note": "Needs a script."},
            "risk": {"level": "unknown", "flags": []},
        }

    sentences = _sentences(text or hook)
    words = _tokens(text or hook)
    word_count = len(words)
    seconds = float(duration or 0.0)
    if seconds <= 0:
        target = float(script.get("target_seconds") or 0) or (34.0 if fmt == "short" else 280.0)
        seconds = target
    wpm = (word_count / seconds) * 60.0 if seconds > 0 else 0.0

    hook_text = hook or (sentences[0] if sentences else "")
    hook_words = _tokens(hook_text)
    hook_tokens = set(hook_words)
    hook_score = 45.0
    if "?" in hook_text:
        hook_score += 18
    if re.search(r"\b\d+\b", hook_text):
        hook_score += 10
    if hook_tokens & _CURIOSITY:
        hook_score += 18
    if 6 <= len(hook_words) <= 22:
        hook_score += 12
    if len(hook_words) > 32:
        hook_score -= 15
    if not hook_text:
        hook_score = 20.0
    hook_check = _check(
        "hook", "Hook",
        hook_score,
        f"{len(hook_words)} words, "
        + ("a question" if "?" in hook_text else "a statement")
        + (", carries a curiosity word" if hook_tokens & _CURIOSITY else ""),
    )

    pacing_score = _band(wpm, 128.0, 172.0, span=45.0)
    pacing_check = _check(
        "pacing", "Pacing", pacing_score,
        f"{wpm:.0f} words per minute across {seconds:.0f}s"
        + (" — inside the natural band" if 128 <= wpm <= 172 else " — outside the 128–172 band"),
    )

    lengths = [len(_tokens(s)) for s in sentences] or [word_count]
    average = sum(lengths) / len(lengths)
    long_sentences = sum(1 for n in lengths if n > 30)
    clarity_score = _band(average, 8.0, 22.0, span=20.0) - long_sentences * 6
    clarity_check = _check(
        "clarity", "Clarity", clarity_score,
        f"{average:.1f} words per sentence, {long_sentences} over 30 words",
    )

    tail = " ".join(sentences[-2:]).lower() if sentences else ""
    payoff_hit = next((p for p in _PAYOFF if p in tail), "")
    payoff_score = 78.0 if payoff_hit else 50.0
    if tail and len(_tokens(sentences[-1])) <= 24:
        payoff_score += 12
    payoff_check = _check(
        "payoff", "Payoff", payoff_score,
        f"closing beat {'lands with “' + payoff_hit + '”' if payoff_hit else 'does not name its own payoff'}",
    )

    cta_hit = bool(set(_tokens(" ".join(sentences[-3:]))) & _CTA)
    cta_check = _check(
        "cta", "Invitation", 100.0 if cta_hit else 45.0,
        "the closing invites an action" if cta_hit else "no quiet invitation to subscribe or comment",
    )

    grams: dict[tuple[str, ...], int] = {}
    for i in range(len(words) - 3):
        gram = tuple(words[i : i + 4])
        grams[gram] = grams.get(gram, 0) + 1
    repeats = sum(count - 1 for count in grams.values() if count > 1)
    content = [w for w in words if w not in _STOP]
    unique_ratio = len(set(content)) / len(content) if content else 1.0
    repetition_score = 100.0 - min(60.0, repeats * 9.0) - max(0.0, 0.45 - unique_ratio) * 120.0
    repetition_check = _check(
        "repetition", "Repetition", repetition_score,
        f"{repeats} repeated four-word phrases, {unique_ratio:.0%} of content words are unique",
    )

    ideal_low, ideal_high = (3, 7) if fmt == "short" else (4, 10)
    structure_score = 100.0 if ideal_low <= len(segments) <= ideal_high else 62.0
    structure_check = _check(
        "structure", "Structure", structure_score,
        f"{len(segments)} spoken segment{'s' if len(segments) != 1 else ''} "
        f"(the house style is {ideal_low}–{ideal_high} for a {fmt})",
    )

    risk_flags: list[dict[str, str]] = []
    risk_text = " ".join(part for part in (text, hook) if part)
    lowered = risk_text.lower()
    for term, note in _RISK_TERMS.items():
        if term in lowered:
            risk_flags.append({"term": term, "note": note})
    for quote in re.findall(r"[\"“](.{45,})[\"”]", risk_text):
        risk_flags.append({"term": quote[:60], "note": "a long quoted passage — confirm the source and fair use"})
    risk_score = _clamp(100.0 - 20.0 * len(risk_flags))
    risk_check = _check(
        "rights", "Rights check", risk_score,
        "no rights flags in the text" if not risk_flags else f"{len(risk_flags)} item(s) need a human look",
    )

    weights = {
        "hook": 0.28, "pacing": 0.17, "clarity": 0.13, "payoff": 0.16,
        "cta": 0.06, "repetition": 0.10, "structure": 0.10,
    }
    scores = {
        "hook": hook_score, "pacing": pacing_score, "clarity": clarity_score,
        "payoff": payoff_score, "cta": cta_check["score"], "repetition": repetition_score,
        "structure": structure_score,
    }
    overall = sum(scores[key] * weight for key, weight in weights.items())
    overall = _clamp(overall * 0.92 + risk_score * 0.08)

    mid = _clamp(38 + (hook_score - 50) * 0.22 + (pacing_score - 50) * 0.14 + (payoff_score - 50) * 0.10, 18, 72)
    retention = {
        "band": f"{int(mid - 6)}–{int(mid + 6)}%",
        "note": "A structural guess for the first half-minute, not a YouTube prediction.",
    }

    suggestions: list[str] = []
    if hook_score < 60:
        suggestions.append("Open on the strangest concrete detail instead of a setup line.")
    if pacing_score < 60:
        direction = "slower" if wpm > 172 else "quicker"
        suggestions.append(f"The read wants to be {direction}; aim for 140–160 words per minute.")
    if clarity_score < 60:
        suggestions.append("Break the longest sentence into two; one idea per breath.")
    if payoff_score < 65:
        suggestions.append("Name the payoff in the last two lines — what should the viewer keep?")
    if not cta_hit:
        suggestions.append("Close with one quiet invitation, not a sales pitch.")
    if repeats:
        suggestions.append(f"Retire {repeats} repeated phrase(s) so the middle feels new.")
    if structure_score < 80:
        suggestions.append("Reshape the middle into 3–6 distinct beats with clean turns.")
    if risk_flags:
        suggestions.append("Resolve the flagged rights items, or cut the flagged passage.")
    if not suggestions:
        suggestions.append("Structurally sound. Read it aloud once before recording.")

    return {
        "ok": True,
        "score": int(round(overall)),
        "grade": _grade(overall),
        "checks": [
            hook_check, pacing_check, clarity_check, payoff_check, cta_check,
            repetition_check, structure_check, risk_check,
        ],
        "metrics": {
            "words": word_count,
            "sentences": len(sentences),
            "segments": len(segments),
            "wpm": round(wpm, 1),
            "avg_sentence_words": round(average, 1),
            "seconds": round(seconds, 1),
        },
        "suggestions": suggestions[:6],
        "hook_variants": _hook_variants(title, hook_text),
        "retention": retention,
        "risk": {
            "level": "clear" if not risk_flags else "review",
            "flags": risk_flags[:8],
            "note": "Heuristics only; not a legal clearance and not a fact check.",
        },
        "analysed_at": _now(),
    }


def analyze_video(video: dict[str, Any]) -> dict[str, Any]:
    return analyze(
        video.get("script") if isinstance(video.get("script"), dict) else {},
        title=str(video.get("title") or ""),
        duration=float(video.get("duration") or 0.0),
        fmt=str(video.get("format") or "short"),
    )


def summary(report: dict[str, Any] | None) -> str:
    if not report or not report.get("ok"):
        return "Not read yet"
    weak = [c["label"] for c in report.get("checks", []) if c.get("grade") == "fail"]
    base = f"Editorial score {report.get('score', 0)}/100"
    return base + (f" · weak: {', '.join(weak)}" if weak else " · no fails")


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
