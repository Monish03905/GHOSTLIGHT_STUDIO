from datetime import datetime, timedelta

from ghostlight.commander import Commander
from ghostlight.events import EventBus
from ghostlight.orchestrator import Studio
from ghostlight.scheduler import Scheduler
from ghostlight.youtube import QuotaError, YouTubeClient


def _harness(cfg, db):
    bus = EventBus(db)
    yt = YouTubeClient(cfg, db)
    studio = Studio(cfg, db, bus, yt)
    sched = Scheduler(cfg, db, bus, studio)
    cmd = Commander(cfg, db, bus, studio, sched, yt)
    return cmd, studio, sched


def test_rule_parse_actions(cfg, db):
    cmd, _, _ = _harness(cfg, db)
    cases = {
        "make a short": ("generate", {"format": "short", "count": 1}),
        "make 2 long films": ("generate", {"format": "long", "count": 2}),
        "pause the schedule": ("pause", {}),
        "resume": ("resume", {}),
        "status": ("status", {}),
        "upload the latest film": ("upload", {"count": 1}),
    }
    for note, (action, args) in cases.items():
        out = cmd.handle(note)
        assert out["action"] == action, note
        for key, value in args.items():
            assert out["args"].get(key) == value, (note, key)


def test_generate_creates_queued_video(cfg, db):
    cmd, studio, _ = _harness(cfg, db)
    out = cmd.handle("make a short about lighthouse keepers")
    assert out["action"] == "generate"
    videos = db.list_videos()
    assert len(videos) == 1
    assert videos[0]["status"] == "queued"
    assert videos[0]["format"] == "short"


def test_setting_roundtrip(cfg, db):
    cmd, _, _ = _harness(cfg, db)
    out = cmd.handle("set privacy to public")
    assert out["action"] == "set_setting"
    assert cfg.get("youtube.privacy") == "public"
    out = cmd.handle("set times 10:00, 20:30")
    assert cfg.get("schedule.times") == ["10:00", "20:30"]


def test_unknown_niche_rejected(cfg, db):
    cmd, _, _ = _harness(cfg, db)
    out = cmd.handle("set niches to made_up_place")
    assert "don't know the niche" in out["reply"]


def test_directives_are_logged(cfg, db):
    cmd, _, _ = _harness(cfg, db)
    cmd.handle("status")
    with db._connect() as conn:
        rows = conn.execute("SELECT text, action, reply FROM directives").fetchall()
    assert len(rows) == 1
    assert rows[0]["text"] == "status"
    assert "status" in rows[0]["action"]
    assert rows[0]["reply"]


def test_scheduler_rhythm_fires_once_per_slot(cfg, db):
    cmd, studio, sched = _harness(cfg, db)
    now = datetime.now(cfg.timezone())
    slot = (now - timedelta(minutes=5)).strftime("%H:%M")
    cfg.set("schedule.enabled", True)
    cfg.set("schedule.paused", False)
    cfg.set("schedule.times", [slot])
    sched._tick()
    sched._tick()
    assert len(db.list_videos()) == 1


def test_scheduler_respects_daily_cap(cfg, db):
    cmd, studio, sched = _harness(cfg, db)
    now = datetime.now(cfg.timezone())
    slot = (now - timedelta(minutes=5)).strftime("%H:%M")
    cfg.set("schedule.enabled", True)
    cfg.set("schedule.paused", False)
    cfg.set("schedule.times", [slot])
    cfg.set("schedule.max_per_day", 1)
    sched._tick()
    key = f"{now.date().isoformat()}#0"
    db.set_pref("schedule.last_slot", "")  # allow the slot again
    sched._tick()
    assert len(db.list_videos()) == 1  # capped


def test_quota_precheck_blocks_upload(cfg, db, tmp_path):
    yt = YouTubeClient(cfg, db)
    day = yt.quota_day()
    db.add_quota(day, units=10000, uploads=0)
    video = tmp_path / "film.mp4"
    video.write_bytes(b"0" * 16)
    try:
        yt.upload(video, title="x", description="d")
        raised = False
    except QuotaError:
        raised = True
    assert raised


def test_dry_run_upload_skips_quota(cfg, db, tmp_path):
    cfg.set("youtube.dry_run", True)
    yt = YouTubeClient(cfg, db)
    video = tmp_path / "film.mp4"
    video.write_bytes(b"0" * 16)
    meta = yt.upload(video, title="Dry", description="d")
    assert meta["dry_run"] is True
    assert db.quota(yt.quota_day())["uploads"] == 0
