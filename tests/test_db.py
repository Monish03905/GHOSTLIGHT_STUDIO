from ghostlight.db import Database


def _make(db: Database, vid: str = "v1", **over) -> dict:
    record = {"id": vid, "format": "short", "status": "ready", "title": "Test Film"}
    record.update(over)
    return db.create_video(record)


def test_create_and_get_roundtrip(db: Database):
    made = _make(db, tags=["alpha", "beta"], script={"narration": "hello"})
    fetched = db.get_video(made["id"])
    assert fetched["title"] == "Test Film"
    assert fetched["tags"] == ["alpha", "beta"]
    assert fetched["script"]["narration"] == "hello"


def test_update_touches_updated_at(db: Database):
    made = _make(db)
    before = db.get_video(made["id"])["updated_at"]
    db.update_video(made["id"], status="published")
    after = db.get_video(made["id"])
    assert after["status"] == "published"
    assert after["updated_at"] >= before


def test_list_filters_and_archives(db: Database):
    _make(db, "a", status="ready")
    _make(db, "b", status="published")
    _make(db, "c", status="ready")
    db.archive_video("c")
    names = [v["id"] for v in db.list_videos(status="ready")]
    assert names == ["a"]
    archived = db.list_videos(include_archived=True, status="ready")
    assert {v["id"] for v in archived} == {"a", "c"}


def test_prefs_roundtrip(db: Database):
    db.set_pref("flag", {"on": True})
    assert db.get_pref("flag") == {"on": True}
    assert db.get_pref("missing", 42) == 42


def test_quota_accumulates(db: Database):
    db.add_quota("2026-11-03", units=1600, uploads=1)
    db.add_quota("2026-11-03", units=50, uploads=0)
    assert db.quota("2026-11-03") == {"units": 1650, "uploads": 1}
    assert db.quota("1999-01-01") == {"units": 0, "uploads": 0}


def test_events_since_id(db: Database):
    first = db.log_event("info", "note", "one")
    second = db.log_event("info", "note", "two")
    tail = db.list_events(since_id=first["id"])
    assert [e["message"] for e in tail] == ["two"]
    assert second["id"] > first["id"]


def test_upload_meta_column_migration(db: Database, tmp_path):
    made = _make(db, upload_meta={"youtube_id": "abc", "dry_run": False})
    fetched = db.get_video(made["id"])
    assert fetched["upload_meta"]["youtube_id"] == "abc"
    assert fetched["published_at"] == ""
