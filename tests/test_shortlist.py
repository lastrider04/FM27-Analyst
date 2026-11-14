"""The "FM Analyst" shortlist: storing it, forgetting removed players, and the bid signals (synthetic data)."""
import copy

import pytest

from analytics.shortlist import shortlist, shortlist_player, signals
from capture.snapshot import store_snapshot
from store.db import connect
from tests.test_store import snapshot


def target(uid=2000000077, value=20_000_000, expires="2033-06-30", ca=140, added="2031-11-20"):
    return dict(unique_id=uid, name=f"Target {uid % 100}", first_name="T", last_name=str(uid), dob="2010-01-15",
                at_club_id=642, contract_club_id=642, ca=ca, pa=175, condition=95.0, sharpness=80.0, jadedness=0,
                value=value, wage_per_week=20000, contract_start="2029-07-01", contract_expires=expires,
                rep_home=5000, rep_current=5000, rep_world=4000, caps=3, intl_goals=1,
                attributes={"crossing": 60, "dribbling": 70}, positions={"DC": 20, "DM": 15}, injuries=[], added=added)


def snap_with(players, game_date="2031-11-29", found=True):
    s = snapshot(game_date=game_date, with_match=False)
    s["players"][0]["positions"] = {"DC": 20}
    s["shortlist"] = dict(name="FM Analyst", found=found, players=copy.deepcopy(players))
    return s


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "t.db")
    yield c
    c.close()


def test_history_builds_up_and_feeds_the_page(con):
    store_snapshot(con, snap_with([target()]))
    store_snapshot(con, snap_with([target(value=16_000_000, ca=146)], game_date="2032-03-01"))
    d = shortlist(con, 1001)
    assert d["found"] is True
    (p,) = d["players"]
    assert [h["value"] for h in p["history"]] == [20_000_000, 16_000_000]
    assert p["value_change_pct"] == -20.0 and p["ca_change"] == 6
    assert p["club"] == "Crystal Palace" and p["added"] == "2031-11-20"
    assert p["fit"] == {"position": "D C", "rank": 2, "of": 2, "best": 158}
    kinds = {s["text"].split(":")[0] for s in p["signals"]}
    assert any(t.startswith("Value down 20%") for t in kinds)
    detail = shortlist_player(con, 1001, p["unique_id"])
    assert detail["attributes"]["technical"]["dribbling"] == 70


def test_removed_players_are_forgotten(con):
    store_snapshot(con, snap_with([target(), target(uid=2000000088)]))
    store_snapshot(con, snap_with([target(uid=2000000088)], game_date="2031-12-05"))
    assert [p["unique_id"] for p in shortlist(con, 1001)["players"]] == [2000000088]
    for table in ("shortlist", "shortlist_state", "shortlist_attributes"):
        assert con.execute(f"SELECT count(*) FROM {table} WHERE unique_id = 2000000077").fetchone()[0] == 0
    # shortlist players never leak into your own squad
    assert con.execute("SELECT count(*) FROM player_state WHERE unique_id = 2000000088").fetchone()[0] == 0


def test_deleted_shortlist_empties_it_and_unreadable_keeps_it(con):
    store_snapshot(con, snap_with([target()]))
    s = snap_with([])
    s["shortlist"] = None                       # couldn't read it this time: keep what's stored
    store_snapshot(con, s)
    assert len(shortlist(con, 1001)["players"]) == 1
    store_snapshot(con, snap_with([], found=False))
    d = shortlist(con, 1001)
    assert d["found"] is False and d["players"] == []


def test_contract_signals():
    assert signals({"contract_months": 4})[0]["kind"] == "good"
    assert "Final year" in signals({"contract_months": 10})[0]["text"]
    assert "18 months" in signals({"contract_months": 17})[0]["text"]
    assert signals({"contract_months": 40}) == []


def test_go_now_list(con):
    store_snapshot(con, snap_with([target(expires="2032-09-30"), target(uid=2000000088)]))
    d = shortlist(con, 1001)
    assert d["go_now"] == [2000000077]          # final year of the contract; the other has years left
    (p,) = [x for x in d["players"] if x["unique_id"] == 2000000077]
    assert p["go_reasons"][0].startswith("final year")
