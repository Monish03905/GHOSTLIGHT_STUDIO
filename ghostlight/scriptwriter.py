from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from . import content, novelty
from .config import Config
from .db import Database
from .llm import LLMClient, LLMError, provider_status
from . import prompts

EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]")
URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
STAGE_RE = re.compile(r"\[[^\]]{1,40}\]|\((?:pause|beat|music|silence|softly)[^)]{0,30}\)", re.IGNORECASE)
SPEAKER_RE = re.compile(r"^\s*(?:narrator|voiceover|voice|speaker)\s*:\s*", re.IGNORECASE)
HASHTAG_RE = re.compile(r"#\w+")
EXTRA_BANNED = ["as an ai", "language model", "in conclusion", "to sum up", "stay tuned"]


class ScriptError(RuntimeError):
    def __init__(self, message: str, issues: list[str] | None = None):
        super().__init__(message)
        self.issues = issues or []


@dataclass
class WriteResult:
    script: dict[str, Any]
    brief: dict[str, Any]
    fingerprint: dict[str, Any]
    novelty: dict[str, Any]
    provider: str
    attempts: int
    issues: list[str] = field(default_factory=list)


def _clean_text(text: str) -> str:
    text = str(text or "")
    text = EMOJI_RE.sub("", text)
    text = STAGE_RE.sub("", text)
    text = SPEAKER_RE.sub("", text)
    text = text.replace("**", "").replace("__", "").replace("*", "")
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip('"').strip()


def _first_sentence(text: str) -> str:
    match = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)
    return match[0].strip() if match else text.strip()


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'’]+", text))


def _trim_title(title: str, limit: int) -> str:
    title = title.strip(" .-—|")
    if len(title) <= limit:
        return title
    cut = title[:limit].rsplit(" ", 1)[0].strip(" .-—|")
    return cut or title[:limit]


