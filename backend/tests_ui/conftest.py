"""Browser tests against a RUNNING server (they never start one themselves).

    uvicorn app.main:app --host 127.0.0.1 --port 8000      # with the client built and the DB seeded
    python -m pytest tests_ui -q                            # UI_BASE_URL / UI_BROWSER_CHANNEL to override

Uses the locally installed Microsoft Edge by default (no browser download needed). Set UI_BROWSER_CHANNEL=chromium
after `python -m playwright install chromium` on machines without Edge.
"""
import os

import httpx
import pytest

BASE = os.getenv("UI_BASE_URL", "http://127.0.0.1:8000")
CHANNEL = os.getenv("UI_BROWSER_CHANNEL", "msedge")
DEMO_PASSWORD = os.getenv("SEED_PASSWORD", "djstudio-demo")


@pytest.fixture(scope="session")
def browser():
    try:
        httpx.get(f"{BASE}/health", timeout=3).raise_for_status()
    except Exception:
        pytest.skip(f"No server at {BASE} — start uvicorn first")
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel=None if CHANNEL == "chromium" else CHANNEL)
        except Exception as exc:
            pytest.skip(f"Could not launch browser channel '{CHANNEL}': {exc}")
        yield b
        b.close()


@pytest.fixture
def new_page(browser):
    """Factory: each call is a separate browser context (= a separate signed-in person)."""
    contexts, errors = [], []

    def make(width=1440, height=950):
        ctx = browser.new_context(viewport={"width": width, "height": height})
        contexts.append(ctx)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("dialog", lambda d: d.accept())
        return page

    yield make
    for ctx in contexts:
        ctx.close()
    assert not errors, f"JavaScript errors in the page: {errors}"


def sign_in(page, email, password=DEMO_PASSWORD):
    page.goto(BASE + "/")
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Walk in").click()
    page.locator(".bookcase").wait_for()
