import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_DB = Path(tempfile.gettempdir()) / f"djstudio_test_{os.getpid()}.db"
os.environ.update({
    "DATABASE_URL": f"sqlite+aiosqlite:///{_DB.as_posix()}",
    "JWT_SECRET": "test-only-secret-not-for-deployment",
    "SEED_PASSWORD": "test-pass-123",
    "RECONNECT_GRACE_SECONDS": "0.3",
    "EVENT_FLUSH_SECONDS": "0.2",
    "ANTHROPIC_API_KEY": "",
})
BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def client():
    subprocess.run([sys.executable, "seed.py", "--reset"], cwd=BACKEND, env=os.environ, check=True,
                   capture_output=True)
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
    try:
        _DB.unlink()
    except OSError:
        pass


def login(client, email: str) -> dict:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "test-pass-123"})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="session")
def tokens(client):
    return {name: login(client, f"{name}@djstudio.dev") for name in ("admin", "host", "codj", "listener", "guest")}


def auth(tok: dict) -> dict:
    return {"Authorization": f"Bearer {tok['accessToken']}"}
