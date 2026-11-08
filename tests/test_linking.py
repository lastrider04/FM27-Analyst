"""Linking line-ups to fixtures: exact scores first, then neighbouring opponents, then recency."""
import datetime as dt

from reader.fixtures import Fixture
from reader.matches import Match, PlayerMatch, TeamMatch, link_fixtures

US, BOU, LEI, SPU = 1001, 1002, 1003, 1004
TODAY = dt.date(2032, 1, 20)


def lineup(goals: int, conceded: int | None, neighbours=(), key="k") -> Match:
    players = [PlayerMatch(i, 1000 + i, {"goals": goals if i == 0 else 0, "distance_m": 9000.0, "passes_attempted": 30,
                                          "sub_on_minute": 0, "rating_x100": 700}) for i in range(11)]
    m = Match(key, TeamMatch(US, players, conceded=conceded), None)
    for club in neighbours:
        m.candidates[club] = TeamMatch(club, [])
    return m


def fixture(day: int, home: int, away: int, hg: int, ag: int) -> Fixture:
    return Fixture(date=dt.date(2032, 1, day), home_id=home, away_id=away, home=str(home), away=str(away), home_goals=hg,
                   away_goals=ag, home_pens=None, away_pens=None, competition_index=232, competition="PL", fixture_id=None)


def test_exact_score_beats_a_neighbour_from_another_match():
    # another club's team sat beside a copy of the 1-0 at Bournemouth; that club's 2-0 mustn't take it
    m = lineup(1, 0, neighbours=[LEI], key="cup")
    fx = [fixture(11, BOU, US, 0, 1), fixture(3, US, LEI, 2, 0)]
    link_fixtures([m], fx, US, TODAY)
    assert m.fixture is fx[0] and m.opponent is None              # the wrong neighbour isn't kept


def test_same_score_twice_is_told_apart_by_the_opponent():
    spurs, leicester = lineup(1, 2, neighbours=[SPU], key="a"), lineup(1, 2, neighbours=[LEI, 1005], key="b")
    fx = [fixture(7, US, SPU, 1, 2), fixture(17, LEI, US, 2, 1)]
    link_fixtures([spurs, leicester], fx, US, TODAY)
    assert spurs.fixture is fx[0] and leicester.fixture is fx[1]
    assert leicester.opponent.club_id == LEI and leicester.link_confidence == "high"


def test_conceding_fewer_is_ruled_out_unless_an_own_goal_and_the_opponent_agree():
    m = lineup(1, 0, key="x")
    fx = [fixture(17, LEI, US, 2, 1)]                              # we conceded 2 there; the keepers say 0
    link_fixtures([m], fx, US, TODAY)
    assert m.fixture is None
    m2 = lineup(1, 1, neighbours=[LEI], key="y")                  # 1 faced on target + 1 own goal, opponent agrees
    link_fixtures([m2], fx, US, TODAY)
    assert m2.fixture is fx[0]


def test_without_keeper_data_the_neighbouring_opponent_still_decides():
    m = lineup(1, None, neighbours=[LEI], key="z")
    fx = [fixture(11, BOU, US, 0, 1), fixture(17, LEI, US, 0, 1)]
    link_fixtures([m], fx, US, TODAY)
    assert m.fixture is fx[1]
