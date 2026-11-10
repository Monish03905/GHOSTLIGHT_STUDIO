from __future__ import annotations

import asyncio
import threading
from typing import Any

from .db import Database


class EventBus:
    """Writes events to SQLite and fans them out to live SSE listeners."""

    def __init__(self, db: Database):
        self.db = db
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=400)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def emit(
        self,
        kind: str,
        message: str,
        level: str = "info",
        video_id: str = "",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = self.db.log_event(level=level, kind=kind, message=message, video_id=video_id, data=data)
        self._dispatch(event)
        return event

    def step(self, video_id: str, stage: str, message: str, progress: int, **extra: Any) -> None:
        self.emit(
            "stage",
            message,
            video_id=video_id,
            data={"stage": stage, "progress": progress, **extra},
        )

    def _dispatch(self, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        try:
            loop.call_soon_threadsafe(self._put, event)
        except RuntimeError:
            pass

    def _put(self, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
