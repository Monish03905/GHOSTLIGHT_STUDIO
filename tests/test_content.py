from ghostlight.content import (
    compose_offline_script,
    format_choices,
    get_niche,
    make_brief,
    niche_keys,
)
from ghostlight.render import scene_count


def test_make_brief_shape():
    brief = make_brief(niche_keys(), fmt="short", seed=11)
    for key in ("subject", "lens", "concept", "niche", "seed", "palette", "style", "mood"):
        assert brief.get(key), key


def test_make_brief_respects_niche_choice():
    brief = make_brief(niche_keys(), fmt="short", niche_key="deep_sea", seed=3)
    assert brief["niche"] == "deep_sea"


def test_offline_script_structure():
    brief = make_brief(["cosmic"], fmt="short", seed=5)
    script = compose_offline_script(brief, fmt="short", words_min=60, words_max=120)
    words = sum(len(s["text"].split()) for s in script["segments"])
    assert len(script["title"]) >= 10
    assert script["hook"]
    assert len(script["segments"]) >= 3
    assert 60 <= words <= 130
    assert script["format"] == "short"
    assert script["tags"]


def test_format_choices_partition_by_suitability():
    short = format_choices("short")
    long = format_choices("long")
    everything = format_choices()
    assert short and long
    assert set(short) <= set(everything)
    assert set(long) <= set(everything)


def test_scene_count_bounds():
    assert scene_count(30, True) == 5
    assert scene_count(300, True) == 9
    assert scene_count(30, False) == 8
    assert scene_count(4000, False) == 28
    assert 4 <= scene_count(43.2, True) <= 9
