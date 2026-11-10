from __future__ import annotations

from pathlib import Path

import pytest

from ghostlight import languages


def _video() -> dict:
    return {
        "id": "film-lang",
        "language": "en",
        "title": "The Living Light",
        "hook": "Why does the deep sea glow?",
        "description": "A short look at light made by living creatures.",
        "tags": ["ocean", "light"],
        "duration": 20.0,
        "script": {
            "segments": [
                {"heading": "", "text": "The sea glows without the sun."},
                {"heading": "", "text": "Living creatures make the light."},
            ]
        },
    }


def _translator(language: str = "hi"):
    calls = []

    def call(system, user):
        calls.append((system, user))
        return {
            "title": "जीवित प्रकाश",
            "hook": "गहरा समुद्र क्यों चमकता है?",
            "description": "जीवित प्राणियों की बनाई रोशनी पर एक छोटा फ़िल्म।",
            "tags": ["समुद्र", "रोशनी"],
            "segments": [
                "समुद्र सूरज के बिना चमकता है।",
                "जीवित प्राणी यह रोशनी बनाते हैं।",
            ],
        }

    call.calls = calls
    return call


def test_language_registry_covers_requested_voices():
    codes = {lang["code"] for lang in languages.options()}
    assert {"en", "hi", "te", "ta"} <= codes
    assert languages.get_language("TE").native == "తెలుగు"
    assert languages.get_language("te").edge_voice.startswith("te-IN-")
    with pytest.raises(languages.LocalizationError):
        languages.get_language("xx")


def test_translate_validates_and_returns_metadata(cfg):
    video = _video()
    fake = _translator()
    out = languages.translate(cfg, video, "hi", translator=fake)
    assert out["language"] == "hi"
    assert out["title"] == "जीवित प्रकाश"
    assert len(out["segments"]) == 2
    assert out["provider"] == "injected translator"
    assert fake.calls and "target_language" in fake.calls[0][1]


def test_translate_refuses_the_source_language(cfg):
    with pytest.raises(languages.LocalizationError):
        languages.translate(cfg, _video(), "en", translator=_translator())


def test_translate_rejects_a_mismatched_segment_count(cfg):
    def short(system, user):
        return {
            "title": "जीवित प्रकाश",
            "hook": "हुक",
            "description": "विवरण",
            "tags": [],
            "segments": ["केवल एक"],
        }

    with pytest.raises(languages.LocalizationError):
        languages.translate(cfg, _video(), "hi", translator=short)


def test_translate_rejects_an_unchanged_script(cfg):
    def unchanged(system, user):
        return {
            "title": "जीवित प्रकाश",
            "hook": "हुक",
            "description": "विवरण",
            "tags": [],
            "segments": [s["text"] for s in _video()["script"]["segments"]],
        }

    with pytest.raises(languages.LocalizationError):
        languages.translate(cfg, _video(), "hi", translator=unchanged)


def test_localize_video_writes_captions_and_stores_the_record(cfg, db):
    video = _video()
    result = languages.localize_video(cfg, db, video, "hi", translator=_translator())
    assert result["status"] == "ready"
    assert result["audio_path"] == ""
    stored = db.list_localizations("film-lang")
    assert len(stored) == 1
    assert stored[0]["language"] == "hi"
    assert stored[0]["title"] == "जीवित प्रकाश"
    srt = Path(stored[0]["srt_path"])
    assert srt.is_file()
    assert "-->" in srt.read_text(encoding="utf-8")


def test_localize_video_keeps_metadata_when_the_voice_fails(cfg, db):
    def broken_voice(texts, lang, workdir):
        raise RuntimeError("no network")

    result = languages.localize_video(
        cfg, db, _video(), "te",
        translator=_translator(),
        voice=True,
        synthesizer=broken_voice,
    )
    assert result["status"] == "ready"
    assert result["audio_path"] == ""
    assert "Voiceover skipped" in result["note"]


def test_localize_video_with_a_voice_synthesizer(cfg, db, tmp_path):
    class Spoken:
        path = tmp_path / "voice.mp3"
        provider = "edge"
        voice = "te-IN-MohanNeural"

    Spoken.path.write_bytes(b"audio")

    result = languages.localize_video(
        cfg, db, _video(), "te",
        translator=_translator(),
        voice=True,
        synthesizer=lambda texts, lang, workdir: Spoken(),
    )
    assert result["audio_path"] == str(Spoken.path)
    assert result["voice"] == "te-IN-MohanNeural"
    stored = db.get_localization("film-lang", "te")
    assert stored["audio_path"] == str(Spoken.path)


def test_localize_video_upserts_a_second_language(cfg, db):
    languages.localize_video(cfg, db, _video(), "hi", translator=_translator())
    languages.localize_video(cfg, db, _video(), "te", translator=_translator())
    assert {item["language"] for item in db.list_localizations("film-lang")} == {"hi", "te"}
    db.delete_localization("film-lang", "te")
    assert [item["language"] for item in db.list_localizations("film-lang")] == ["hi"]


def test_build_localized_srt_times_cues_inside_the_span(tmp_path):
    timed = [
        {"start": 1.0, "end": 6.0,
         "text": "The first thought is complete and it ends with a quiet turn. "
                 "The second follows with a longer explanation."},
        {"start": 6.5, "end": 9.0, "text": "A short closing line."},
    ]
    out = languages.build_localized_srt(timed, tmp_path / "captions.hi.srt")
    text = out.read_text(encoding="utf-8")
    assert "00:00:01,000 -->" in text
    assert "00:00:09,000" in text
    assert text.count("-->") >= 3
    for block in text.strip().split("\n\n"):
        clock = block.splitlines()[1]
        start, end = [part.strip() for part in clock.split("-->")]
        assert start < end


def test_translate_without_a_provider_fails_honestly(cfg):
    cfg.set("script.provider", "offline")
    with pytest.raises(languages.LocalizationError):
        languages.translate(cfg, _video(), "hi")
