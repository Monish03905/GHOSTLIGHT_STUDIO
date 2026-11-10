from __future__ import annotations

from pathlib import Path

import pytest

from ghostlight import repurpose

SENTENCES = [
    "Why does the deep sea glow at all?",
    "Nothing down there has ever seen the sun.",
    "The light is made by living creatures, not by fire.",
    "A single shrimp can flash blue for a fraction of a second.",
    "That flash is a language older than trees.",
    "Some fish answer with a slower pulse of green.",
    "Researchers count thousands of these signals each night.",
    "The dark is not empty, it is crowded with quiet lamps.",
    "So the next time you imagine the ocean floor, remember this.",
    "It is not a void. It is a city that never turns its lights off.",
]


def _words(text: str, start: float = 0.0, step: float = 0.42) -> list[dict]:
    out: list[dict] = []
    clock = start
    for token in text.split():
        out.append({"text": token, "start": round(clock, 3), "end": round(clock + 0.34, 3)})
        clock += step
    return out


def _narration() -> dict:
    words: list[dict] = []
    clock = 0.0
    for sentence in SENTENCES:
        chunk = _words(sentence, start=clock)
        words.extend(chunk)
        clock = chunk[-1]["end"] + 0.7
    return {"words": words, "segments": []}


def test_beats_split_on_spoken_sentences():
    beats = repurpose.beats_from_words(_narration()["words"])
    assert len(beats) >= len(SENTENCES)
    assert beats[0].text.startswith("Why does the deep sea glow")
    assert beats[0].text.endswith("?")
    assert all(beat.end >= beat.start for beat in beats)
    assert all(beat.words for beat in beats)


def test_narration_falls_back_to_segment_timings():
    beats = repurpose.beats_from_narration({
        "segments": [
            {"text": "A first complete thought.", "start": 0.0, "end": 5.0},
            {"text": "A second complete thought.", "start": 5.4, "end": 11.0},
        ]
    })
    assert len(beats) == 2
    assert beats[1].start == pytest.approx(5.4)
    assert beats[0].words


def test_narration_without_timings_is_rejected():
    with pytest.raises(repurpose.RepurposeError):
        repurpose.beats_from_narration({})


def test_score_window_rewards_a_question_hook():
    beats = repurpose.beats_from_narration(_narration())
    question = repurpose.score_window(beats, 0, 3)
    flat = repurpose.score_window(beats, 2, 5)
    assert 0 <= flat <= 100
    assert question >= flat


def test_plan_returns_non_overlapping_in_range_cuts():
    video = {"title": "The Living Light", "duration": 70.0}
    plan = repurpose.plan(video, _narration(), count=3)
    clips = plan["candidates"]
    assert 1 <= len(clips) <= 3
    assert plan["beats"] >= len(SENTENCES)
    for clip in clips:
        assert repurpose.MIN_CLIP - 1.5 <= clip["duration"] <= repurpose.MAX_CLIP + 0.01
        assert clip["score"] > 0
        assert clip["title"]
        assert clip["digest"]
    ordered = sorted(clips, key=lambda c: c["start"])
    for left, right in zip(ordered, ordered[1:]):
        assert right["start"] >= left["end"] - 0.001


def test_plan_avoids_existing_ranges():
    video = {"title": "The Living Light", "duration": 70.0}
    everything = repurpose.plan(video, _narration(), count=3)["candidates"][0]
    avoided = repurpose.plan(
        video, _narration(), count=3,
        avoid=[{"clip_start": 0.0, "clip_end": 999.0, "title": "taken", "hook": "taken"}],
    )
    assert avoided["candidates"] == []
    assert everything["start"] >= 0


def test_plan_clamps_count():
    video = {"title": "The Living Light", "duration": 70.0}
    assert len(repurpose.plan(video, _narration(), count=99)["candidates"]) <= 6
    assert len(repurpose.plan(video, _narration(), count=-5)["candidates"]) >= 1


def _long_narration() -> dict:
    narration = _narration()
    words = narration["words"]
    tail = max(word["end"] for word in words) + 1.0
    words = words + [
        {**word, "start": word["start"] + tail, "end": word["end"] + tail}
        for word in narration["words"]
    ]
    return {"words": words}


def test_candidate_from_range_validates_bounds():
    video = {"title": "The Living Light", "duration": 70.0}
    with pytest.raises(repurpose.RepurposeError):
        repurpose.candidate_from_range(video, _narration(), 2.0, 6.0)
    with pytest.raises(repurpose.RepurposeError):
        repurpose.candidate_from_range(video, _long_narration(), 0.0, 75.0)
    candidate = repurpose.candidate_from_range(video, _narration(), 1.0, 20.0)
    assert candidate.start == pytest.approx(1.0)
    assert candidate.end == pytest.approx(20.0)
    assert "Cut by hand" in candidate.reason


def test_build_clip_ass_writes_relative_timed_lines(tmp_path: Path):
    words = _words("The sea glows because the living make their own light.", start=10.0)
    out = repurpose.build_clip_ass(words, 12.0, 20.0, tmp_path / "clip.ass")
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in text
    assert "PlayResY: 1920" in text
    assert "Dialogue: 0,0:00:00.00" in text
    assert "0:00:02.00" not in text.split("[Events]")[1]
    for line in text.split("[Events]")[1].splitlines():
        if line.startswith("Dialogue:"):
            spoken = line.rsplit(",", 1)[-1]
            assert len(spoken.split()) <= 5


def test_render_clip_wires_ffmpeg(monkeypatch, tmp_path: Path):
    source = tmp_path / "film.mp4"
    source.write_bytes(b"source")
    calls = []

    def fake_run(args, cwd=None, timeout=None):
        calls.append(list(args))
        target = Path(cwd) / args[-1]
        target.write_bytes(b"video")
        return None

    monkeypatch.setattr(repurpose.ffmpeg, "run", fake_run)
    out = tmp_path / "clips" / "clip.mp4"
    rendered = repurpose.render_clip(
        source, out, 4.0, 14.0,
        words=_words("A complete thought ends here.", start=4.0),
        width=1080, height=1920, fps=30, crf=22,
    )
    assert rendered.path == out
    assert rendered.bytes == 5
    assert rendered.thumb is not None and rendered.thumb.name == "clip_thumb.jpg"
    assert rendered.captions is not None and rendered.captions.suffix == ".ass"
    args = calls[0]
    assert args[args.index("-ss") + 1] == "4.000"
    assert args[args.index("-t") + 1] == "10.000"
    graph = args[args.index("-filter_complex") + 1]
    assert "boxblur" in graph and "overlay" in graph and "ass=clip_subs.ass" in graph
    assert calls[1][-1] == "clip_thumb.jpg"
