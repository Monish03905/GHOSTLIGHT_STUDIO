from __future__ import annotations

from ghostlight.db import Database
from ghostlight.events import EventBus


def test_notifications_are_durable_and_ordered(db):
    first = db.add_notification("First", "one", kind="quality")
    second = db.add_notification("Second", "two", kind="language", level="warning")
    third = db.add_notification("Third", "three", kind="library", level="success", video_id="film-a")

    assert db.unread_notifications() == 3
    items = db.list_notifications(limit=10)
    assert [item["id"] for item in items] == [third["id"], second["id"], first["id"]]
    assert items[0]["read"] == 0
    assert items[0]["level"] == "success"
    assert items[0]["video_id"] == "film-a"

    assert db.mark_notification(first["id"]) == 1
    assert db.unread_notifications() == 2
    assert len(db.list_notifications(unread_only=True)) == 2

    assert db.mark_notification(0) == 2
    assert db.unread_notifications() == 0
    assert db.mark_notification(9999) == 0


def test_notifications_are_capped_and_trimmed(db):
    note = db.add_notification("x" * 400, "y" * 2000)
    stored = db.list_notifications(limit=1)[0]
    assert stored["id"] == note["id"]
    assert len(stored["title"]) == 200
    assert len(stored["body"]) == 1000


def test_event_bus_notify_writes_a_notification(db):
    bus = EventBus(db)
    bus.notify(
        "A film is ready",
        "The desk finished “The Quiet City”.",
        kind="quality",
        level="success",
        video_id="film-a",
        link="/feed.xml",
    )
    items = db.list_notifications(limit=5)
    assert len(items) == 1
    assert items[0]["title"] == "A film is ready"
    assert items[0]["kind"] == "quality"
    assert items[0]["link"] == "/feed.xml"
    assert db.unread_notifications() == 1


def test_notifications_survive_a_new_database_handle(db):
    db.add_notification("Persisted", "still here")
    reopened = Database(db.path)
    assert reopened.unread_notifications() == 1
    assert reopened.list_notifications(limit=1)[0]["title"] == "Persisted"
