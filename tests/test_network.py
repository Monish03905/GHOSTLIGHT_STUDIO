from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from ghostlight import publish
from ghostlight.app import create_app
from ghostlight.channels import ensure_lineup
from ghostlight.db import Database
from ghostlight.events import EventBus
from ghostlight.orchestrator import Studio
from ghostlight.scheduler import Scheduler
from ghostlight.showrunner import Showrunner


class _FakeAccount:
    def __init__(self, connected: bool):
        self.connected = connected


class _FakeHub:
    def __init__(self, linked: set[str]):
        self.linked = linked

    def account(self, channel_id: str | None = None) -> _FakeAccount:
        return _FakeAccount(str(channel_id or "") in self.linked)


def _channel(db: Database, channel_id: str, name: str, times: list[str]) -> dict:
    return db.create_channel({
        "id": channel_id,
        "name": name,
        "tagline": "a test voice",
        "niches": ["cosmic"],
        "styles": ["aurora"],
        "formats": ["short"],
        "times": times,
        "max_per_day": 1,
        "enabled": 1,
        "privacy": "private",
        "persona": {},
        "playbook": {},
    })


def test_lineup_creates_distinct_voices(cfg, db):
    bus = EventBus(db)
    showrunner = Showrunner(cfg, db, bus)
    lineup = showrunner.ensure_lineup()

    assert len(lineup) == 3
    assert len({c["id"] for c in lineup}) == 3
    assert all(c["times"] for c in lineup)
    assert all(c["privacy"] == "private" for c in lineup)

    niche_sets = [set(c["niches"]) for c in lineup]
    assert sum(len(s) for s in niche_sets) == len(set().union(*niche_sets))

    journal = db.list_journal(limit=5)
    assert journal and journal[0]["kind"] == "birth"
    assert len(db.list_journal(channel_id=lineup[0]["id"])) == 1


def test_scheduler_only_produces_linked_channels(cfg, db):
    bus = EventBus(db)
    hub = _FakeHub({"linked"})
    showrunner = Showrunner(cfg, db, bus, hub)
    studio = Studio(cfg, db, bus, hub, showrunner=showrunner)
    sched = Scheduler(cfg, db, bus, studio, showrunner=showrunner)

    now = datetime.now(cfg.timezone())
    slot = (now - timedelta(minutes=5)).strftime("%H:%M")
    _channel(db, "silent", "Silent", [slot])
    _channel(db, "linked", "Linked", [slot])

    cfg.set("schedule.enabled", True)
    cfg.set("schedule.paused", False)
    sched._tick()

    videos = db.list_videos()
    assert len(videos) == 1
    assert videos[0]["channel_id"] == "linked"
    assert videos[0]["status"] == "queued"


def test_backlog_skips_unlinked_channels(cfg, db):
    bus = EventBus(db)
    hub = _FakeHub(set())
    showrunner = Showrunner(cfg, db, bus, hub)
    studio = Studio(cfg, db, bus, hub, showrunner=showrunner)
    sched = Scheduler(cfg, db, bus, studio, showrunner=showrunner)

    soon = (datetime.now(cfg.timezone()) + timedelta(hours=2)).strftime("%H:%M")
    _channel(db, "silent", "Silent", [soon])
    cfg.set("schedule.enabled", True)
    cfg.set("schedule.paused", False)

    sched._tick()
    assert db.list_videos() == []


def test_channel_api_crud_and_privacy(cfg):
    app = create_app(cfg)
    client = TestClient(app)
    ensure_lineup(cfg, Database(cfg.db_path))

    listed = client.get("/api/channels").json()
    assert listed["count"] == 3
    assert listed["templates"]
    assert any(n["id"] == "cosmic" for n in listed["options"]["niches"])

    created = client.post("/api/channels", json={
        "name": "Night Shift",
        "tagline": "the hours nobody clocks",
        "niches": ["quiet_tech"],
        "styles": ["neon"],
        "formats": ["short", "long"],
        "times": ["22:15"],
        "privacy": "unlisted",
    })
    assert created.status_code == 200
    channel = created.json()
    assert channel["id"] == "night-shift"
    assert channel["privacy"] == "unlisted"

    patched = client.patch("/api/channels/night-shift", json={"privacy": "public"})
    assert patched.status_code == 200
    assert patched.json()["privacy"] == "public"

    assert client.patch("/api/channels/night-shift", json={"privacy": "secret"}).status_code == 400
    assert client.patch("/api/channels/night-shift", json={"times": ["25:99"]}).status_code == 400
    assert client.patch("/api/channels/night-shift", json={"niches": ["made_up"]}).status_code == 400

    assert client.delete("/api/channels/night-shift").status_code == 200
    assert client.get("/api/channels").json()["count"] == 3


