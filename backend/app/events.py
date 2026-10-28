"""Batched append-only writer (PRD 9.4): high-frequency events are buffered and flushed every
EVENT_FLUSH_SECONDS or EVENT_FLUSH_MAX rows, whichever comes first — never one DB write per vote."""
import asyncio
import logging
import time
import uuid

from . import config
from .db import SessionLocal
from .models import ChatMessage, Interaction, QueueEvent

log = logging.getLogger("djstudio.events")


class EventSink:
    def __init__(self):
        self._rows: list = []
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None
        await self.flush()

    def _push(self, row):
        self._rows.append(row)
        if len(self._rows) >= config.EVENT_FLUSH_MAX:
            self._wakeup.set()

    def event(self, lounge_id: str, type_: str, payload: dict, user_id: int | None = None,
              ts: float | None = None) -> str:
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        self._push(QueueEvent(id=event_id, lounge_id=lounge_id, user_id=user_id, type=type_, payload=payload,
                              ts=ts or time.time()))
        log.info("lounge_event", extra={"loungeId": lounge_id, "type": type_, "userId": user_id})
        return event_id

    def chat(self, message_id: str, lounge_id: str, user_id: int | None, msg_type: str, body: str,
             sentiment: float | None, ts_seconds: float):
        self._push(ChatMessage(id=message_id, lounge_id=lounge_id, user_id=user_id, msg_type=msg_type, body=body,
                               sentiment_score=sentiment, ts_seconds=ts_seconds))

    def interaction(self, **fields):
        self._push(Interaction(**fields))

    def records(self, *rows):
        """Low-frequency rows (e.g. a resolved Soundclash) that ride along with the next batch."""
        for row in rows:
            self._push(row)

    async def flush(self):
        if not self._rows:
            return
        rows, self._rows = self._rows, []
        try:
            async with SessionLocal() as session:
                session.add_all(rows)
                await session.commit()
        except Exception:
            log.exception("event flush failed; %d rows re-queued", len(rows))
            self._rows[:0] = rows

    async def _run(self):
        while True:
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=config.EVENT_FLUSH_SECONDS)
            except asyncio.TimeoutError:
                pass
            self._wakeup.clear()
            await self.flush()


sink = EventSink()
