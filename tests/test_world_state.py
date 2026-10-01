"""World-state persistence tests (mocked Groq, no network)."""
import app as game
from fastapi.testclient import TestClient

client = TestClient(game.app)


def _seed_key(monkeypatch):
    monkeypatch.setattr(game, "get_effective_key", lambda: "fake")


def test_world_state_init_on_start(monkeypatch):
    _seed_key(monkeypatch)

    def fake_groq(system, user, max_tokens=1400, temperature=0.9):
        return {"title": "T", "opening": "Once upon a time.",
                "choices": ["a", "b", "c"],
                "state": {"health": 100, "inventory": [], "flags": [], "location": "Cave"},
                "world_state": {"characters": [{"name": "Hero", "note": "protagonist"}],
                                "locations": ["Cave"], "items": ["lantern"],
                                "open_threads": ["find the door"], "turn": 0}}

    monkeypatch.setattr(game, "call_groq_json", fake_groq)
    client.post("/api/restart")
    r = client.post("/api/start", json={"genre": "Fantasy", "setting": "Cave", "character": "Hero", "style": "Epic"})
    assert r.status_code == 200, r.text
    ws = r.json()["world_state"]
    assert ws["turn"] == 0
    assert any(c["name"] == "Hero" for c in ws["characters"])
    assert "Cave" in ws["locations"]
    # persisted server-side
    assert game._STORY["world_state"]["turn"] == 0
    client.post("/api/restart")


def test_world_state_missing_falls_back(monkeypatch):
    """Model omits world_state -> seeded default keeps story working."""
    _seed_key(monkeypatch)

    def fake_groq(system, user, max_tokens=1400, temperature=0.9):
        return {"title": "T", "opening": "Hi.", "choices": ["a", "b", "c"],
                "state": {"health": 100, "inventory": [], "flags": [], "location": "Cave"}}

    monkeypatch.setattr(game, "call_groq_json", fake_groq)
    client.post("/api/restart")
    r = client.post("/api/start", json={"genre": "Fantasy", "setting": "Cave", "character": "Hero", "style": "Epic"})
    assert r.status_code == 200
    ws = r.json()["world_state"]
    assert any(c["name"] == "Hero" for c in ws["characters"])
    client.post("/api/restart")


def test_world_state_update_and_persist_across_turns(monkeypatch):
    _seed_key(monkeypatch)

    def fake_groq(system, user, max_tokens=1400, temperature=0.9):
        if "Start a" in user:
            return {"title": "Mock Tale", "opening": "You wake in a cave.",
                    "choices": ["Take the lantern", "Go north", "Rest"],
                    "state": {"health": 100, "inventory": [], "flags": ["begin"], "location": "Cave"},
                    "world_state": {"characters": [{"name": "Hero", "note": "protagonist"}],
                                    "locations": ["Cave"], "items": [], "open_threads": ["explore"], "turn": 0}}
        # must receive compact world state in prompt (anti-drift)
        assert "Cave" in user
        return {"consequence": "You take the lantern.", "event": "Light fills the cave.",
                "choices": ["Go deeper", "Climb up", "Shout"],
                "state": {"health": 95, "inventory": ["lantern"], "flags": ["begin"], "location": "Cave"},
                "world_state": {"characters": [{"name": "Hero", "note": "has lantern"}],
                                "locations": ["Cave", "Tunnel"], "items": ["lantern"],
                                "open_threads": ["explore", "map the tunnel"], "turn": 1},
                "ending": None}

    monkeypatch.setattr(game, "call_groq_json", fake_groq)
    client.post("/api/restart")
    client.post("/api/start", json={"genre": "Fantasy", "setting": "Cave", "character": "Hero", "style": "Epic"})
    r = client.post("/api/choose", json={"choice_index": 0})
    assert r.status_code == 200, r.text
    ws = r.json()["world_state"]
    assert "Tunnel" in ws["locations"] and "lantern" in ws["items"]
    assert ws["turn"] == 1
    # /api/story persists it
    assert client.get("/api/story").json()["world_state"]["turn"] == 1
    client.post("/api/restart")


def test_world_state_parse_fail_keeps_old(monkeypatch):
    """Model returns garbage world_state type -> old state kept, story still works."""
    _seed_key(monkeypatch)
    calls = {"n": 0}

    def fake_groq(system, user, max_tokens=1400, temperature=0.9):
        calls["n"] += 1
        if "Start a" in user:
            return {"title": "T", "opening": "O.", "choices": ["a", "b", "c"],
                    "state": {"health": 100, "inventory": [], "flags": [], "location": "Cave"},
                    "world_state": {"characters": [{"name": "Hero", "note": "p"}],
                                    "locations": ["Cave"], "items": ["sword"],
                                    "open_threads": ["quest"], "turn": 0}}
        return {"consequence": "c", "event": "e", "choices": ["x", "y", "z"],
                "state": {"health": 100, "inventory": [], "flags": [], "location": "Cave"},
                "world_state": "garbage-not-a-dict", "ending": None}

    monkeypatch.setattr(game, "call_groq_json", fake_groq)
    client.post("/api/restart")
    client.post("/api/start", json={"genre": "Fantasy", "setting": "Cave", "character": "Hero", "style": "Epic"})
    r = client.post("/api/choose", json={"choice_index": 0})
    assert r.status_code == 200, r.text
    ws = r.json()["world_state"]
    assert "sword" in ws["items"]  # old preserved
    assert r.json()["world_state_ok"] is False
    client.post("/api/restart")


def test_clamp_world_state_caps():
    ws = game.clamp_world_state({"characters": [{"name": f"C{i}", "note": "x"} for i in range(50)],
                                 "locations": [f"L{i}" for i in range(50)],
                                 "items": [f"I{i}" for i in range(50)],
                                 "open_threads": [f"T{i}" for i in range(50)],
                                 "turn": 9999})
    assert len(ws["characters"]) <= 12 and len(ws["locations"]) <= 12
    assert len(ws["items"]) <= 20 and len(ws["open_threads"]) <= 12
    assert ws["turn"] <= 999
    assert len(game.compact_world_state(ws)) <= 1600
