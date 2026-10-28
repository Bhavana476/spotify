import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import Lounge
from app.recovery import close_orphaned_lounges


def test_restart_closes_live_and_stale_lounges_but_keeps_fresh_scheduled(client, tokens):
    host_id = tokens["host"]["user"]["userId"]

    async def go():
        ids = {k: f"lg_{k}_{uuid.uuid4().hex[:4]}" for k in ("live", "stale", "fresh")}
        async with SessionLocal() as s:
            s.add_all([
                Lounge(id=ids["live"], invite_code=f"R-{uuid.uuid4().hex[:5]}", host_user_id=host_id, vibe_profile="x",
                       seed_track_id="t_2001", status="live"),
                Lounge(id=ids["stale"], invite_code=f"R-{uuid.uuid4().hex[:5]}", host_user_id=host_id, vibe_profile="x",
                       seed_track_id="t_2001", created_at=datetime.now(timezone.utc) - timedelta(days=2)),
                Lounge(id=ids["fresh"], invite_code=f"R-{uuid.uuid4().hex[:5]}", host_user_id=host_id, vibe_profile="x",
                       seed_track_id="t_2001"),
            ])
            await s.commit()
        await close_orphaned_lounges()
        async with SessionLocal() as s:
            return {k: await s.get(Lounge, v) for k, v in ids.items()}

    rows = asyncio.run(go())
    assert rows["live"].status == "ended" and rows["live"].summary["closedBy"] == "server_restart"
    assert rows["stale"].status == "ended"
    assert rows["fresh"].status == "scheduled"
