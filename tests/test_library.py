from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

from ghostlight import library


def _video(cfg, video_id: str, *, bytes_: int = 100, **fields) -> dict:
    folder = cfg.video_dir(video_id)
    (folder / "video.mp4").write_bytes(b"0" * bytes_)
    return {"id": video_id, "title": fields.pop("title", video_id.title()),
            "format": "short", "bytes": bytes_, **fields}


def _age(db, video_id: str, stamp: str = "2020-01-01T00:00:00+00:00") -> None:
    with db._connect() as conn:
        conn.execute("UPDATE videos SET updated_at = ? WHERE id = ?", (stamp, video_id))


def test_storage_report_counts_tracks_and_orphans(cfg, db):
    _video(cfg, "film-a", bytes_=100, title="Film A")
    _video(cfg, "film-b", bytes_=50, title="Film B")
    db.create_video({"id": "film-a", "title": "Film A", "format": "short", "bytes": 100})
    db.create_video({"id": "film-b", "kind": "clip", "title": "Film B", "format": "short", "bytes": 50})
    orphan = cfg.videos_dir / "orphan-render"
    orphan.mkdir(parents=True, exist_ok=True)
    (orphan / "leftover.bin").write_bytes(b"x" * 10)

    report = library.storage_report(cfg, db)
    assert report["films"] == 1
    assert report["clips"] == 1
    assert report["records"] == 2
    assert report["tracked_bytes"] == 150
    assert report["on_disk_bytes"] == 160
    assert report["orphan_dirs"] == ["orphan-render"]
    assert report["orphan_bytes"] == 10
    assert report["by_kind"] == {"film": 1, "clip": 1}
    assert report["free_bytes"] >= 0
    assert "never deleted automatically" in report["note"]


def test_export_catalogue_without_media(cfg, db):
    _video(cfg, "film-a", bytes_=12, title="Film A")
    db.create_video({"id": "film-a", "title": "Film A", "format": "short", "bytes": 12})
    db.upsert_localization("film-a", "hi", {"status": "ready", "title": "फ़िल्म", "tags": ["समुद्र"]})

    result = library.export_catalogue(cfg, db)
    target = Path(result["path"])
    assert target.is_file()
    assert result["films"] == 1
    assert result["media_files"] == 0

    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        assert {"manifest.json", "films.json", "films.csv", "localizations.json"} <= names
        assert not any(name.startswith("media/") for name in names)
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["films"] == 1
        rows = list(csv.DictReader(io.StringIO(archive.read("films.csv").decode("utf-8"))))
        assert rows[0]["id"] == "film-a"
        locs = json.loads(archive.read("localizations.json"))
        assert locs["film-a"][0]["language"] == "hi"


def test_export_catalogue_with_media_and_filter(cfg, db):
    _video(cfg, "film-a", bytes_=12, title="Film A")
    _video(cfg, "film-b", bytes_=12, title="Film B")
    db.create_video({"id": "film-a", "title": "Film A", "format": "short", "bytes": 12,
                     "video_path": str(cfg.video_dir("film-a") / "video.mp4")})
    db.create_video({"id": "film-b", "title": "Film B", "format": "short", "bytes": 12,
                     "video_path": str(cfg.video_dir("film-b") / "video.mp4")})

    result = library.export_catalogue(cfg, db, include_media=True, video_ids=["film-a"])
    assert result["films"] == 1
    assert result["media_files"] == 1
    with zipfile.ZipFile(result["path"]) as archive:
        assert "media/film-a/video.mp4" in archive.namelist()
        assert not any("film-b" in name for name in archive.namelist())


def test_backup_database_copies_the_files(cfg, db):
    db.add_notification("A note", "Saved before the backup")
    result = library.backup_database(cfg, db, keep=3)
    target = Path(result["path"])
    assert target.is_file()
    assert result["bytes"] > 0
    assert target.parent == cfg.data_dir / "backups"
    assert result["kept"] >= 1


def test_prune_plan_only_lists_old_archived_or_failed(cfg, db):
    _video(cfg, "old-archive", title="Old Archive")
    _video(cfg, "old-fail", title="Old Fail")
    _video(cfg, "old-live", title="Old Live")
    _video(cfg, "fresh-archive", title="Fresh Archive")
    db.create_video({"id": "old-archive", "archived": 1, "title": "Old Archive"})
    db.create_video({"id": "old-fail", "status": "failed", "title": "Old Fail"})
    db.create_video({"id": "old-live", "status": "ready", "title": "Old Live"})
    db.create_video({"id": "fresh-archive", "archived": 1, "title": "Fresh Archive"})
    for video_id in ("old-archive", "old-fail", "old-live"):
        _age(db, video_id)

    plan = library.prune_plan(cfg, db, days=60)
    ids = {candidate["id"] for candidate in plan["candidates"]}
    assert ids == {"old-archive", "old-fail"}
    assert plan["count"] == 2
    assert plan["total_bytes"] > 0
    assert "Nothing is removed until you confirm" in plan["note"]


def test_apply_prune_requires_confirmation(cfg, db):
    with pytest.raises(library.LibraryError):
        library.apply_prune(cfg, db, ["anything"])


def test_apply_prune_removes_only_eligible_films(cfg, db):
    _video(cfg, "old-archive", title="Old Archive")
    _video(cfg, "old-live", title="Old Live")
    db.create_video({"id": "old-archive", "archived": 1, "title": "Old Archive"})
    db.create_video({"id": "old-live", "status": "ready", "title": "Old Live"})
    _age(db, "old-archive")
    _age(db, "old-live")
    folder = cfg.video_dir("old-archive")

    result = library.apply_prune(
        cfg, db, ["old-archive", "old-live", "../escape"], confirm=True,
    )
    assert result["removed_records"] == 1
    assert result["removed_files"] == 1
    assert result["removed_bytes"] > 0
    assert set(result["skipped"]) == {"old-live", "../escape"}
    assert not folder.exists()
    assert db.get_video("old-archive") is None
    assert db.get_video("old-live") is not None


def test_delete_video_cascades_localizations_and_metrics(cfg, db):
    db.create_video({"id": "film-a", "title": "Film A"})
    db.upsert_localization("film-a", "hi", {"status": "ready", "title": "फ़िल्म"})
    db.upsert_metrics("film-a", "", {"views": 5})
    db.delete_video("film-a")
    assert db.get_video("film-a") is None
    assert db.list_localizations("film-a") == []
    assert db.get_metrics("film-a") in (None, {})
