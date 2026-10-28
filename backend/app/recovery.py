"""Startup housekeeping. Live queue state lives in memory, so after a restart any lounge still marked 'live'
has lost its room and can never resume: close it with a proper summary instead of leaving a ghost booth."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .analytics import session_analytics
from .db import SessionLocal
from .models import Lounge

log = logging.getLogger("djstudio.recovery")
STALE_SCHEDULED = timedelta(hours=12)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes


async def close_orphaned_lounges() -> int:
    now = datetime.now(timezone.utc)
    closed = 0
    async with SessionLocal() as s:
        rows = (await s.execute(select(Lounge).where(Lounge.status != "ended"))).scalars().all()
        for lounge in rows:
            stale = lounge.status == "live" or now - _aware(lounge.created_at) > STALE_SCHEDULED
            if not stale:
                continue
            lounge.status, lounge.ended_at = "ended", now
            lounge.summary = {**await session_analytics(s, lounge.id), "closedBy": "server_restart"}
            closed += 1
        await s.commit()
    if closed:
        log.info("closed orphaned lounges", extra={"count": closed})
    return closed
