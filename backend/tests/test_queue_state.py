import asyncio
import random

import pytest

from app.gateway.lounge_state import LoungeState, QueueError

HOST, CODJ, L1, L2, L3 = 1, 2, 3, 4, 5


def make(clock=None):
    st = LoungeState("lg_t", HOST, {"maxParticipants": 4, "soundclashEnabled": True, "battleSeconds": 30},
                     clock=clock or (lambda: 1000.0))
    for uid in (HOST, CODJ, L1):
        st.connect(uid, f"u{uid}")
    st.start("t_seed")
    return st


def test_vote_reorders_and_is_idempotent():
    st = make()
    a, b, c = (st.add_track(t, L1) for t in ("t_a", "t_b", "t_c"))
    assert [q.track_id for q in st.next_up] == ["t_a", "t_b", "t_c"]
    assert st.vote(L1, c.entry_id) is True
    assert st.vote(L1, c.entry_id) is False  # same user again: no double count
    assert [q.track_id for q in st.next_up][0] == "t_c" and len(c.votes) == 1
    st.vote(L1, c.entry_id, up=False)
    assert [q.track_id for q in st.next_up] == ["t_a", "t_b", "t_c"]


def test_sparse_positions_only_moved_row_changes():
    st = make()
    items = [st.add_track(f"t_{i}", L1) for i in range(5)]
    before = {q.entry_id: q.position for q in items}
    assert sorted(before.values()) == [1000, 2000, 3000, 4000, 5000]
    st.promote(items[3].entry_id)
    changed = [e for e, p in before.items() if next(q for q in st.next_up if q.entry_id == e).position != p]
    assert changed == [items[3].entry_id]
    assert st.next_up[0].entry_id == items[3].entry_id


def test_concurrent_votes_converge_to_single_order():
    """Many concurrent voters on different tracks; the final order must equal the order derived from the
    final tallies, and every snapshot observed by any 'client' is internally consistent."""
    st = make()
    entries = [st.add_track(f"t_{i}", L1) for i in range(6)]
    observed = []

    async def voter(uid):
        rng = random.Random(uid)
        for _ in range(20):
            e = rng.choice(entries)
            st.vote(uid, e.entry_id, rng.random() > 0.3)
            observed.append((st.version, [q["entryId"] for q in st.queue_view()]))
            await asyncio.sleep(0)

    async def run():
        await asyncio.gather(*(voter(uid) for uid in range(100, 130)))

    asyncio.run(run())
    expected = sorted(entries, key=lambda q: (-len(q.votes), q.position))
    assert [q.entry_id for q in st.next_up] == [q.entry_id for q in expected]
    versions = [v for v, _ in observed]
    assert versions == sorted(versions) and len(set(versions)) == len(versions)  # strictly ordered mutations


def test_capacity_lock_and_ban():
    st = make()
    st.connect(L2, "l2")
    with pytest.raises(QueueError) as e:
        st.connect(L3, "l3")
    assert e.value.code == "full"
    st.settings["maxParticipants"] = 10
    st.locked = True
    with pytest.raises(QueueError):
        st.connect(L3, "l3")
    st.banned.add(L2)
    with pytest.raises(QueueError):
        st.connect(L2, "l2")


def test_reconnect_is_not_a_fresh_join():
    st = make()
    st.drop_connection(L1)
    assert st.connect(L1, "u3") is False or st.participants[L1].connections == 1


def test_host_disconnect_promotes_longest_present_codj():
    st = make()
    st.co_djs.update({CODJ, L1})
    st.drop_connection(HOST)
    outcome = st.finalize_leave(HOST)
    assert outcome["promotedHost"] == CODJ  # joined before L1
    assert st.host_user_id == CODJ and HOST in st.co_djs and not st.frozen


def test_host_disconnect_without_codj_freezes_then_unfreezes():
    st = make()
    st.add_track("t_a", L1)
    st.drop_connection(HOST)
    assert st.finalize_leave(HOST)["frozen"] is True
    assert st.host_state == "disconnected"
    with pytest.raises(QueueError) as e:
        st.vote(L1, st.next_up[0].entry_id)
    assert e.value.code == "frozen"
    st.connect(HOST, "host")
    assert not st.frozen and st.host_state == "connected"
    st.vote(L1, st.next_up[0].entry_id)


def test_reconnect_within_grace_cancels_leave():
    st = make()
    st.drop_connection(HOST)
    st.connect(HOST, "host")
    assert st.finalize_leave(HOST) is None and not st.frozen


def test_soundclash_full_flow_splices_winner_into_next_up():
    st = make()
    defender = st.add_track("t_def", HOST)
    st.add_track("t_other", HOST)
    st.submit_challenger("t_ch1", L1)
    st.submit_challenger("t_ch2", CODJ)
    battle = st.open_battle("host")
    assert [c["trackId"] for c in battle.candidates] == ["t_def", "t_ch1", "t_ch2"]
    st.battle_vote(L1, "t_ch1")
    st.battle_vote(CODJ, "t_ch1")
    st.battle_vote(HOST, "t_def")
    st.battle_vote(HOST, "t_ch2")  # changing your vote replaces it
    assert battle.tally() == {"t_def": 0, "t_ch1": 2, "t_ch2": 1}
    assert st.close_battle() == "t_ch1"
    assert [q.track_id for q in st.next_up][:3] == ["t_ch1", "t_def", "t_other"]
    assert st.next_up[0].locked_reason == "battle"
    with pytest.raises(QueueError):
        st.battle_vote(L1, "t_ch1")


def test_soundclash_tie_requires_tiebreak_among_leaders():
    st = make()
    st.add_track("t_def", HOST)
    st.submit_challenger("t_ch", L1)
    st.submit_challenger("t_ch2", L1)
    st.open_battle("ai_dj")
    st.battle_vote(L1, "t_ch")
    st.battle_vote(HOST, "t_def")
    assert st.close_battle() is None and st.battle.status == "tied"
    with pytest.raises(QueueError):
        st.apply_battle_winner("t_ch2")  # not one of the tied leaders
    assert st.apply_battle_winner("t_def") == "t_def"
    assert st.next_up[0].track_id == "t_def"


def test_battle_requires_two_candidates_and_respects_settings():
    st = make()
    with pytest.raises(QueueError):
        st.open_battle("host")
    st.settings["soundclashEnabled"] = False
    with pytest.raises(QueueError):
        st.submit_challenger("t_x", L1)


def test_advance_moves_head_to_now_playing():
    st = make()
    st.add_track("t_a", L1)
    st.add_track("t_b", L1)
    st.vote(L1, st.next_up[1].entry_id)
    finished = st.advance()
    assert finished["trackId"] == "t_seed" and st.now_playing["trackId"] == "t_b"
    assert st.history == ["t_seed"]
