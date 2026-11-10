from ghostlight.novelty import (
    cliche_hits,
    continuity_hits,
    evaluate,
    jaccard,
    make_fingerprint,
    similarity,
)


def _finger(text: str, subject: str = "thing", lens: str = "scale") -> dict:
    brief = {"subject": subject, "lens": lens, "seed": 7, "niche": "cosmic", "format": "short"}
    return make_fingerprint({"title": "T", "hook": text}, brief)


def test_fingerprint_has_stable_parts():
    fp = _finger("The harbour lights keep time with the tide.")
    assert fp["shingles"]
    assert fp["premise_parts"]["subject"] == "thing"


def test_similarity_identical_is_high():
    a = _finger("A lighthouse keeper counts the ships that never arrive.")
    b = _finger("A lighthouse keeper counts the ships that never arrive.")
    assert similarity(a, b) > 0.9


def test_similarity_unrelated_is_low():
    a = _finger("A lighthouse keeper counts the ships that never arrive.", subject="keepers")
    b = _finger("Mushroom networks trade sugar beneath the forest floor.", subject="mycelium")
    assert similarity(a, b) < 0.3


def test_evaluate_rejects_near_duplicate():
    first = _finger("A cartographer maps streets that only exist at night.")
    second = _finger("A cartographer maps streets that only exist at night.")
    result = evaluate(second, [{"id": "1", "title": "x", "fingerprint": first}], 0.30)
    assert result["accepted"] is False
    assert result["score"] > 0.3


def test_evaluate_accepts_fresh_idea():
    first = _finger("A cartographer maps streets that only exist at night.", subject="streets")
    second = _finger("Deep sea siphonophores glow to organise their colony.", subject="siphonophores")
    result = evaluate(second, [{"id": "1", "title": "x", "fingerprint": first}], 0.30)
    assert result["accepted"] is True


def test_continuity_hits_flags_sequel_language():
    hits = continuity_hits("part two of the signal series, as promised last time")
    assert hits


def test_continuity_hits_clean_text():
    assert continuity_hits("One strange idea, standing entirely alone.") == []


def test_cliche_hits():
    assert cliche_hits("buckle up, this will blow your mind")
    assert not cliche_hits("The harbour keeps its own arithmetic.")


def test_jaccard_bounds():
    assert jaccard(set(), set()) == 0.0
    assert jaccard({"a"}, {"a"}) == 1.0
