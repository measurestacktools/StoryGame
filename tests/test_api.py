"""Tests: state machine, validation, JSON fallback. No live Groq calls (mocked)."""
import app as game
from fastapi.testclient import TestClient

client = TestClient(game.app)


def test_parse_json_defensive_plain():
    assert game.parse_json_defensive('{"a": 1}') == {"a": 1}


def test_parse_json_defensive_fences():
    assert game.parse_json_defensive('```json\n{"a": 2}\n```') == {"a": 2}


def test_parse_json_defensive_trailing_comma():
    assert game.parse_json_defensive('prefix {"a": 1,} suffix') == {"a": 1}


def test_parse_json_defensive_fails():
    try:
        game.parse_json_defensive("no json here")
        assert False, "should raise"
    except ValueError:
        pass


def test_clamp_state():
    s = game.clamp_state({"health": 999, "inventory": ["a", "a", ""], "flags": ["x"], "location": "L"})
    assert s["health"] == 100 and s["inventory"] == ["a"]
    s2 = game.clamp_state({"health": -5, "inventory": [], "flags": [], "location": ""})
    assert s2["health"] == 0


def test_status_presence_only():
    r = client.get("/api/status")
    assert r.status_code == 200
    j = r.json()
    assert "has_key" in j and "model" in j
    assert "key" not in str(j).lower() or "has_key" in str(j).lower()
    # ensure no key material leaks
    assert "gsk_" not in r.text


def test_start_bad_genre():
    r = client.post("/api/start", json={"genre": "Nope", "setting": "x", "character": "y", "style": "Epic"})
    assert r.status_code == 400


def test_start_bad_style():
    r = client.post("/api/start", json={"genre": "Fantasy", "setting": "x", "character": "y", "style": "Nope"})
    assert r.status_code == 400


def test_start_empty_setting():
    r = client.post("/api/start", json={"genre": "Fantasy", "setting": "", "character": "y", "style": "Epic"})
    assert r.status_code == 400


def test_choose_without_story():
    client.post("/api/restart")
    r = client.post("/api/choose", json={"choice_index": 0})
    assert r.status_code == 400
    assert "No story" in r.json()["error"]


def test_custom_validation(monkeypatch):
    # seed a fake story to reach action validation
    game._STORY = {"title": "T", "genre": "Fantasy", "style": "Epic", "setting": "S",
                   "character": "C", "state": game.clamp_state({}), "turn": 0,
                   "choices": ["a", "b", "c"], "log": [], "event": "e",
                   "consequence": "", "ending": None}
    r = client.post("/api/custom", json={"action": ""})
    assert r.status_code == 400
    r = client.post("/api/custom", json={"action": "x" * 501})
    assert r.status_code == 400
    client.post("/api/restart")


def test_choose_bad_index():
    game._STORY = {"title": "T", "genre": "Fantasy", "style": "Epic", "setting": "S",
                   "character": "C", "state": game.clamp_state({}), "turn": 0,
                   "choices": ["a", "b", "c"], "log": [], "event": "e",
                   "consequence": "", "ending": None}
    r = client.post("/api/choose", json={"choice_index": 9})
    assert r.status_code == 400
    client.post("/api/restart")


def test_full_flow_mocked(monkeypatch):
    """State machine with mocked Groq: item persists across turns."""
    calls = {"n": 0}

    def fake_groq(system, user, max_tokens=1400, temperature=0.9):
        calls["n"] += 1
        if "Start a" in user:
            return {"title": "Mock Tale", "opening": "You wake in a cave.",
                    "choices": ["Take the lantern", "Go north", "Rest"],
                    "state": {"health": 100, "inventory": [], "flags": ["begin"], "location": "Cave"}}
        inv = ["brass lantern"] if calls["n"] >= 2 else []
        return {"consequence": "You take the lantern.",
                "event": "Light fills the cave.",
                "choices": ["Go deeper", "Climb up", "Shout"],
                "state": {"health": 95, "inventory": inv, "flags": ["begin", "has_light"], "location": "Cave"},
                "ending": None}

    monkeypatch.setattr(game, "call_groq_json", fake_groq)
    monkeypatch.setattr(game, "get_effective_key", lambda: "fake")
    client.post("/api/restart")
    r = client.post("/api/start", json={"genre": "Fantasy", "setting": "Cave", "character": "Hero", "style": "Epic"})
    assert r.status_code == 200, r.text
    r = client.post("/api/choose", json={"choice_index": 0})
    assert r.status_code == 200
    assert "brass lantern" in r.json()["state"]["inventory"]
    # second turn: inventory must persist (state continuity)
    r = client.post("/api/custom", json={"action": "carry the lantern deeper"})
    assert r.status_code == 200
    assert "brass lantern" in r.json()["state"]["inventory"]
    assert r.json()["turn"] == 2
    # export works
    r = client.get("/api/export")
    assert r.status_code == 200 and "Mock Tale" in r.json()["markdown"]
    client.post("/api/restart")


def test_json_fallback_on_malformed(monkeypatch):
    def bad_groq(system, user, max_tokens=1400, temperature=0.9):
        raise RuntimeError("AI returned malformed JSON. boom")
    monkeypatch.setattr(game, "call_groq_json", bad_groq)
    monkeypatch.setattr(game, "get_effective_key", lambda: "fake")
    client.post("/api/restart")
    r = client.post("/api/start", json={"genre": "Comedy", "setting": "Tavern", "character": "Bard", "style": "Light"})
    assert r.status_code == 200  # fallback keeps game playable
    client.post("/api/restart")
