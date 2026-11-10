from __future__ import annotations

from ghostlight import editorial


def _strong_script() -> dict:
    return {
        "hook": "Why did a city of lamps vanish beneath the sea?",
        "target_seconds": 34,
        "segments": [
            {"text": "In 1907, a fishing town reported lights moving under the water."},
            {"text": "The lights were not fire, and they were not boats."},
            {"text": "They were living creatures, each one flashing a different code."},
            {"text": "For ninety years, nobody could prove what the signals meant."},
            {"text": "The trick is simpler than it sounds: the light is a conversation."},
            {"text": "So next time you picture the deep, remember the quiet city."},
            {"text": "If this stayed with you, subscribe for one strange idea at a time."},
        ],
    }


def _weak_script() -> dict:
    sentence = "It was very dark and very deep and it was very cold and very quiet and the water was dark and deep and cold."
    return {"hook": "", "target_seconds": 40, "segments": [{"text": " ".join([sentence] * 4)}]}


def test_empty_script_is_not_scored():
    report = editorial.analyze({}, title="Nothing yet")
    assert report["ok"] is False
    assert report["checks"] == []
    assert report["suggestions"]


def test_strong_script_scores_well_and_reports_every_check():
    report = editorial.analyze(_strong_script(), title="The Quiet City", duration=34.0, fmt="short")
    assert report["ok"] is True
    assert 0 <= report["score"] <= 100
    assert report["grade"] in {"pass", "warn"}
    assert len(report["checks"]) == 8
    assert {c["key"] for c in report["checks"]} >= {"hook", "pacing", "clarity", "payoff", "rights"}
    assert report["metrics"]["segments"] == 7
    assert report["hook_variants"]
    assert "structural guess" in report["retention"]["note"]
    assert report["risk"]["level"] == "clear"


def test_weak_script_gets_notes_not_a_forecast():
    report = editorial.analyze(_weak_script(), title="Dark Water", duration=40.0, fmt="short")
    assert report["score"] < 80
    assert report["suggestions"]
    assert report["retention"]["band"].endswith("%")
    assert "YouTube prediction" in report["retention"]["note"]


def test_rights_terms_raise_a_review_flag():
    script = {
        "hook": "A strange discovery, adapted from a forgotten diary.",
        "segments": [{"text": "The soundtrack was found beside the song lyrics. A study says the room was silent."}],
    }
    report = editorial.analyze(script, title="Found Sound", duration=30.0)
    assert report["risk"]["level"] == "review"
    terms = {flag["term"] for flag in report["risk"]["flags"]}
    assert {"lyrics", "soundtrack", "adapted from", "study says"} <= terms
    rights = next(c for c in report["checks"] if c["key"] == "rights")
    assert rights["grade"] != "pass"


def test_analyze_video_reads_script_and_format():
    video = {
        "title": "The Quiet City",
        "format": "long",
        "duration": 240.0,
        "script": _strong_script(),
    }
    report = editorial.analyze_video(video)
    assert report["ok"] is True
    assert report["metrics"]["seconds"] == 240.0
    assert editorial.summary(report).startswith("Editorial score")


def test_summary_says_when_not_read():
    assert editorial.summary(None) == "Not read yet"
    assert editorial.summary({"ok": False}) == "Not read yet"
