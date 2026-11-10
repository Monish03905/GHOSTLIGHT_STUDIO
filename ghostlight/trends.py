from __future__ import annotations

import hashlib
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from . import novelty

# A hand-curated radar, one shelf per niche. The studio never copies a viral
# video: these are raw materials for an original, standalone essay.
TREND_CATALOG: dict[str, list[dict[str, Any]]] = {
    "cosmic": [
        {
            "topic": "the oldest light in the universe",
            "angle": "what it means that the first light is still arriving",
            "why": "Every telescope image is a letter that left before the reader existed.",
            "tags": ["cosmology", "light", "deep time"],
            "heat": 88,
            "momentum": 16,
            "competition": 44,
            "window": "evergreen",
        },
        {
            "topic": "why the Moon is drifting away",
            "angle": "the quiet arithmetic of a relationship ending",
            "why": "The Moon recedes a few centimetres a year; the number is small enough to feel personal.",
            "tags": ["moon", "orbits", "tides"],
            "heat": 82,
            "momentum": 24,
            "competition": 51,
            "window": "this week",
        },
        {
            "topic": "the sound of a black hole",
            "angle": "listening to the lowest note in the universe",
            "why": "Sonified black-hole data keeps resurfacing because the sound is stranger than the theory.",
            "tags": ["black holes", "sound", "gravity"],
            "heat": 79,
            "momentum": 30,
            "competition": 38,
            "window": "this week",
        },
        {
            "topic": "Europa's hidden ocean",
            "angle": "an ocean under ice with no shoreline",
            "why": "Missions are converging on Europa, and the ocean is still mostly a rumour.",
            "tags": ["europa", "oceans", "space"],
            "heat": 74,
            "momentum": 12,
            "competition": 33,
            "window": "evergreen",
        },
        {
            "topic": "what happens when the Sun dies",
            "angle": "the long disposal of a star that made everything",
            "why": "The end of the Sun is a reliable, slow-burning fascination.",
            "tags": ["sun", "stars", "deep time"],
            "heat": 81,
            "momentum": 8,
            "competition": 62,
            "window": "evergreen",
        },
        {
            "topic": "the Voyager probes' last signal",
            "angle": "the distance at which a machine stops being ours",
            "why": "Voyager keeps turning up in feeds because the silence is now measured in years.",
            "tags": ["voyager", "probes", "signal"],
            "heat": 86,
            "momentum": 26,
            "competition": 47,
            "window": "this week",
        },
        {
            "topic": "the dust between stars",
            "angle": "the ordinary material that hides the whole sky",
            "why": "Interstellar dust reddens distant light and keeps the far universe partly under a veil.",
            "tags": ["dust", "interstellar", "light"],
            "heat": 63,
            "momentum": 6,
            "competition": 22,
            "window": "evergreen",
        },
    ],
    "deep_sea": [
        {
            "topic": "the light beneath the ice",
            "angle": "bioluminescence as the ocean's private language",
            "why": "Deep-sea footage performs because so little of the ocean has been looked at.",
            "tags": ["ocean", "light", "bioluminescence"],
            "heat": 90,
            "momentum": 22,
            "competition": 55,
            "window": "this week",
        },
        {
            "topic": "the midnight zone",
            "angle": "a place that is neither night nor day",
            "why": "The mesopelagic is the largest habitat on Earth and the least visited.",
            "tags": ["ocean", "depth", "dark"],
            "heat": 76,
            "momentum": 18,
            "competition": 31,
            "window": "evergreen",
        },
        {
            "topic": "whale falls",
            "angle": "an entire city built on one ending",
            "why": "A whale carcass can feed a community for decades; the image is impossible to forget.",
            "tags": ["whales", "deep sea", "ecosystem"],
            "heat": 84,
            "momentum": 14,
            "competition": 39,
            "window": "evergreen",
        },
        {
            "topic": "the sound of the deepest trench",
            "angle": "the hull creak that scientists mistook for a creature",
            "why": "The Challenger Deep has a soundscape; the first recordings still circulate.",
            "tags": ["trench", "sound", "ocean"],
            "heat": 71,
            "momentum": 9,
            "competition": 27,
            "window": "evergreen",
        },
        {
            "topic": "the ghost octopus",
            "angle": "a pale animal that broods in the dark for years",
            "why": "The octopus breeding story is quiet, strange and almost unbearably patient.",
            "tags": ["octopus", "deep sea", "patience"],
            "heat": 87,
            "momentum": 20,
            "competition": 46,
            "window": "this week",
        },
        {
            "topic": "the ocean's slow heartbeat",
            "angle": "the way water remembers a coast",
            "why": "Coastal change is tangible and local, which makes it travel.",
            "tags": ["ocean", "coast", "tides"],
            "heat": 64,
            "momentum": 11,
            "competition": 24,
            "window": "evergreen",
        },
    ],
    "forgotten_history": [
        {
            "topic": "the last speaker of a language",
            "angle": "what disappears when nobody is left to say it",
            "why": "Language loss is a recurring, emotionally legible history story.",
            "tags": ["language", "memory", "history"],
            "heat": 89,
            "momentum": 23,
            "competition": 49,
            "window": "this week",
        },
        {
            "topic": "a city erased from the maps",
            "angle": "the bureaucracy of forgetting a place",
            "why": "Redacted towns and vanished villages are reliable obsessions.",
            "tags": ["maps", "archive", "places"],
            "heat": 83,
            "momentum": 19,
            "competition": 41,
            "window": "this week",
        },
        {
            "topic": "the radio that never answered",
            "angle": "a signal sent so far it has no audience yet",
            "why": "The Arecibo message is a small, durable hook in the history of listening.",
            "tags": ["radio", "signal", "century"],
            "heat": 72,
            "momentum": 12,
            "competition": 29,
            "window": "evergreen",
        },
        {
            "topic": "the missing lighthouse keepers",
            "angle": "the room where everything stayed exactly where it was",
            "why": "A tidy mystery draws in viewers; keep the facts and leave the file open.",
            "tags": ["lighthouse", "archive", "mystery"],
            "heat": 85,
            "momentum": 17,
            "competition": 57,
            "window": "this week",
        },
        {
            "topic": "abandoned radar stations",
            "angle": "the architecture of a threat that never arrived",
            "why": "Concrete ghosts photograph well and tell a century's mood.",
            "tags": ["abandoned", "radar", "cold war"],
            "heat": 69,
            "momentum": 10,
            "competition": 26,
            "window": "evergreen",
        },
        {
            "topic": "the town under the reservoir",
            "angle": "what the water kept",
            "why": "Drowned villages surface in dry summers and return when the water does.",
            "tags": ["reservoir", "village", "water"],
            "heat": 78,
            "momentum": 21,
            "competition": 35,
            "window": "seasonal",
        },
    ],
    "human_mind": [
        {
            "topic": "why you remember songs but not names",
            "angle": "the odd economy of memory",
            "why": "Naming the feeling of forgetting makes it shareable in one line.",
            "tags": ["memory", "music", "brain"],
            "heat": 92,
            "momentum": 28,
            "competition": 61,
            "window": "this week",
        },
        {
            "topic": "the doorway that erases a thought",
            "angle": "walking into a room and losing the reason",
            "why": "Everyone has done this; the explanation is more interesting than the joke.",
            "tags": ["memory", "attention", "everyday"],
            "heat": 88,
            "momentum": 25,
            "competition": 54,
            "window": "this week",
        },
        {
            "topic": "why silence feels loud",
            "angle": "the brain turning up the volume on nothing",
            "why": "Tinnitus and auditory hallucinations sit at a strange border of self and signal.",
            "tags": ["silence", "hearing", "brain"],
            "heat": 73,
            "momentum": 15,
            "competition": 30,
            "window": "evergreen",
        },
        {
            "topic": "the feeling of being watched",
            "angle": "a mind that treats the dark as a room full of eyes",
            "why": "Watchfulness is a leftover, and leftovers are always good essays.",
            "tags": ["attention", "fear", "mind"],
            "heat": 80,
            "momentum": 13,
            "competition": 43,
            "window": "evergreen",
        },
        {
            "topic": "why time speeds up with age",
            "angle": "the proportion trick that steals a summer",
            "why": "The relative-length explanation lands well and invites comments.",
            "tags": ["time", "memory", "aging"],
            "heat": 90,
            "momentum": 27,
            "competition": 66,
            "window": "this week",
        },
        {
            "topic": "the mind's autopilot",
            "angle": "the part of the day that nobody was present for",
            "why": "Highway hypnosis and autopilot are a gentle way into attention.",
            "tags": ["attention", "habit", "mind"],
            "heat": 67,
            "momentum": 8,
            "competition": 25,
            "window": "evergreen",
        },
    ],
    "quiet_tech": [
        {
            "topic": "machines that forget on purpose",
            "angle": "the design case for uselessness",
            "why": "AI memory is a live conversation; a quiet counterpoint stands out.",
            "tags": ["technology", "memory", "design"],
            "heat": 84,
            "momentum": 29,
            "competition": 58,
            "window": "this week",
        },
        {
            "topic": "the last payphone",
            "angle": "a public machine with no public left",
            "why": "Disappearing infrastructure is a soft, visual nostalgia story.",
            "tags": ["payphone", "infrastructure", "nostalgia"],
            "heat": 79,
            "momentum": 18,
            "competition": 32,
            "window": "evergreen",
        },
        {
            "topic": "why software ages",
            "angle": "the slow decay of perfectly logical machines",
            "why": "Developers share this one; the metaphor of rust applies to code.",
            "tags": ["software", "decay", "engineering"],
            "heat": 68,
            "momentum": 14,
            "competition": 28,
            "window": "evergreen",
        },
        {
            "topic": "the hum of a data center",
            "angle": "the sound of the cloud made physical",
            "why": "The cloud is invisible, which makes the physical sound satisfying.",
            "tags": ["data centers", "sound", "cloud"],
            "heat": 81,
            "momentum": 22,
            "competition": 37,
            "window": "this week",
        },
        {
            "topic": "a machine that listens for earthquakes",
            "angle": "care as a form of attention",
            "why": "Sensor networks are quietly heroic and under-told.",
            "tags": ["sensors", "earthquakes", "machines"],
            "heat": 70,
            "momentum": 11,
            "competition": 23,
            "window": "evergreen",
        },
        {
            "topic": "the trouble with autocomplete",
            "angle": "the sentence you did not mean to write",
            "why": "Predictive text is a daily, slightly uncanny collaborator.",
            "tags": ["autocomplete", "language", "AI"],
            "heat": 86,
            "momentum": 31,
            "competition": 63,
            "window": "this week",
        },
    ],
    "natural_world": [
        {
            "topic": "trees that talk underground",
            "angle": "the forest as a slow conversation",
            "why": "Mycorrhizal networks are a dependable wonder engine.",
            "tags": ["forest", "fungi", "networks"],
            "heat": 91,
            "momentum": 24,
            "competition": 57,
            "window": "this week",
        },
        {
            "topic": "the last silent forest",
            "angle": "what goes missing when the insects go",
            "why": "Quiet nature is an emotional way into an ecological story.",
            "tags": ["forest", "silence", "insects"],
            "heat": 77,
            "momentum": 19,
            "competition": 34,
            "window": "evergreen",
        },
        {
            "topic": "migration that no one sees",
            "angle": "the sky as a bird route",
            "why": "Migration maps make invisible movement visible.",
            "tags": ["migration", "birds", "maps"],
            "heat": 74,
            "momentum": 12,
            "competition": 29,
            "window": "seasonal",
        },
        {
            "topic": "the oldest living thing",
            "angle": "a lifespan that makes nations look temporary",
            "why": "Long-lived trees are a scale story that never quite stops working.",
            "tags": ["trees", "age", "scale"],
            "heat": 85,
            "momentum": 16,
            "competition": 48,
            "window": "evergreen",
        },
        {
            "topic": "snow that glows",
            "angle": "light with no lamp behind it",
            "why": "Bioluminescent snow and glowing seas are visual bait with a real mechanism.",
            "tags": ["snow", "light", "biology"],
            "heat": 72,
            "momentum": 13,
            "competition": 26,
            "window": "seasonal",
        },
        {
            "topic": "the sea's slow heartbeat",
            "angle": "a tide that keeps time with no clock",
            "why": "Tides are ordinary and enormous; the contrast makes a good essay.",
            "tags": ["tide", "ocean", "time"],
            "heat": 66,
            "momentum": 7,
            "competition": 22,
            "window": "evergreen",
        },
    ],
    "liminal_places": [
        {
            "topic": "the airport at 3 a.m.",
            "angle": "a building designed for leaving, briefly empty",
            "why": "Liminal-space imagery is a durable aesthetic; the essay gives it a spine.",
            "tags": ["liminal", "airport", "night"],
            "heat": 89,
            "momentum": 27,
            "competition": 52,
            "window": "this week",
        },
        {
            "topic": "a town under a reservoir",
            "angle": "the steeple that appears when the water drops",
            "why": "Drowned places are a strong visual and a real history.",
            "tags": ["reservoir", "town", "water"],
            "heat": 82,
            "momentum": 21,
            "competition": 39,
            "window": "seasonal",
        },
        {
            "topic": "the last train",
            "angle": "the etiquette of an almost empty carriage",
            "why": "Late-night transit is intimate and instantly recognisable.",
            "tags": ["train", "night", "strangers"],
            "heat": 75,
            "momentum": 16,
            "competition": 31,
            "window": "evergreen",
        },
        {
            "topic": "an empty mall",
            "angle": "retail architecture after the people leave",
            "why": "Dead malls are an internet staple; a restrained essay stands apart.",
            "tags": ["mall", "abandoned", "architecture"],
            "heat": 80,
            "momentum": 18,
            "competition": 44,
            "window": "evergreen",
        },
        {
            "topic": "the edge of the map",
            "angle": "what cartographers put where knowledge stops",
            "why": "Map edges are a beautiful way to talk about certainty.",
            "tags": ["maps", "unknown", "history"],
            "heat": 71,
            "momentum": 10,
            "competition": 25,
            "window": "evergreen",
        },
        {
            "topic": "a motel that never closes",
            "angle": "the room that keeps its light on",
            "why": "Nocturnal motels are a strong opening image for solitude.",
            "tags": ["motel", "night", "solitude"],
            "heat": 68,
            "momentum": 12,
            "competition": 27,
            "window": "evergreen",
        },
    ],
    "everyday_physics": [
        {
            "topic": "why ice is slippery",
            "angle": "a surface that refuses to be simple",
            "why": "The answer is still argued about; that makes it a good essay, not a factoid.",
            "tags": ["ice", "friction", "physics"],
            "heat": 84,
            "momentum": 20,
            "competition": 42,
            "window": "seasonal",
        },
        {
            "topic": "the physics of a spinning coin",
            "angle": "the last second before it decides",
            "why": "A coin's wobble is a compact lesson in instability.",
            "tags": ["coin", "rotation", "physics"],
            "heat": 73,
            "momentum": 14,
            "competition": 28,
            "window": "evergreen",
        },
        {
            "topic": "why the sky is not blue",
            "angle": "the colour that is mostly a story about scattering",
            "why": "A familiar question with an unfamiliar, satisfying depth.",
            "tags": ["sky", "light", "colour"],
            "heat": 78,
            "momentum": 11,
            "competition": 47,
            "window": "evergreen",
        },
        {
            "topic": "the sound of a kettle",
            "angle": "how a small machine announces a phase change",
            "why": "Domestic objects make physics feel close enough to touch.",
            "tags": ["kettle", "sound", "heat"],
            "heat": 65,
            "momentum": 8,
            "competition": 19,
            "window": "evergreen",
        },
        {
            "topic": "how a mirror knows left from right",
            "angle": "the question that is really about you",
            "why": "Mirror puzzles are a reliable comment-section engine.",
            "tags": ["mirror", "symmetry", "perception"],
            "heat": 81,
            "momentum": 19,
            "competition": 45,
            "window": "this week",
        },
        {
            "topic": "the strange life of a soap bubble",
            "angle": "a surface that is always solving a problem",
            "why": "Bubbles are beautiful and mathematically honest.",
            "tags": ["bubbles", "surface", "physics"],
            "heat": 69,
            "momentum": 9,
            "competition": 21,
            "window": "evergreen",
        },
    ],
}

