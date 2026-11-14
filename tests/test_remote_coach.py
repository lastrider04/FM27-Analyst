"""App panel › AI coach: remote play passes questions to the analyst's coach and shares nothing else."""
from remote import analyst


def test_coach_status_shares_only_ready_and_label(monkeypatch):
    monkeypatch.setattr(analyst, "fetch", lambda path, port_: {"ready": True, "label": "gpt", "email": "me@x.com",
                                                             "detail": "https://api.example.com"})
    assert analyst.coach_status(1) == {"ready": True, "label": "gpt"}


def test_coach_conversation_keeps_messages_only(monkeypatch):
    seen = []

    def fake(path, port_):
        seen.append(path)
        return {"messages": [{"role": "user", "content": "hi"},
                             {"role": "assistant", "content": "yo", "tools": ["Squad"], "usage": {"input": 9}},
                             {"role": "system", "content": "secret"}]}
    monkeypatch.setattr(analyst, "fetch", fake)
    out = analyst.coach_conversation("a/b")
    assert seen == ["/api/chats/a%2Fb"]
    assert out == {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo", "tools": ["Squad"]}]}


def test_coach_conversation_missing(monkeypatch):
    def gone(path, port_):
        raise analyst.AnalystUnavailable("404")
    monkeypatch.setattr(analyst, "fetch", gone)
    assert analyst.coach_conversation("x") is None
