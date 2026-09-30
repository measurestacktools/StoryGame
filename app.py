"""PROJECT 8 — AI Story/Adventure Game. FastAPI + Groq (openai/gpt-oss-120b)."""
import json
import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

MODEL = "openai/gpt-oss-120b"
BASE_URL = "https://api.groq.com/openai/v1"
GENRES = ["Fantasy", "Sci-Fi", "Mystery", "Horror", "Comedy"]
STYLES = ["Epic", "Dark", "Light"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="StoryGame")
_MEM_KEY: Optional[str] = None
_STORY: Optional[Dict[str, Any]] = None


def get_effective_key() -> str:
    if _MEM_KEY:
        return _MEM_KEY
    return (os.getenv("GROQ_API_KEY", "") or os.getenv("GROQ_TEST_KEY", "") or "").strip()


def get_client(key: str):
    from openai import OpenAI
    return OpenAI(base_url=BASE_URL, api_key=key, timeout=30.0)


def verify_key_live(key: str) -> None:
    client = get_client(key)
    client.models.list()


def map_groq_error(e: Exception) -> str:
    s = str(e).lower()
    if "401" in s or "unauthorized" in s or "invalid api key" in s or "incorrect api key" in s:
        return "Invalid API key. Open Settings and paste a valid Groq key."
    if "429" in s or "rate limit" in s or "too many requests" in s:
        return "Groq is rate-limited right now. Wait a few seconds and try again."
    if "timeout" in s or "connection" in s or "network" in s:
        return "Network error reaching Groq. Check your connection and try again."
    if "model" in s and ("not found" in s or "does not exist" in s):
        return f"Model {MODEL} unavailable. Try again later."
    return f"AI error: {str(e)[:220]}"


