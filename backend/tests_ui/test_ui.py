import re
import uuid

import httpx

from .conftest import BASE, DEMO_PASSWORD, sign_in

SECTIONS = ["Picked for you", "Host a night", "Got an invite", "On tonight", "Your card", "Past nights"]


def pick_option(select, starts_with):
    label = next(o for o in select.locator("option").all_inner_texts() if o.lstrip("✓✗ ").startswith(starts_with))
    select.select_option(label=label)


def test_shopfront_every_shelf_opens_its_section(new_page):
    page = new_page()
    sign_in(page, "listener@djstudio.dev")
    for title in SECTIONS:
        page.locator(".shelf", has_text=title).click()
        assert page.locator(".section-head h1").inner_text() == title
    page.locator(".shelf", has_text="Picked for you").click()
    first = page.locator(".pick-sleeve h3").inner_text()
    page.get_by_role("button", name="Next pick").first.click()
    assert page.locator(".pick-sleeve h3").inner_text() != first


def test_brand_new_member_gets_shop_favourites_not_flat_scores(new_page):
    email = f"ui{uuid.uuid4().hex[:8]}@djstudio.dev"
    httpx.post(f"{BASE}/api/v1/auth/register", json={"email": email, "password": "ui-test-pass",
                                                      "displayName": "UI Newcomer"}).raise_for_status()
    page = new_page()
    sign_in(page, email, "ui-test-pass")
    assert page.locator(".pick-tag").inner_text().lower() == "shop favourite"


def test_two_members_one_booth_end_to_end(new_page):
    host, guest = new_page(), new_page()
    sign_in(host, "host@djstudio.dev")
    host.locator(".shelf", has_text="Host a night").click()
    host.get_by_role("button", name=re.compile("Open the doors")).click()
    host.get_by_role("button", name="Drop the needle").click()
    code = host.locator(".code-chip").inner_text()
    for title in ("Glass Horizon", "Pulse Theory", "Signal Bloom"):
        pick_option(host.locator(".crate select"), title)
        host.get_by_role("button", name="Add to crate").click()
        host.locator(".sleeve", has_text=title).wait_for()

    sign_in(guest, "listener@djstudio.dev")
    guest.locator(".shelf", has_text="Got an invite").click()
    guest.get_by_label("Invite code").fill(code)
    guest.get_by_role("button", name=re.compile("Step inside")).click()
    guest.locator(".sleeve").nth(2).wait_for()

    # Vote: the third record jumps to the top on BOTH screens.
    third = guest.locator(".sleeve strong").nth(2).inner_text()
    guest.locator(".sleeve .vote-pill").nth(2).click()
    for page in (guest, host):
        page.wait_for_function("t => document.querySelector('.sleeve strong').innerText === t", arg=third)

    # Grounded Q&A cites the liner notes.
    guest.get_by_role("button", name="Ask the DJ").click()
    guest.locator(".writer input").fill("where's this sample from?")
    guest.get_by_role("button", name="Ask", exact=True).click()
    assert "evt_2001_1" in guest.locator(".entry.answer .cite").first.inner_text()

    # Soundclash: challenge, ring the bell, vote, close -> winner takes the next slot everywhere.
    pick_option(guest.locator(".clash-panel select"), "Afterglow Protocol")
    guest.get_by_role("button", name="Challenge").click()
    host.get_by_role("button", name="Ring the bell now").click()
    guest.locator(".contender-card", has_text="Afterglow Protocol").get_by_role("button", name="Back this one").click()
    host.get_by_role("button", name="Close voting now").click()
    for page in (guest, host):
        page.wait_for_function("() => document.querySelector('.sleeve strong').innerText === 'Afterglow Protocol'")
        assert page.locator(".sleeve").first.locator(".stamp").text_content() == "Won the clash"

    # The AI DJ plans a mix with its reasoning shown.
    host.get_by_role("button", name="Cue the outro").click()
    host.locator(".decision").wait_for()
    assert "Afterglow Protocol" in host.locator(".decision-track").inner_text()

    # End the night -> the ledger lists the battle read back from the soundclash tables.
    lounge_url = host.url
    host.get_by_role("button", name="End the night").click()
    host.get_by_text("Lights up").wait_for()
    host.goto(lounge_url.replace("/booth/", "/ledger/"))
    host.locator(".battle-list").wait_for()
    assert "Afterglow Protocol" in host.locator(".battle-list .winner").inner_text()
    assert host.locator(".ledger-table").get_by_text("Soundclashes").count() == 1


def test_workbench_rejects_bad_profile_and_files_good_one(new_page):
    page = new_page()
    sign_in(page, "admin@djstudio.dev")
    page.get_by_role("link", name="Workbench").click()
    track_id = f"t_ui{uuid.uuid4().hex[:6]}"
    page.get_by_label("Catalogue no.").fill(track_id)
    page.get_by_label("Title").fill("UI Test Pressing")
    page.get_by_label("Artist").fill("The Testers")
    page.get_by_label("Camelot key").fill("13C")
    page.get_by_role("button", name="Check it").click()
    assert "not a valid Camelot key" in page.locator(".notice").inner_text()
    assert page.locator("label.bad").count() == 1

    page.get_by_label("Camelot key").fill("8A")
    page.get_by_role("button", name="File the record").click()
    page.get_by_text(f"Filed as {track_id}").wait_for()

    token = httpx.post(f"{BASE}/api/v1/auth/login", json={"email": "admin@djstudio.dev",
                                                         "password": DEMO_PASSWORD}).json()["accessToken"]
    httpx.delete(f"{BASE}/api/v1/admin/tracks/{track_id}", headers={"Authorization": f"Bearer {token}"})


def test_listener_has_no_workbench(new_page):
    page = new_page()
    sign_in(page, "listener@djstudio.dev")
    assert page.get_by_role("link", name="Workbench").count() == 0
    page.goto(BASE + "/workbench")
    page.locator(".bookcase").wait_for()  # falls back to the shopfront; the API also refuses (test_rbac.py)


def test_phone_width_never_scrolls_sideways(new_page):
    page = new_page(390, 844)
    sign_in(page, "listener@djstudio.dev")
    assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