def test_status_and_growth_expose_the_network(cfg):
    app = create_app(cfg)
    client = TestClient(app)
    ensure_lineup(cfg, Database(cfg.db_path))

    status = client.get("/api/status").json()
    assert len(status["channels"]) == 3
    assert status["autopilot"]["enabled"] is True
    assert "totals" in status["growth"]

    growth = client.get("/api/growth").json()
    assert len(growth["channels"]) == 3
    assert growth["summary"]["totals"]["revenue"] == 0


def test_oauth_callback_rejects_unknown_state(cfg):
    client = TestClient(create_app(cfg))
    resp = client.get("/api/youtube/oauth/callback", params={"code": "x", "state": "forged"},
                      follow_redirects=False)
    assert resp.status_code == 302
    assert "reason=state" in resp.headers["location"]

    denied = client.get("/api/youtube/oauth/callback", params={"error": "access_denied"},
                        follow_redirects=False)
    assert denied.status_code == 302
    assert "reason=access_denied" in denied.headers["location"]


def test_oauth_start_without_client_secret_is_a_clean_400(cfg):
    client = TestClient(create_app(cfg))
    ensure_lineup(cfg, Database(cfg.db_path))
    resp = client.post("/api/youtube/oauth/start", json={"channel_id": "ghostlight"})
    assert resp.status_code == 400
    assert "OAuth client" in resp.json()["detail"]


def test_client_secret_upload_is_validated_and_stored(cfg):
    client = TestClient(create_app(cfg))
    ensure_lineup(cfg, Database(cfg.db_path))

    assert client.post("/api/youtube/client-secret", content=b"not json").status_code == 400
    assert client.post("/api/youtube/client-secret", content=b'{"nope": 1}').status_code == 400

    payload = b'{"installed": {"client_id": "abc.apps.googleusercontent.com", "client_secret": "shh"}}'
    resp = client.post("/api/youtube/client-secret?channel_id=quiet-machine", content=payload)
    assert resp.status_code == 200
    target = cfg.base_dir / "secrets" / "channels" / "quiet-machine" / "client_secret.json"
    assert target.is_file()
    assert "abc.apps.googleusercontent.com" in target.read_text(encoding="utf-8")


def test_deleted_channel_leaves_no_journal_voice(cfg, db):
    _channel(db, "old", "Old Voice", ["08:00"])
    db.add_journal("old", "Old Voice joined the network.", kind="birth")
    db.add_journal("ghost", "A voice that never existed.", kind="birth")

    spoken = db.list_journal(limit=10)
    assert [row["headline"] for row in spoken] == ["Old Voice joined the network."]

    db.delete_channel("old")
    assert db.list_journal(limit=10) == []
    assert db.list_journal(channel_id="old") == []


def test_metadata_and_srt_for_a_long_film(cfg):
    video = {
        "format": "long",
        "title": "The Sound of a Black Hole",
        "hook": "There is a note in the middle of the galaxy.",
        "niche": "cosmic",
        "brief": {"subject": "black holes", "question": "What would you listen for?"},
        "script": {
            "description": "An essay about listening to the dark.",
            "tags": ["astronomy", "silence"],
        },
    }
    channel = {"name": "Ghostlight", "cta": "Subscribe for one strange idea at a time."}
    narration = {"segments": [
        {"start": 0, "heading": "Cold open", "text": "There is a note."},
        {"start": 24, "heading": "The hum", "text": "It arrives as a pressure."},
        {"start": 58, "heading": "The silence", "text": "Then nothing."},
        {"start": 91, "heading": "What it means", "text": "We listen anyway."},
        {"start": 128, "heading": "Coda", "text": "Leave a light on."},
    ]}
    cfg.set("youtube.auto_comment", True)
    meta = publish.build_metadata(cfg, video, channel, narration)

    assert meta["short"] is False
    assert meta["chapters"][0] == "0:00 Cold open"
    assert len(meta["chapters"]) >= 3
    assert "computer-generated" in meta["description"]
    assert meta["hashtags"][0] == "#cosmic"
    assert meta["comment"].startswith("One question before you go:")

    words = [
        {"text": "There", "start": 0.0, "end": 0.3},
        {"text": "is", "start": 0.3, "end": 0.45},
        {"text": "a", "start": 0.45, "end": 0.55},
        {"text": "note", "start": 0.55, "end": 0.9},
        {"text": "in", "start": 0.9, "end": 1.0},
        {"text": "the", "start": 1.0, "end": 1.1},
        {"text": "dark.", "start": 1.1, "end": 1.6},
    ]
    srt = publish.build_srt({"words": words})
    assert srt.startswith("1\n00:00:00,000 --> ")
    assert "There is a note in the" in srt
    assert "dark." in srt
