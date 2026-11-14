"""Remote play › Picks: the bridge to the FM27 analyst (a fake analyst; no game, no network)."""
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("windows_capture")
from remote import analyst, auth, server  # noqa: E402

STATUS = {"latest": {"game_date": "2032-01-28"}, "game_running": True,
          "next": {"date": "2032-02-02", "kickoff": "20:00", "venue": "H", "opponent": "Tottenham",
                   "competition": "Premier League"}}
PLAYER = {"unique_id": 1, "name": "Désiré Doué", "position": "AM L", "condition": 69.0, "sharpness": 100.0,
          "jadedness": 300, "form": 7.2, "injury": None, "unfit": ["jaded (300)"], "caution": [], "why": "…",
          "starter": True, "ca": 180, "threat": 0.9}
OVERVIEW = {"next_match": {"recommended": [PLAYER], "swaps": [{"out": PLAYER, "in": PLAYER | {"name": "Yushi Soeda"}}],
                           "rest": [PLAYER], "basis": {"condition_at": "2032-01-28", "matches": 5}},
            "alerts": [{"kind": "jaded", "unique_id": 1, "name": "Désiré Doué", "detail": "jadedness 300"}],
            "upcoming": [{"date": "2032-02-02", "kickoff": "20:00", "opponent": "Tottenham", "venue": "H",
                          "competition": "Premier League", "home_goals": None}]}


@pytest.fixture
def fake_analyst(monkeypatch):
    monkeypatch.setattr(analyst, "fetch", lambda path, port_, timeout=5.0: {"/api/status": STATUS,
                                                                           "/api/overview": OVERVIEW}[path])
    monkeypatch.setattr(analyst, "port", lambda: 8775)


def test_summary_is_trimmed_to_what_the_panel_shows(fake_analyst):
    s = analyst.summary()
    assert s["as_of"] == "2032-01-28" and s["next"]["opponent"] == "Tottenham"
    assert s["swaps"][0]["out"]["name"] == "Désiré Doué" and s["swaps"][0]["in"]["name"] == "Yushi Soeda"
    assert "ca" not in s["picks"][0] and s["picks"][0]["unfit"] == ["jaded (300)"]
    assert s["alerts"] == [{"kind": "jaded", "name": "Désiré Doué", "detail": "jadedness 300"}]
    assert "home_goals" not in s["upcoming"][0]


def test_unpaired_phone_gets_nothing(fake_analyst, monkeypatch):
    monkeypatch.setattr(server.Hub, "__init__", lambda self, lan: _bare_hub(self, lan))
    monkeypatch.setattr(auth, "device_for", lambda cookies, ip, lan: (None, "pair"))
    c = TestClient(server.create_app(lan=False))
    assert c.get("/api/analyst").status_code == 401
    assert c.post("/api/analyst/capture", headers={"X-FM-Remote": "1", "Origin": "http://testserver",
                                                   "Host": "testserver"}).status_code == 401


def test_capture_needs_the_page_header(fake_analyst, monkeypatch):
    monkeypatch.setattr(server.Hub, "__init__", lambda self, lan: _bare_hub(self, lan))
    monkeypatch.setattr(auth, "device_for", lambda cookies, ip, lan: ({"id": "x", "name": "phone"}, ""))
    started = []
    monkeypatch.setattr(analyst, "start_capture", lambda port_=None: started.append(1) or {"started": True})
    c = TestClient(server.create_app(lan=False))
    assert c.post("/api/analyst/capture").status_code == 403 and not started
    assert c.get("/api/analyst").json()["next"]["opponent"] == "Tottenham"


def _bare_hub(self, lan):
    """A Hub without capture, input or banner (nothing on the PC is touched)."""
    self.lan, self.clients, self.loop, self.banner, self.encoders = lan, set(), None, None, {}
    self.fm, self.https_url = {"t": "fm", "state": None}, None
    self.capturer = type("C", (), {"start": lambda s: None, "stop": lambda s: None, "frame": None, "status": "off"})()
    self.controller = type("K", (), {"paused": False, "release_all": lambda s: None})()


SQUAD = {"game_date": "2032-01-28", "players": [
    {"unique_id": 2, "name": "Erling Haaland", "age": 31, "status": "loaned in", "condition": 99.0, "sharpness": 69.0,
     "jadedness": -313, "positions": '{"GK": 1, "ST": 20, "AMC": 12}', "injuries": None, "form": [6.4, 7.7],
     "form_label": "steady", "avg_rating": 6.73, "apps": 20, "ca": 192, "pa": 195, "contract_expires": "2032-06-30"},
    {"unique_id": 3, "name": "Karl Hein", "age": 29, "status": "first team", "condition": 100.0, "sharpness": 63.0,
     "jadedness": 350, "positions": '{"GK": 20}', "form": [], "form_label": None, "avg_rating": None, "apps": 0,
     "injuries": '[{"start": "2032-01-20", "min_days": 10, "max_days": 14}]'}]}
FIXTURES = {"fixtures": [
    {"id": 9, "date": "2032-02-04", "venue": "A", "opponent": "Tottenham", "competition": "Cup", "result": None,
     "home_goals": None, "away_goals": None},
    {"id": 8, "date": "2032-02-02", "venue": "H", "opponent": "Tottenham", "competition": "PL", "result": None,
     "home_goals": None, "away_goals": None},
    {"id": 7, "date": "2032-01-28", "venue": "A", "opponent": "Frankfurt", "competition": "UCL", "result": "W",
     "home_goals": 1, "away_goals": 3}]}


@pytest.fixture
def fake_analyst_all(monkeypatch):
    data = {"/api/status": STATUS, "/api/overview": OVERVIEW, "/api/squad": SQUAD, "/api/fixtures": FIXTURES}
    monkeypatch.setattr(analyst, "fetch", lambda path, port_, timeout=5.0: data[path])
    monkeypatch.setattr(analyst, "port", lambda: 8775)


def test_squad_is_grouped_and_trimmed(fake_analyst_all):
    s = analyst.squad()
    hein, haaland = s["players"]                            # goalkeepers first
    assert hein["group"] == "Goalkeepers" and haaland["group"] == "Attackers"
    assert haaland["positions"] == ["ST"] and haaland["loan"] and "ca" not in haaland
    assert hein["injury"] == "injured, back in 2-6 days" and hein["jadedness"] == 350


def test_fixtures_split_into_results_and_coming_up(fake_analyst_all):
    f = analyst.fixtures()
    assert [r["opponent"] for r in f["upcoming"]] == ["Tottenham", "Tottenham"]
    assert f["upcoming"][0]["date"] == "2032-02-02"         # soonest first
    assert f["results"][0]["score"] == "3-1"                # our goals first, away from home too


def test_squad_and_fixtures_need_pairing(fake_analyst_all, monkeypatch):
    monkeypatch.setattr(server.Hub, "__init__", lambda self, lan: _bare_hub(self, lan))
    monkeypatch.setattr(auth, "device_for", lambda cookies, ip, lan: (None, "pair"))
    c = TestClient(server.create_app(lan=False))
    assert c.get("/api/analyst/squad").status_code == 401
    assert c.get("/api/analyst/nothing").status_code == 404
    monkeypatch.setattr(auth, "device_for", lambda cookies, ip, lan: ({"id": "x", "name": "phone"}, ""))
    assert len(c.get("/api/analyst/squad").json()["players"]) == 2
