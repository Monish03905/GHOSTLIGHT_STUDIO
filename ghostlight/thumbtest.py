from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .db import Database

MIN_ARM_HOURS = 24
MAX_ARM_HOURS = 336  # two weeks
DEFAULT_ARM_HOURS = 72
MAX_ARMS = 3

CAVEAT = (
    "Channel-level analytics expose views and watch time, not thumbnail impressions, "
    "so each arm is compared by views per equal window. Feed noise, day of week and "
    "outside traffic can outweigh a thumbnail; read the result as a direction, not proof."
)


class ThumbTestError(Exception):
    pass


class NotEligible(ThumbTestError):
    pass


def arm_hours(cfg: Config, requested: float | None = None) -> int:
    raw = requested if requested is not None else cfg.get("thumbnails.arm_hours", DEFAULT_ARM_HOURS)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = DEFAULT_ARM_HOURS
    return int(max(MIN_ARM_HOURS, min(MAX_ARM_HOURS, value)))


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def eligible_arms(video: dict[str, Any], wanted: list[str] | None = None) -> list[dict[str, str]]:
    variants = video.get("thumb_variants") or []
    arms: list[dict[str, str]] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_id = str(variant.get("id") or "").strip()
        if wanted and variant_id not in wanted:
            continue
        path = Path(str(variant.get("path") or ""))
        if not variant_id or not path.is_file():
            continue
        arms.append({
            "variant": variant_id,
            "label": str(variant.get("label") or variant_id),
            "path": str(path),
        })
        if len(arms) >= MAX_ARMS:
            break
    return arms


def _score(metrics: dict[str, Any], hours: float) -> float:
    views = max(0, int(metrics.get("views") or 0))
    watch = max(0.0, float(metrics.get("watch_minutes") or 0))
    return round(views / max(0.1, hours) + watch * 0.01, 4)


def _sample(arm: dict[str, str], started: datetime, ended: datetime,
            metrics: dict[str, Any]) -> dict[str, Any]:
    hours = max(0.1, (ended - started).total_seconds() / 3600)
    return {
        "variant": arm["variant"],
        "label": arm["label"],
        "started_at": _iso(started),
        "ended_at": _iso(ended),
        "hours": round(hours, 2),
        "metrics": metrics,
        "score": _score(metrics, hours),
    }


def _remember(db: Database, video: dict[str, Any], variant: str, path: str) -> None:
    variants = [
        {**v, "recommended": str(v.get("id")) == variant}
        for v in (video.get("thumb_variants") or [])
        if isinstance(v, dict)
    ]
    db.update_video(str(video["id"]), thumb_path=str(path), thumb_variants=variants)


