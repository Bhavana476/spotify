"""Runtime configuration. Every secret comes from the environment (see .env.example)."""
import os

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


DATABASE_URL = _env("DATABASE_URL", "sqlite+aiosqlite:///./djstudio.db")
JWT_SECRET = _env("JWT_SECRET")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = int(_env("ACCESS_TOKEN_MINUTES", "30"))  # PRD 10.1: <= 60
REFRESH_TOKEN_DAYS = int(_env("REFRESH_TOKEN_DAYS", "7"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or None
LLM_MODEL = _env("LLM_MODEL", "claude-haiku-5-5")
LLM_TIMEOUT_SECONDS = float(_env("LLM_TIMEOUT_SECONDS", "2.5"))

# Playback is simulated at the scheduling level (PRD 4.2). >1 speeds tracks up for demos.
PLAYBACK_SPEED = float(_env("PLAYBACK_SPEED", "1"))
OUTRO_WINDOW_SECONDS = float(_env("OUTRO_WINDOW_SECONDS", "20"))
SENTIMENT_WINDOW_SECONDS = float(_env("SENTIMENT_WINDOW_SECONDS", "30"))
RECONNECT_GRACE_SECONDS = float(_env("RECONNECT_GRACE_SECONDS", "10"))
EVENT_FLUSH_SECONDS = float(_env("EVENT_FLUSH_SECONDS", "1"))
EVENT_FLUSH_MAX = int(_env("EVENT_FLUSH_MAX", "50"))
CORS_ORIGINS = _env("CORS_ORIGINS", "http://localhost:5173").split(",")
