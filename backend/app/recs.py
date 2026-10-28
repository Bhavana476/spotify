"""Serves the hybrid recommender. The model is retrained in the background (batch job) when new interactions
have landed, so the rail updates without a redeploy."""
import asyncio
import logging
import time

from sqlalchemy import func, select

from . import catalog
from .db import SessionLocal
from .engine import recommender
from .models import Interaction

log = logging.getLogger("djstudio.recs")
RETRAIN_INTERVAL = 15.0

_model: recommender.Model | None = None
_trained_on = -1
_trained_at = 0.0


async def retrain(force: bool = False) -> dict:
    global _model, _trained_on, _trained_at
    async with SessionLocal() as s:
        count = (await s.execute(select(func.count(Interaction.id)))).scalar_one()
        if not force and count == _trained_on and _model is not None:
            return status()
        rows = (await s.execute(select(Interaction))).scalars().all()
    started = time.perf_counter()
    _model = recommender.train(catalog.all_tracks(), [
        {"user_id": r.user_id, "track_id": r.track_id, "completed": r.completed, "liked": r.liked,
         "played_seconds": r.played_seconds} for r in rows])
    _trained_on, _trained_at = count, time.time()
    log.info("recommender retrained", extra={"interactions": count,
                                             "ms": round((time.perf_counter() - started) * 1000, 1)})
    return status()


def status() -> dict:
    return {"interactions": _trained_on, "trainedAt": _trained_at}


def model() -> recommender.Model | None:
    return _model


async def retrain_loop():
    while True:
        await asyncio.sleep(RETRAIN_INTERVAL)
        try:
            await retrain()
        except Exception:
            log.exception("retrain failed")
