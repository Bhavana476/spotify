import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import catalog, config, recs
from .db import SessionLocal, init_db
from .events import sink
from .gateway import ws
from .gateway.hub import hub
from .recovery import close_orphaned_lounges
from .routers import admin, auth, dashboard, lounges, tracks

_STD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Structured logs; lounge-scoped records carry loungeId as the correlation id."""

    def format(self, record):
        data = {"ts": round(record.created, 3), "level": record.levelname, "logger": record.name,
                "msg": record.getMessage()}
        data.update({k: v for k, v in record.__dict__.items() if k not in _STD_ATTRS})
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def _setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("djstudio")
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    root.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    await init_db()
    await close_orphaned_lounges()
    async with SessionLocal() as s:
        await catalog.load(s)
    await recs.retrain(force=True)
    sink.start()
    retrain_task = asyncio.create_task(recs.retrain_loop())
    yield
    retrain_task.cancel()
    await sink.stop()


app = FastAPI(title="AI DJ Studio", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def timing(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
              for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Validation failed", "errors": errors})


@app.get("/health")
async def health():
    return {"status": "ok", "tracks": len(catalog.all_tracks())}


@app.get("/health/gateway")
async def gateway_health():
    return {"status": "ok", "liveLounges": len(hub.live()),
            "sockets": sum(len(rt.sockets) for rt in hub.runtimes.values())}


for r in (auth.router, tracks.router, lounges.router, dashboard.router, admin.router, ws.router):
    app.include_router(r)

# Serve the built React client when present (single-process demo: `npm run build` then `uvicorn`).
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        return FileResponse(_DIST / "index.html")