LIVE_CACHE_SECONDS = 1800
_LIVE_LOCK = threading.Lock()
_LIVE_CACHE: dict[str, Any] = {"at": 0.0, "key": "", "items": []}


def _stable(value: str) -> int:
    return int(hashlib.sha1(value.encode("utf-8")).hexdigest()[:12], 16)


def _clamp(value: float, low: float = 1.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _day_key(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).date().isoformat()


def _score(entry: dict[str, Any], niche: str, day: str, fit: float) -> dict[str, Any]:
    seed = _stable(f"{day}:{niche}:{novelty.normalize(entry['topic'])}")
    wobble = (seed % 1000) / 1000.0
    swing = ((seed >> 12) % 1000) / 1000.0
    interest = round(_clamp(float(entry.get("heat", 70)) + (wobble - 0.5) * 16), 1)
    momentum = round(_clamp(float(entry.get("momentum", 10)) + (swing - 0.5) * 18, -100, 100), 1)
    competition = round(_clamp(float(entry.get("competition", 45)) + ((seed >> 24) % 100 - 50) * 0.5), 1)
    momentum_score = _clamp(50.0 + momentum / 2.0, 0, 100)
    opportunity = round(
        0.40 * interest + 0.25 * momentum_score + 0.20 * (100.0 - competition) + 0.15 * (fit * 100.0),
        1,
    )
    grade = "hot" if opportunity >= 78 else "rising" if opportunity >= 64 else "steady" if opportunity >= 50 else "cool"
    return {
        "topic": entry["topic"],
        "angle": entry.get("angle", ""),
        "why": entry.get("why", ""),
        "tags": list(entry.get("tags", [])),
        "window": entry.get("window", "evergreen"),
        "niche": niche,
        "niche_label": _niche_label(niche),
        "interest": interest,
        "momentum": momentum,
        "competition": competition,
        "fit": round(fit, 2),
        "opportunity": opportunity,
        "grade": grade,
        "direction": "up" if momentum >= 8 else "down" if momentum <= -8 else "flat",
        "live": False,
        "source": "catalog",
    }


def _niche_label(key: str) -> str:
    from . import content

    return content.get_niche(key).label if key in content.NICHES else str(key).replace("_", " ")


def _niche_fit(channel: dict[str, Any], niche: str, playbook: dict[str, Any] | None = None) -> float:
    niches = [n for n in (channel.get("niches") or []) if n]
    if not niches:
        return 0.7
    if niche not in niches:
        return 0.28
    base = 0.82
    weights = (playbook or {}).get("niches") or {}
    weight = float(weights.get(niche, 1.0) or 1.0)
    return max(0.35, min(1.0, base + (min(weight, 3.0) - 1.0) * 0.12))


def catalog(niches: list[str] | None = None) -> list[tuple[str, dict[str, Any]]]:
    keys = [n for n in (niches or list(TREND_CATALOG.keys())) if n in TREND_CATALOG] or list(TREND_CATALOG.keys())
    return [(niche, entry) for niche in keys for entry in TREND_CATALOG[niche]]


def fetch_live(geo: str = "US", timeout: float = 4.0) -> list[dict[str, Any]]:
    """Best-effort Google Trends RSS. Never raises; returns [] when offline."""
    key = f"{geo}:{int(time.time() // LIVE_CACHE_SECONDS)}"
    with _LIVE_LOCK:
        if _LIVE_CACHE.get("key") == key:
            return list(_LIVE_CACHE.get("items") or [])

    urls = [
        f"https://trends.google.com/trending/rss?geo={geo}",
        f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}",
    ]
    items: list[dict[str, Any]] = []
    for url in urls:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "GhostlightStudio/1.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(600_000)
            items = _parse_rss(raw)
            if items:
                break
        except Exception:
            continue

    with _LIVE_LOCK:
        _LIVE_CACHE.update({"at": time.time(), "key": key, "items": items})
    return list(items)


