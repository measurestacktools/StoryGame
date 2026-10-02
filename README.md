# 📖 StoryGame — AI Story/Adventure Game (Project 8)

Branching interactive fiction on **FastAPI + vanilla JS + Groq (`openai/gpt-oss-120b`)**.
Layout: **WORLD → EVENT → CHOICES → CONSEQUENCE**, with story log, inventory/health, custom actions, multiple endings, and `.md` export.

## Features
- Genre/setting/character/style setup, AI opening + 3 choices per turn
- Persistent state (health, inventory, flags) across turns, custom free-form actions
- Turn counter, story log, multiple endings, export, restart

## Requirements
- Python 3.10+
- A free Groq API key ([console.groq.com/keys](https://console.groq.com/keys))
- Internet (AI calls go to Groq)

## Installation
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate | macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env   # add GROQ_API_KEY  (or paste the key in Settings later)
```

## Limitations
- Short, contained adventure by design: single in-memory story (restart clears it); auto-finale at turn 10
- Needs a Groq key + internet; free-tier rate limits may need pacing

## How to play
1. Pick genre/style, enter setting + character → **Begin Adventure**
2. Pick one of 3 choices (or type a custom action ≤500 chars) each turn
3. Watch health/inventory/flags + codex; reach an ending, then **Export** or **Restart**

## Quickstart
```bash
pip install -r requirements.txt
copy .env.example .env   # add GROQ_API_KEY
python -m uvicorn app:app --port 8013
# open http://127.0.0.1:8013
```

## API
| Method | Route | Body | Notes |
|---|---|---|---|
| GET | `/api/status` | — | `{has_key, model, story_active, turn}` — presence only, never key |
| POST | `/api/key` | `{key}` | live-verifies via `models.list`, server-memory only |
| DELETE | `/api/key` | — | clears server memory |
| POST | `/api/start` | `{genre, setting, character, style}` | Groq JSON mode, defensive parse + fallback |
| POST | `/api/choose` | `{choice_index: 0-2}` | full state + log sent to Groq |
| POST | `/api/custom` | `{action≤500}` | free-form action |
| GET | `/api/story` | — | current story |
| GET | `/api/export` | — | `{markdown, title}` |
| POST | `/api/restart` | — | clears story |

Genres: Fantasy, Sci-Fi, Mystery, Horror, Comedy. Styles: Epic, Dark, Light.
Endings: Groq may return `ending:{title, epilogue}`; auto-finale at turn 10; health ≤ 0 forces an ending.

## Troubleshooting
- `No API key` — open Settings and paste a Groq key, or set `GROQ_API_KEY` in `.env`.
- `Invalid API key` — key rejected by Groq; generate a fresh one at console.groq.com/keys.
- `Groq is rate-limited` — wait a few seconds and retry.
- Story already ended — endings (including the turn-10 auto-finale) are final; press Restart/Play Again.
- Port in use — run `python -m uvicorn app:app --port 8013` on a free port.

## Tests
```bash
pip install -r requirements-test.txt
pytest -q
```

## Security
Frontend never stores/sends keys except `POST /api/key` on Save. Keys live in process memory (`_MEM_KEY`) or `GROQ_API_KEY` env. `/api/status` never leaks key material.