class ScriptWriter:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        on_event: Callable[[str, str, str], None] | None = None,
    ):
        self.cfg = cfg
        self.db = db
        self.on_event = on_event or (lambda level, kind, message: None)
        self.client = LLMClient(cfg)
        self.provider = self.client.provider

    def _emit(self, message: str, level: str = "info", kind: str = "script") -> None:
        self.on_event(level, kind, message)

    def word_window(self, fmt: str) -> tuple[int, int]:
        wpm = int(self.cfg.get("script.words_per_minute", 152))
        if fmt == "short":
            low, high = self.cfg.get("script.short_seconds", [28, 46])
        else:
            low, high = self.cfg.get("script.long_seconds", [200, 380])
        min_words = max(50, int(float(low) / 60.0 * wpm * 0.85))
        max_words = max(min_words + 40, int(float(high) / 60.0 * wpm * 1.15))
        return min_words, max_words

    def write(
        self,
        fmt: str = "short",
        niche: str | None = None,
        topic: str | None = None,
        format_override: str | None = None,
        guidance: str = "",
        seed: int | None = None,
        style_override: str | None = None,
        palette_override: str | None = None,
        tone_override: str | None = None,
        audience_override: str | None = None,
    ) -> WriteResult:
        if fmt not in {"short", "long"}:
            fmt = "short"
        niches = [n for n in self.cfg.get("creator.niches", []) if n in content.NICHES] or content.niche_keys()
        recent = self.db.recent_titles(int(self.cfg.get("novelty.recent_for_prompt", 40)))
        prior = self.db.all_fingerprints()
        used_subjects = {
            content.subject_key(str((row.get("fingerprint") or {}).get("premise_parts", {}).get("subject", "")))
            for row in prior
        }
        used_subjects.discard("")
        avoid = [str(x) for x in self.cfg.get("creator.avoid_topics", []) if str(x).strip()]
        threshold = float(self.cfg.get("novelty.max_similarity", 0.30))
        attempts = max(1, int(self.cfg.get("novelty.attempts", 4)))
        min_words, max_words = self.word_window(fmt)
        target = tuple(self.cfg.get("script.short_seconds" if fmt == "short" else "script.long_seconds", [28, 46]))
        style_cfg = str(self.cfg.get("visuals.style", "auto"))
        if style_override not in content.STYLE_KEYS:
            style_override = None if style_cfg in {"", "auto"} else style_cfg
        if palette_override not in content.PALETTES:
            palette_override = None

        try:
            status = provider_status(self.cfg)
            using_llm = self.provider != "offline" and status.available
            if using_llm:
                self._emit(f"Writing with {status.name} · {status.model}")
            else:
                reason = "offline mode" if self.provider == "offline" else status.detail or "provider unavailable"
                self._emit(f"Writing with the Muse ({reason})")
        except Exception as exc:
            self._emit(f"Provider check failed ({exc}); writing with the Muse.", level="warn", kind="warn")
            using_llm = False

        feedback = guidance.strip()
        issues: list[str] = []
        attempted_titles: list[str] = []
        best_candidate: WriteResult | None = None

        for attempt in range(1, attempts + 1):
            brief = content.make_brief(
                niches,
                fmt=fmt,
                niche_key=niche,
                topic=topic if attempt == 1 or topic else None,
                used_subjects=used_subjects,
                used_titles=[r.get("title", "") for r in recent] + attempted_titles,
                style_override=style_override,
                palette_override=palette_override,
                format_override=format_override,
                tone=tone_override if tone_override is not None else self.cfg.get("creator.tone", ""),
                audience=audience_override if audience_override is not None else self.cfg.get("creator.audience", ""),
                target_seconds=(int(target[0]), int(target[1])),
                seed=seed + attempt * 7919 if seed is not None else None,
            )
            attempted_titles.append(str(brief.get("subject", "")))

            provider_label = "muse"
            raw: dict[str, Any]
            if using_llm:
                user_prompt = prompts.script_prompt(
                    brief,
                    fmt,
                    min_words,
                    max_words,
                    recent,
                    avoid,
                    feedback=feedback,
                )
                if guidance and attempt == 1:
                    user_prompt += f"\nADDITIONAL DIRECTION FROM THE DIRECTOR\n{guidance}\n"
                try:
                    raw = self.client.complete_json(prompts.system_prompt(self.cfg), user_prompt)
                    provider_label = f"{self.provider}/{self.client.model}"
                except LLMError as exc:
                    self._emit(f"Model call failed ({exc}); falling back to the Muse.", level="warn", kind="warn")
                    using_llm = False
                    raw = content.compose_offline_script(
                        brief, fmt=fmt, words_min=min_words, words_max=max_words, recent_titles=[r.get("title", "") for r in recent]
                    )
                    provider_label = "muse"
            else:
                raw = content.compose_offline_script(
                    brief, fmt=fmt, words_min=min_words, words_max=max_words, recent_titles=[r.get("title", "") for r in recent]
                )

            script = self.normalize(raw, brief, fmt)
            candidate_issues = self.validate(script, brief, fmt, min_words, max_words, recent, avoid)

            if not candidate_issues:
                fingerprint = novelty.make_fingerprint(script, brief)
                novelty_result = novelty.evaluate(fingerprint, prior, threshold)
                if not novelty_result["accepted"]:
                    nearest = novelty_result.get("nearest_title") or "an earlier film"
                    candidate_issues.append(
                        f"Too similar to '{nearest}' (similarity {novelty_result['score']:.2f}, "
                        f"limit {threshold:.2f}). Choose a different subject, lens and imagery."
                    )
                    if (
                        best_candidate is None
                        or novelty_result["score"]
                        < float(best_candidate.novelty.get("score", 1.0))
                    ):
                        best_candidate = WriteResult(
                            script=script,
                            brief=brief,
                            fingerprint=fingerprint,
                            novelty=novelty_result,
                            provider=provider_label,
                            attempts=attempt,
                            issues=candidate_issues,
                        )

            if candidate_issues:
                issues = candidate_issues
                feedback = " ".join(candidate_issues)
                self._emit(
                    f"Draft {attempt} set aside — {candidate_issues[0][:160]}",
                    level="warn",
                    kind="novelty",
                )
                continue

            result = WriteResult(
                script=script,
                brief=brief,
                fingerprint=fingerprint,
                novelty=novelty_result,
                provider=provider_label,
                attempts=attempt,
            )
            self._emit(
                f"Script accepted: “{script['title']}” · novelty {novelty_result['novelty']:.2f} "
                f"· {_word_count(script['narration'])} words",
                level="ok",
                kind="script",
            )
            return result

        if best_candidate is not None:
            raise ScriptError(
                "No sufficiently original draft was produced. The nearest existing film still shares too much.",
                issues=issues,
            )
        raise ScriptError("The writer could not produce a valid script.", issues=issues)

    # -- normalisation and validation -----------------------------------
    def normalize(self, raw: Any, brief: dict[str, Any], fmt: str) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ScriptError("The writer returned something other than a script object.")

        title = _clean_text(HASHTAG_RE.sub("", str(raw.get("title", ""))))
        title = re.sub(r"\s*#?shorts?\s*$", "", title, flags=re.IGNORECASE)
        title = _trim_title(title, int(self.cfg.get("script.max_title_chars", 88)))
        if len(title) < 10:
            title = content.offline_title(brief, content.get_niche(brief["niche"]), random.Random(brief["seed"]))
            title = _trim_title(title, int(self.cfg.get("script.max_title_chars", 88)))

        raw_segments = raw.get("segments")
        if isinstance(raw_segments, str):
            raw_segments = [{"text": raw_segments}]
        if not isinstance(raw_segments, list):
            raw_segments = []
        segments: list[dict[str, str]] = []
        for item in raw_segments:
            if isinstance(item, str):
                text, heading = item, ""
            elif isinstance(item, dict):
                text = item.get("text", "")
                heading = _clean_text(item.get("heading", ""))
                if len(heading) > 70:
                    heading = heading[:70].rsplit(" ", 1)[0]
            else:
                continue
            text = _clean_text(text)
            if not text:
                continue
            if SPEAKER_RE.match(text):
                text = SPEAKER_RE.sub("", text)
            segments.append({"heading": heading, "text": text})

        if not segments:
            hook = _clean_text(raw.get("hook", ""))
            if hook:
                segments = [{"heading": "", "text": hook}]
        if not segments:
            raise ScriptError("The writer returned no spoken lines.")

        fmt_obj = content.get_format(brief.get("format", ""))
        if fmt == "long":
            if not any(seg["heading"] for seg in segments):
                acts = sorted({0, max(1, len(segments) // 3), max(2, (2 * len(segments)) // 3)})
                for idx, heading in zip(acts, fmt_obj.headings):
                    if idx < len(segments):
                        segments[idx]["heading"] = heading
        else:
            for seg in segments:
                seg["heading"] = ""

        narration = " ".join(seg["text"] for seg in segments).strip()
        hook = _first_sentence(segments[0]["text"])[:400]

        description = _clean_text(raw.get("description", ""))
        description = URL_RE.sub("", description)
        description = HASHTAG_RE.sub("", description)
        description = re.sub(r"\s+", " ", description).strip()
        if len(description) < 25:
            description = (
                f"{_first_sentence(segments[0]['text'])} "
                f"A quiet essay on {brief['subject']}, seen through {brief['lens']}."
            )
        description = description[:4500]

        tags_raw = raw.get("tags", [])
        if isinstance(tags_raw, str):
            tags_raw = re.split(r"[,\n]", tags_raw)
        tags: list[str] = []
        if isinstance(tags_raw, list):
            for tag in tags_raw:
                cleaned = _clean_text(HASHTAG_RE.sub("", str(tag))).lower().strip(" .,-")
                if 2 < len(cleaned) <= 40 and cleaned not in tags:
                    tags.append(cleaned)
        if len(tags) < 5:
            for fallback in [
                brief["niche"].replace("_", " "),
                brief["lens"],
                brief["concept"],
                "essay",
                "ghostlight studio",
                "quiet video essay",
            ]:
                fallback = fallback.lower()
                if 2 < len(fallback) <= 40 and fallback not in tags:
                    tags.append(fallback)
        tags = tags[:12]

        thumb = _clean_text(str(raw.get("thumbnail_text", ""))).upper()
        thumb = re.sub(r"[^A-Z0-9 &'’-]", " ", thumb)
        thumb = re.sub(r"\s+", " ", thumb).strip()[:30]
        if len(thumb) < 3:
            thumb = content.offline_thumbnail_text(brief, title)

        style = str(raw.get("visual_style", "")).lower()
        if style not in content.STYLE_KEYS:
            style = brief.get("style", "aurora")
        mood = str(raw.get("music_mood", "")).lower()
        if mood not in content.MOOD_KEYS:
            mood = brief.get("mood", "wonder")

        closing = _clean_text(raw.get("closing_line", "")) or segments[-1]["text"]
        if closing not in narration:
            closing = segments[-1]["text"]

        return {
            "title": title,
            "hook": hook,
            "segments": segments,
            "narration": narration,
            "description": description,
            "tags": tags,
            "thumbnail_text": thumb,
            "visual_style": style,
            "music_mood": mood,
            "closing_line": closing,
            "format": fmt,
            "niche": brief["niche"],
        }

    def validate(
        self,
        script: dict[str, Any],
        brief: dict[str, Any],
        fmt: str,
        min_words: int,
        max_words: int,
        recent: list[dict[str, str]],
        avoid: list[str],
    ) -> list[str]:
        issues: list[str] = []
        title = script["title"]
        narration = script["narration"]
        words = _word_count(narration)
        max_title = int(self.cfg.get("script.max_title_chars", 88))

        if not (10 <= len(title) <= max_title):
            issues.append(f"Title must be 10-{max_title} characters.")
        if not title or title.lower().startswith(("part ", "episode ")):
            issues.append("Title reads like part of a series; make it standalone.")
        if _word_count(narration) < min_words * 0.88:
            issues.append(f"Narration is too short ({words} words; target {min_words}-{max_words}).")
        if _word_count(narration) > max_words * 1.12:
            issues.append(f"Narration is too long ({words} words; target {min_words}-{max_words}).")

        segments = script["segments"]
        hard_max = 8 if fmt == "short" else 18
        if not (3 <= len(segments) <= hard_max):
            issues.append(f"Use 3-{hard_max} spoken segments.")
        if any(_word_count(seg["text"]) < 4 for seg in segments):
            issues.append("Every segment must contain a full spoken thought.")

        all_text = f"{title}\n{narration}"
        cliches = novelty.cliche_hits(all_text)
        if cliches:
            issues.append(f"Remove these clichés: {', '.join(cliches[:4])}.")
        continuity = novelty.continuity_hits(all_text)
        if continuity:
            issues.append(f"Remove series/continuity or franchise references: {', '.join(continuity[:4])}.")
        lowered = novelty.normalize(all_text)
        banned = [phrase for phrase in EXTRA_BANNED if phrase in lowered]
        if banned:
            issues.append(f"Remove meta/AI phrasing: {', '.join(banned)}.")
        if URL_RE.search(all_text):
            issues.append("Remove URLs from the script.")
        for topic in avoid:
            if topic and novelty.normalize(topic) in lowered:
                issues.append(f"The director asked to avoid: {topic}.")
        for item in recent:
            prior_title = novelty.normalize(item.get("title", ""))
            if prior_title and prior_title == novelty.normalize(title):
                issues.append(f"A film with the title “{item.get('title')}” already exists.")
                break
        if script["description"].count("  ") > 0:
            issues.append("Description contains doubled spaces.")
        if len(script["tags"]) < 5:
            issues.append("Provide at least five useful tags.")

        seen = set()
        for seg in segments:
            key = novelty.normalize(seg["text"])
            if key in seen:
                issues.append("A spoken line is repeated verbatim.")
                break
            seen.add(key)

        if fmt == "short" and words > 175:
            issues.append("Shorts must stay under 175 spoken words.")
        return issues


def novelty_report(writer: ScriptWriter, fmt: str, threshold: float | None = None) -> dict[str, Any]:
    limit = float(threshold if threshold is not None else writer.cfg.get("novelty.max_similarity", 0.30))
    prior = writer.db.all_fingerprints()
    total = len(prior)
    return {
        "films_on_record": total,
        "threshold": limit,
        "note": (
            "Every accepted script is fingerprinted and checked against the full ledger. "
            "Standalone and anti-continuity rules are also enforced in the writer prompt and validator."
        ),
    }
