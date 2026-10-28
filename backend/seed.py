"""Seeds tracks (acoustic profiles + RAG timelines), demo users and a synthetic interaction dataset.

Usage:  python seed.py [--reset]
Demo account password is read from SEED_PASSWORD (a local-only demo credential, not a deployment secret).
"""
import asyncio
import os
import sys

from sqlalchemy import delete, select

from app import synthetic
from app.db import Base, SessionLocal, engine, init_db
from app.models import Interaction, Track, TrackTimelineEvent, User
from app.security import hash_password
from app.seed_data import TRACKS, USERS


async def main(reset: bool):
    if reset:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    await init_db()
    password = os.getenv("SEED_PASSWORD", "djstudio-demo")
    async with SessionLocal() as s:
        for (tid, title, artist, dur, bpm, key, energy, valence, _cluster, timeline) in TRACKS:
            track = await s.get(Track, tid) or Track(id=tid)
            track.title, track.artist, track.duration_seconds = title, artist, dur
            track.bpm, track.camelot_key, track.energy, track.valence = bpm, key, energy, valence
            s.add(track)
            await s.execute(delete(TrackTimelineEvent).where(TrackTimelineEvent.track_id == tid))
            for i, (ts, etype, text) in enumerate(timeline, start=1):
                s.add(TrackTimelineEvent(id=f"evt_{tid[2:]}_{i}", track_id=tid, ts_seconds=ts, event_type=etype,
                                         payload={"text": text}))
        for email, name, role in USERS:
            existing = (await s.execute(select(User).where(User.email == email))).scalar_one_or_none()
            if existing is None:
                s.add(User(email=email, display_name=name, role=role, password_hash=hash_password(password)))
        await s.flush()

        # Synthetic listeners get real user rows so interaction FKs hold.
        rows = synthetic.generate()
        sim_ids = sorted({r["user_id"] for r in rows})
        existing_sim = (await s.execute(select(User.id).where(User.email.like("sim%@sim.local")))).scalars().all()
        if not existing_sim:
            id_map = {}
            for n, sim in enumerate(sim_ids):
                u = User(email=f"sim{n}@sim.local", display_name=f"Sim Listener {n}", role="listener",
                         password_hash="!disabled")
                s.add(u)
                await s.flush()
                id_map[sim] = u.id
            # Demo users get a small history too, so their dashboard rail is personalised out of the box.
            demo = (await s.execute(select(User).where(User.email.like("%@djstudio.dev")))).scalars().all()
            for i, u in enumerate(demo):
                id_map[sim_ids[i]] = u.id  # reuse the first few synthetic taste profiles
            for r in rows:
                s.add(Interaction(user_id=id_map[r["user_id"]], track_id=r["track_id"], liked=r["liked"],
                                  completed=r["completed"], played_seconds=r["played_seconds"], co_listened_with=[]))
        await s.commit()
        n_inter = len((await s.execute(select(Interaction.id))).all())
    print(f"Seeded {len(TRACKS)} tracks, {len(USERS)} demo users, {n_inter} interactions. "
          f"Demo password: {'(from SEED_PASSWORD)' if os.getenv('SEED_PASSWORD') else password}")


if __name__ == "__main__":
    asyncio.run(main("--reset" in sys.argv))