def _parse_rss(raw: bytes) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    out: list[dict[str, Any]] = []
    for item in root.iter():
        tag = str(item.tag).split("}")[-1]
        if tag != "item":
            continue
        fields: dict[str, str] = {}
        for child in item:
            name = str(child.tag).split("}")[-1]
            fields[name] = (child.text or "").strip()
        title = fields.get("title", "")
        if not title:
            continue
        traffic = fields.get("approx_traffic", "") or fields.get("traffic", "")
        out.append({
            "topic": title,
            "angle": "a live search signal — find the quiet, human angle beneath the headline",
            "why": f"Searching on Google Trends now{f' ({traffic})' if traffic else ''}.",
            "tags": ["live search"],
            "heat": 84,
            "momentum": 34,
            "competition": 72,
            "window": "this week",
            "source": "Google Trends",
            "live": True,
        })
        if len(out) >= 12:
            break
    return out


def radar(
    channel: dict[str, Any] | None = None,
    *,
    niches: list[str] | None = None,
    now: datetime | None = None,
    live: bool = False,
    geo: str = "US",
    limit: int = 14,
) -> dict[str, Any]:
    channel = channel or {}
    playbook = channel.get("playbook") or {}
    wanted = niches if niches else (channel.get("niches") or [])
    day = _day_key(now)
    rows: list[dict[str, Any]] = []
    for niche, entry in catalog(wanted):
        fit = _niche_fit(channel, niche, playbook)
        scored = _score(entry, niche, day, fit)
        rows.append(scored)

    live_count = 0
    if live:
        seen = {novelty.normalize(row["topic"]) for row in rows}
        for entry in fetch_live(geo=geo):
            key = novelty.normalize(entry["topic"])
            if not key or key in seen:
                continue
            seen.add(key)
            scored = _score(entry, "", day, 0.42)
            scored["niche"] = ""
            scored["niche_label"] = "Live signal"
            scored["live"] = True
            scored["source"] = "Google Trends"
            rows.append(scored)
            live_count += 1

    rows.sort(key=lambda row: (row["opportunity"], row["interest"]), reverse=True)
    top_niche = ""
    if rows:
        top_niche = rows[0].get("niche") or ""
    return {
        "as_of": (_day_date(now)).isoformat(),
        "geo": geo,
        "live": live,
        "live_count": live_count,
        "catalog_count": len(rows) - live_count,
        "top_niche": top_niche,
        "top_niche_label": _niche_label(top_niche) if top_niche else "Live signal",
        "items": rows[: max(1, min(limit, 40))],
        "note": (
            "Opportunity blends interest, momentum, competition and how well the subject fits the "
            "channel. Treat every row as raw material for an original, standalone essay — never as "
            "permission to copy another creator."
        ),
    }


def top_for_channel(channel: dict[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    data = radar(channel, now=now, live=False, limit=1)
    return data["items"][0] if data["items"] else None


def guidance(trend: dict[str, Any]) -> str:
    if not trend:
        return ""
    bits = [f"Current signal: {trend.get('topic', '')}."]
    if trend.get("angle"):
        bits.append(f"Angle: {trend['angle']}.")
    if trend.get("why"):
        bits.append(f"Why it is surfacing: {trend['why']}")
    bits.append(
        "Use the signal as raw material, not a headline. Keep the film standalone, factual and "
        "original; a viewer should never feel they have seen this exact video before."
    )
    return " ".join(bits)


def _day_date(now: datetime | None) -> Any:
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).date()
