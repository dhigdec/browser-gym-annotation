# Backend — Platform API (FastAPI)

Python so it can directly import and run the gym, its verifiers, and the oracle
solvers in later milestones. Currently serves the review contract from a fixture
and connects to Postgres (schema auto-created in dev).

## Run natively (uses the local Postgres)
```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
createdb browser_gym_annotator        # once
uvicorn app.main:app --port 8090 --reload
# → http://localhost:8090/health   /api/tasks   /api/tasks/GYM-2041/review
```

## Layout
```
app/
  config.py     env-driven settings (pydantic-settings)
  db.py         SQLAlchemy 2.0 engine + session
  models.py     core platform schema (task, review_session, verifier_suite, …)
  main.py       FastAPI app + /health + dev create_all
  api/tasks.py  /api/tasks endpoints (fixture for now → real gym data in M2)
  fixtures/     the review contract fixture (mirrors the frontend types)
```

## Config (`.env`, see repo-root `.env.example`)
- `DATABASE_URL` — default `postgresql+psycopg://localhost:5432/browser_gym_annotator`
- `CORS_ORIGINS` — the Vite dev origin(s)

Migrations move to Alembic before we depend on the schema in anger; `create_all`
is a dev convenience only.