def parse_json_defensive(text: str) -> Dict[str, Any]:
    """Defensively parse JSON from an LLM response. Raises ValueError if unrecoverable."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # try largest {...} span
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = t[start:end + 1]
        try:
            obj = json.loads(snippet)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        # light repair: trailing commas
        repaired = re.sub(r",\s*([}\]])", r"\1", snippet)
        try:
            obj = json.loads(repaired)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    raise ValueError("Could not parse AI JSON response")


def clamp_state(state: Dict[str, Any]) -> Dict[str, Any]:
    try:
        health = int(state.get("health", 100))
    except Exception:
        health = 100
    health = max(0, min(100, health))
    inv = state.get("inventory", []) or []
    flags = state.get("flags", []) or []
    inv = [str(x)[:80] for x in inv if str(x).strip()][:20]
    flags = [str(x)[:80] for x in flags if str(x).strip()][:20]
    # dedupe preserving order
    inv = list(dict.fromkeys(inv))
    flags = list(dict.fromkeys(flags))
    loc = str(state.get("location", "Unknown"))[:120] or "Unknown"
    return {"health": health, "inventory": inv, "flags": flags, "location": loc}


def call_groq_json(system: str, user: str, max_tokens: int = 1400, temperature: float = 0.9) -> Dict[str, Any]:
    key = get_effective_key()
    if not key:
        raise RuntimeError("NO_KEY: Add your Groq API key via Settings (gear icon).")
    client = get_client(key)
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = resp.choices[0].message.content or ""
        return parse_json_defensive(text)
    except RuntimeError:
        raise
    except ValueError as ve:
        raise RuntimeError(f"AI returned malformed JSON. {ve}")
    except Exception as e:
        raise RuntimeError(map_groq_error(e))


START_SYSTEM = (
    "You are a game master for an interactive branching adventure. "
    "Maintain strict state continuity (health 0-100, inventory, flags, characters, events, location). "
    "Always reply with valid JSON only, no markdown fences."
)
CHOOSE_SYSTEM = (
    "You are a game master for an interactive branching adventure. "
    "The player state and story-so-far are given. Apply consequences logically: "
    "update health (damage/heal), add/remove inventory items, set flags, move location, track characters. "
    "After 6-10 turns, or when the story naturally concludes or health hits 0, set an 'ending' "
    "object {title, epilogue}. Otherwise ending must be null. "
    "Always reply with valid JSON only."
)


def fallback_start(genre: str, setting: str, character: str, style: str) -> Dict[str, Any]:
    return {
        "title": f"{genre} Tale: {setting[:40]}",
        "opening": f"({style} {genre} adventure — AI JSON fallback.) {character} stands in {setting}. "
                   "The air shifts. Three paths shimmer ahead, each humming with consequence.",
        "choices": ["Push through the main gate", "Sneak around the side", "Call out and listen"],
        "state": {"health": 100, "inventory": [], "flags": ["begin"], "location": setting[:120]},
    }


def fallback_continue(action_text: str, state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "consequence": f"You chose: {action_text}. (Fallback narration — Groq JSON was malformed.)",
        "event": "The world reacts subtly. Dust settles, and three new options emerge from the haze.",
        "choices": ["Press onward", "Search the area", "Rest and observe"],
        "state": state,
        "ending": None,
    }


def build_markdown(story: Dict[str, Any]) -> str:
    lines = [f"# {story.get('title','Untitled Adventure')}", ""]
    lines.append(f"_Genre: {story.get('genre','')} · Style: {story.get('style','')} · Turns: {story.get('turn',0)}_")
    lines.append("")
    for entry in story.get("log", []):
        t = entry.get("turn", 0)
        if entry.get("type") == "opening":
            lines.append(f"## Opening (Turn {t})")
            lines.append(entry.get("text", ""))
        else:
            lines.append(f"## Turn {t} — {entry.get('text','')}")
            if entry.get("consequence"):
                lines.append(f"**Consequence:** {entry['consequence']}")
            if entry.get("event"):
                lines.append(entry["event"])
        lines.append("")
    st = story.get("state", {})
    lines.append(f"**Health:** {st.get('health')} · **Location:** {st.get('location')}")
    lines.append(f"**Inventory:** {', '.join(st.get('inventory', [])) or '—'}")
    lines.append(f"**Flags:** {', '.join(st.get('flags', [])) or '—'}")
    if story.get("ending"):
        lines.append("")
        lines.append(f"# Ending: {story['ending'].get('title','')}")
        lines.append(story["ending"].get("epilogue", ""))
    return "\n".join(lines) + "\n"


# ---- models ----
class KeyIn(BaseModel):
    key: str = ""


class StartIn(BaseModel):
    genre: str = ""
    setting: str = ""
    character: str = ""
    style: str = ""


class ChooseIn(BaseModel):
    choice_index: Any = None


class CustomIn(BaseModel):
    action: str = ""


# ---- routes ----
@app.get("/api/status")
def api_status():
    return {
        "has_key": bool(get_effective_key()),
        "model": MODEL,
        "story_active": _STORY is not None,
        "turn": (_STORY or {}).get("turn", 0),
        "has_ending": bool((_STORY or {}).get("ending")),
    }


@app.post("/api/key")
def api_set_key(body: KeyIn):
    global _MEM_KEY
    key = (body.key or "").strip()
    if not key:
        return JSONResponse({"error": "Key must not be empty."}, status_code=400)
    if len(key) > 300 or " " in key:
        return JSONResponse({"error": "That key format looks invalid."}, status_code=400)
    try:
        verify_key_live(key)
    except Exception as e:
        return JSONResponse({"error": map_groq_error(e)}, status_code=401)
    _MEM_KEY = key
    return {"ok": True}


@app.delete("/api/key")
def api_del_key():
    global _MEM_KEY
    _MEM_KEY = None
    return {"ok": True, "has_key": bool(get_effective_key())}


@app.post("/api/restart")
def api_restart():
    global _STORY
    _STORY = None
    return {"ok": True}


@app.get("/api/story")
def api_story():
    if not _STORY:
        return JSONResponse({"error": "No story yet. Start a new adventure first."}, status_code=404)
    return _STORY


@app.get("/api/export")
def api_export():
    if not _STORY:
        return JSONResponse({"error": "Nothing to export yet."}, status_code=404)
    return {"markdown": build_markdown(_STORY), "title": _STORY.get("title", "story")}


@app.post("/api/start")
def api_start(body: StartIn):
    global _STORY
    genre = (body.genre or "").strip()
    style = (body.style or "").strip()
    setting = (body.setting or "").strip()
    character = (body.character or "").strip()
    if genre not in GENRES:
        return JSONResponse({"error": f"Bad genre. Choose one of: {', '.join(GENRES)}."}, status_code=400)
    if style not in STYLES:
        return JSONResponse({"error": f"Bad style. Choose one of: {', '.join(STYLES)}."}, status_code=400)
    if not setting or not character:
        return JSONResponse({"error": "Setting and character must not be empty."}, status_code=400)
    if len(setting) > 200 or len(character) > 200:
        return JSONResponse({"error": "Setting/character must be ≤ 200 characters."}, status_code=400)
    if not get_effective_key():
        return JSONResponse({"error": "No API key. Open Settings and add your Groq key."}, status_code=401)

    user = (
        f"Start a {style} {genre} interactive story.\nSetting: {setting}\nMain character: {character}\n"
        "Return JSON with keys: title (string), opening (2-4 vivid sentences), "
        "choices (array of exactly 3 short distinct action strings), "
        "state (object: health int 0-100 starting at 100, inventory array of strings, "
        "flags array of strings, location string)."
    )
    try:
        data = call_groq_json(START_SYSTEM, user)
        title = str(data.get("title", f"{genre} Adventure"))[:120] or f"{genre} Adventure"
        opening = str(data.get("opening", ""))[:3000] or "Your adventure begins."
        choices = data.get("choices", [])
        choices = [str(c)[:160] for c in choices if str(c).strip()][:3]
        if len(choices) != 3:
            raise ValueError("AI must return exactly 3 choices")
        state = clamp_state(data.get("state", {}) if isinstance(data.get("state"), dict) else {})
        if not state["location"] or state["location"] == "Unknown":
            state["location"] = setting[:120]
    except RuntimeError as e:
        msg = str(e)
        if msg.startswith("NO_KEY"):
            return JSONResponse({"error": "No API key. Open Settings and add your Groq key."}, status_code=401)
        if "Invalid API key" in msg:
            return JSONResponse({"error": msg}, status_code=401)
        if "rate-limit" in msg:
            return JSONResponse({"error": msg}, status_code=429)
        # malformed JSON → fallback so game stays playable
        fb = fallback_start(genre, setting, character, style)
        title, opening, choices, state = fb["title"], fb["opening"], fb["choices"], clamp_state(fb["state"])

    _STORY = {
        "title": title, "genre": genre, "style": style,
        "setting": setting, "character": character,
        "state": state, "turn": 0, "choices": choices,
        "log": [{"turn": 0, "type": "opening", "text": opening}],
        "opening": opening, "event": opening,
        "consequence": "", "ending": None,
    }
    return {"title": title, "opening": opening, "event": opening,
            "choices": choices, "state": state, "turn": 0}


def _advance(action_text: str):
    global _STORY
    assert _STORY is not None
    state = _STORY["state"]
    log = _STORY["log"]
    history = "\n".join(
        f"T{e.get('turn')}: {str(e.get('text',''))[:200]} | {str(e.get('consequence',''))[:200]} | {str(e.get('event',''))[:200]}"
        for e in log[-10:]
    )
    user = (
        f"Title: {_STORY['title']}\nGenre: {_STORY['genre']} Style: {_STORY['style']}\n"
        f"Character: {_STORY['character']}\nCurrent state: {json.dumps(state)}\n"
        f"Turn: {_STORY['turn']}\nStory so far:\n{history}\n\n"
        f"Player action: {action_text}\n\n"
        "Return JSON with: consequence (1-3 sentences resolving the action), "
        "event (2-4 sentences describing the new situation), "
        "choices (exactly 3 new distinct actions, or [] if ending), "
        "state (updated full object: health, inventory, flags, location — preserve continuity, "
        "carry items/flags forward unless logically removed), "
        "ending (null normally; {title, epilogue} only when story should conclude — e.g. health<=0 or arc resolved)."
    )
    try:
        data = call_groq_json(CHOOSE_SYSTEM, user)
        consequence = str(data.get("consequence", ""))[:3000] or "Nothing happens."
        event = str(data.get("event", ""))[:3000] or "The scene shifts."
        new_state = clamp_state(data.get("state", state) if isinstance(data.get("state"), dict) else state)
        ending = data.get("ending")
        if ending is not None:
            if not isinstance(ending, dict):
                ending = None
            else:
                ending = {"title": str(ending.get("title", "Finale"))[:120],
                          "epilogue": str(ending.get("epilogue", ""))[:3000]}
                if not ending["epilogue"]:
                    ending = None
        choices = data.get("choices", [])
        if ending:
            choices = []
        else:
            choices = [str(c)[:160] for c in choices if str(c).strip()][:3]
            if len(choices) != 3:
                raise ValueError("AI must return exactly 3 choices")
        if new_state["health"] <= 0 and not ending:
            ending = {"title": "The End", "epilogue": "Your health has failed. The adventure ends here."}
            choices = []
    except RuntimeError as e:
        msg = str(e)
        if msg.startswith("NO_KEY"):
            return JSONResponse({"error": "No API key. Open Settings and add your Groq key."}, status_code=401)
        if "Invalid API key" in msg:
            return JSONResponse({"error": msg}, status_code=401)
        if "rate-limit" in msg:
            return JSONResponse({"error": msg}, status_code=429)
        if "malformed JSON" in msg:
            fb = fallback_continue(action_text, state)
            consequence, event, new_state, ending = fb["consequence"], fb["event"], clamp_state(fb["state"]), None
            choices = fb["choices"]
        else:
            return JSONResponse({"error": msg}, status_code=502)
    turn = _STORY["turn"] + 1
    # auto-ending at 10 turns if AI hasn't ended
    if turn >= 10 and not ending:
        ending = {"title": "A Fitting Pause",
                  "epilogue": event + " The chapter closes — for now. Your legend will continue another day."}
        choices = []
    _STORY.update({"turn": turn, "state": new_state, "choices": choices,
                   "consequence": consequence, "event": event, "ending": ending})
    _STORY["log"].append({"turn": turn, "type": "action", "text": action_text,
                          "consequence": consequence, "event": event})
    out: Dict[str, Any] = {"consequence": consequence, "event": event, "choices": choices,
                           "state": new_state, "turn": turn, "ending": ending}
    return out


@app.post("/api/choose")
def api_choose(body: ChooseIn):
    if not _STORY:
        return JSONResponse({"error": "No story yet. Start a new adventure first."}, status_code=400)
    if _STORY.get("ending"):
        return JSONResponse({"error": "Story already ended. Restart to play again."}, status_code=400)
    try:
        idx = int(body.choice_index)
    except Exception:
        return JSONResponse({"error": "choice_index must be 0, 1 or 2."}, status_code=400)
    if idx not in (0, 1, 2) or idx >= len(_STORY.get("choices", [])):
        return JSONResponse({"error": "Invalid choice_index for current choices."}, status_code=400)
    if not get_effective_key():
        return JSONResponse({"error": "No API key. Open Settings and add your Groq key."}, status_code=401)
    action_text = _STORY["choices"][idx]
    res = _advance(f"[Choice {idx+1}] {action_text}")
    if isinstance(res, JSONResponse):
        return res
    res["picked"] = action_text
    return res


@app.post("/api/custom")
def api_custom(body: CustomIn):
    if not _STORY:
        return JSONResponse({"error": "No story yet. Start a new adventure first."}, status_code=400)
    if _STORY.get("ending"):
        return JSONResponse({"error": "Story already ended. Restart to play again."}, status_code=400)
    action = (body.action or "").strip()
    if not action:
        return JSONResponse({"error": "Custom action must not be empty."}, status_code=400)
    if len(action) > 500:
        return JSONResponse({"error": "Custom action must be ≤ 500 characters."}, status_code=400)
    if not get_effective_key():
        return JSONResponse({"error": "No API key. Open Settings and add your Groq key."}, status_code=401)
    return _advance(action)


if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
