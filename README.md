# 📖 StoryGame — AI Story/Adventure Game (Project 8)

Branching interactive fiction on **FastAPI + vanilla JS + Groq (`openai/gpt-oss-120b`)**.
Layout: **WORLD → EVENT → CHOICES → CONSEQUENCE**, with story log, inventory/health, custom actions, multiple endings, and `.md` export.

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

## Tests
```bash
pip install -r requirements-test.txt
pytest -q
```

## Security
Frontend never stores/sends keys except `POST /api/key` on Save. Keys live in process memory (`_MEM_KEY`) or `GROQ_API_KEY` env. `/api/status` never leaks key material.