def start(
    cfg: Config,
    db: Database,
    video: dict[str, Any],
    *,
    variants: list[str] | None = None,
    hours: float | None = None,
    apply: Callable[[str], bool] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not video.get("youtube_id"):
        raise NotEligible("A thumbnail trial swaps the live video's thumbnail, so the film has to be published first.")
    arms = eligible_arms(video, variants)
    if len(arms) < 2:
        raise NotEligible("A trial needs at least two takes that exist on disk.")
    running = db.latest_thumbnail_test(str(video["id"]))
    if running and running.get("status") == "running":
        raise ThumbTestError("A trial is already running for this film. Stop it before starting another.")
    moment = now or datetime.now(timezone.utc)
    seconds = arm_hours(cfg, hours) * 3600
    test = db.create_thumbnail_test(
        str(video["id"]),
        channel_id=str(video.get("channel_id") or ""),
        arms=arms,
        arm_seconds=seconds,
        arm_started_at=_iso(moment),
        note="Arms run back to back. The first take is live now.",
    )
    if apply is not None and not apply(arms[0]["path"]):
        db.update_thumbnail_test(
            int(test["id"]),
            status="blocked",
            note=(
                "YouTube refused the thumbnail swap. Custom thumbnails need a verified "
                "channel; the takes stay on the shelf until that is sorted."
            ),
        )
        return db.get_thumbnail_test(int(test["id"])) or test
    _remember(db, video, arms[0]["variant"], arms[0]["path"])
    return db.get_thumbnail_test(int(test["id"])) or test


def advance(
    cfg: Config,
    db: Database,
    video: dict[str, Any],
    *,
    apply: Callable[[str], bool] | None = None,
    fetch_window: Callable[[str, str], dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Move a due trial to its next arm, or finish it and put the winner live."""
    test = db.latest_thumbnail_test(str(video["id"]))
    if not test or test.get("status") != "running":
        return test
    moment = now or datetime.now(timezone.utc)
    started = _parse(test.get("arm_started_at"))
    if started is None:
        return test
    due = started + timedelta(seconds=int(test.get("arm_seconds") or 0))
    if moment < due:
        return test

    arms: list[dict[str, str]] = list(test.get("arms") or [])
    samples: list[dict[str, Any]] = list(test.get("samples") or [])
    index = len(samples)
    if index >= len(arms):
        return test
    arm = arms[index]
    metrics: dict[str, Any] = {}
    if fetch_window is not None:
        try:
            metrics = fetch_window(started.date().isoformat(), (due - timedelta(seconds=1)).date().isoformat()) or {}
        except Exception:
            metrics = {}
    samples.append(_sample(arm, started, due, metrics))

    if index + 1 < len(arms):
        following = arms[index + 1]
        applied = True if apply is None else bool(apply(following["path"]))
        note = (
            f"{arm['label']} closed with {int(metrics.get('views') or 0)} views. "
            f"{following['label']} is live now."
            if applied else
            f"Could not put {following['label']} live; the trial is paused."
        )
        db.update_thumbnail_test(
            int(test["id"]),
            samples=samples,
            arm_started_at=_iso(due),
            status="running" if applied else "blocked",
            note=note,
        )
        if applied:
            _remember(db, video, following["variant"], following["path"])
        return db.get_thumbnail_test(int(test["id"])) or test

    return _conclude(db, video, test, arms, samples, apply)


def _conclude(
    db: Database,
    video: dict[str, Any],
    test: dict[str, Any],
    arms: list[dict[str, str]],
    samples: list[dict[str, Any]],
    apply: Callable[[str], bool] | None,
) -> dict[str, Any]:
    voted = [s for s in samples if int((s.get("metrics") or {}).get("views") or 0) > 0]
    if not voted:
        studio_pick = next(
            (a for a in arms if a["variant"] == _recommended_variant(video)),
            arms[0] if arms else None,
        )
        if studio_pick is not None and apply is not None:
            apply(studio_pick["path"])
        if studio_pick is not None:
            _remember(db, video, studio_pick["variant"], studio_pick["path"])
        db.update_thumbnail_test(
            int(test["id"]),
            samples=samples,
            status="inconclusive",
            winner="",
            note="No arm drew a view, so there is nothing to compare. The studio pick stays.",
        )
        return db.get_thumbnail_test(int(test["id"])) or test

    best = max(voted, key=lambda s: (float(s.get("score") or 0), float((s.get("metrics") or {}).get("watch_minutes") or 0)))
    winner = next((a for a in arms if a["variant"] == best["variant"]), None)
    applied = True if winner is None or apply is None else bool(apply(winner["path"]))
    if winner is not None:
        _remember(db, video, winner["variant"], winner["path"])
    views = int((best.get("metrics") or {}).get("views") or 0)
    note = (
        f"{best['label']} led the trial at {views} views over {best['hours']} h"
        + (" and is live now." if applied else ", but YouTube refused the final swap.")
    )
    db.update_thumbnail_test(
        int(test["id"]),
        samples=samples,
        status="concluded" if applied else "blocked",
        winner=str(best["variant"]),
        note=note,
    )
    return db.get_thumbnail_test(int(test["id"])) or test


def _recommended_variant(video: dict[str, Any]) -> str:
    for variant in video.get("thumb_variants") or []:
        if isinstance(variant, dict) and variant.get("recommended"):
            return str(variant.get("id") or "")
    return ""


def stop(
    cfg: Config,
    db: Database,
    video: dict[str, Any],
    *,
    keep: str | None = None,
    apply: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    test = db.latest_thumbnail_test(str(video["id"]))
    if not test or test.get("status") != "running":
        raise ThumbTestError("No trial is running for this film.")
    arms: list[dict[str, str]] = list(test.get("arms") or [])
    wanted = keep or _recommended_variant(video)
    chosen = next((a for a in arms if a["variant"] == wanted), None)
    if chosen is None:
        chosen = next((a for a in arms if a.get("path") == video.get("thumb_path")), arms[0] if arms else None)
    if chosen is None:
        raise ThumbTestError("This trial has no takes to keep.")
    if apply is not None:
        apply(chosen["path"])
    _remember(db, video, chosen["variant"], chosen["path"])
    db.update_thumbnail_test(
        int(test["id"]),
        status="stopped",
        winner=chosen["variant"],
        note=f"Stopped by hand. {chosen['label']} stays live.",
    )
    return db.get_thumbnail_test(int(test["id"])) or test


def advance_due(
    cfg: Config,
    db: Database,
    hub: Any,
    *,
    now: datetime | None = None,
    on_event: Callable[..., None] | None = None,
) -> list[dict[str, Any]]:
    """Advance every due trial. Safe to call on each scheduler tick."""
    touched: list[dict[str, Any]] = []
    for test in db.list_thumbnail_tests(status="running", limit=50):
        video = db.get_video(str(test.get("video_id") or ""))
        if not video or not video.get("youtube_id"):
            db.update_thumbnail_test(
                int(test["id"]),
                status="stalled",
                note="The film or its YouTube id disappeared; the trial cannot continue.",
            )
            continue
        account = hub.account(video.get("channel_id")) if hub is not None else None
        if account is None or not getattr(account, "connected", False):
            continue
        video_id = str(video["youtube_id"])

        def fetch_window(start: str, end: str, _account: Any = account, _video: str = video_id) -> dict[str, Any]:
            return _account.fetch_window_metrics(_video, start, end)

        updated = advance(
            cfg, db, video,
            apply=account.set_thumbnail,
            fetch_window=fetch_window,
            now=now,
        )
        if updated and updated.get("status") != "running":
            touched.append(updated)
            if on_event:
                on_event(
                    "success" if updated.get("status") == "concluded" else "info",
                    "thumbnail",
                    f"Thumbnail trial for “{video.get('title', 'a film')}”: {updated.get('note', '')}",
                    video_id=str(video["id"]),
                )
    return touched


def status(db: Database, video_id: str) -> dict[str, Any]:
    test = db.latest_thumbnail_test(video_id)
    if not test:
        return {"status": "none", "caveat": CAVEAT}
    test = dict(test)
    next_at = ""
    if test.get("status") == "running":
        started = _parse(test.get("arm_started_at"))
        if started is not None:
            next_at = (started + timedelta(seconds=int(test.get("arm_seconds") or 0))).isoformat(timespec="seconds")
    test["next_switch_at"] = next_at
    test["caveat"] = CAVEAT
    return test
