# Browser-Use Gym — Annotator Platform

The internal annotation/review platform for Deccan AI's browser-use gym. An
annotator picks a **breaker task**, watches the agent's recorded run step-by-step,
**corrects a step** (a live agent re-runs forward from that state), builds and runs
a multi-level **verifier suite**, and submits the reward-gated result to the dataset.

It sits on top of the `ecommerce-browser-gym` (task schema, deterministic seeding,
oracle solvers, end-state verifiers, real trajectories) and is skinned with the
**Deccan Vault Design System**.

---

## What's shipped

The full loop runs for real, on real tasks, persisted to Postgres:

> pick a breaker → replay the recorded run → verify each step → correct a step →
> **a live agent (gpt-5.1) re-runs forward from that state** → the five-level
> verifier suite **executes** → the reward is **computed** → submit writes a
> golden/breaker row → next task.

| Area | State |
|---|---|
| **Task queue** | the **85 curated breakers** (`sellable_breakers_v2`) are the main queue; `Demos` toggle → the 3 hand-authored fixtures; `All gym tasks` → browse all 312 |
| **Replay** | per-app browser tabs + captured DOM snapshots (fixtures) / per-step screenshots (gym), full-width tab-sized viewport |
| **Review & correct** | verify steps; correct a step → **live gym drive-forward** (gpt-5.1) forks the trajectory with the real continuation; the branch persists + restores on reload; the new steps start unreviewed |
| **Verifier suite** | 5 levels (ui · backend · semantic · process · safety) execute against captured DOM + ground-truth state + trace; LLM judge for semantic/safety |
| **Reward** | server-recomputed from the persisted suite; empty/placeholder verifier scores **0, never 1**; reward = 1 requires **every** verifier to pass; per-check "override to submit" is stamped |
| **Persistence** | normalized 11-table Postgres schema; every click (review progress, suite versions, corrections, overrides) survives a refresh; real submissions |
| **Gym bridge** | run the agent in the **live gym** and read the true milestone verdict; correct → re-verify against the real world |
| **QA review** | multi-annotator agreement + adjudication |
| **Deploy** | Alembic migrations; Cloud-Run-ready containers (see `docs/DEPLOY.md`) |

---

## Quick start (Docker — the whole stack, one command)

Requires **Docker Desktop** running.

```bash
docker compose -f infra/docker-compose.yml up --build
```

That brings up four containers. On first boot the backend **creates the schema and
seeds the task catalog automatically** — no manual DB setup needed.

| Service | URL | What it is |
|---|---|---|
| **frontend** | http://localhost:8080 | the Task Review app — open this |
| **backend** | http://localhost:8090 | FastAPI platform API |
| **postgres** | localhost:**5433** | the database (published on 5433 to avoid clashing with a native :5432) |
| **adminer** | http://localhost:8081 | web DB browser |

Open **http://localhost:8080** and you land on **"Breaker 1 of 85"**.

> To review breakers you also need the **live gym** running — see
> [Reviewing breakers](#reviewing-breakers-the-live-gym) below. The 3 `Demos`
> fixtures work without it.

---

## The databases

**One Postgres database, `browser_gym_annotator`** (user `annotator` / password
`annotator` in dev). Everything the annotator does is persisted here.

**Auto-provisioned in dev.** On startup the backend runs `create_all` and seeds
the catalog (`ENV=dev`, `auto_create_all=true`). No `createdb`/migrate step is
needed for the Docker stack — the tables exist and the tasks are seeded the moment
the backend is healthy.

**Seeded catalog (315 tasks):** 3 hand-authored fixtures + 312 gym tasks (of which
the 85 curated breakers are the default queue). Gym task briefs/trajectories are
filled from the live gym on first review; the 85 breaker manifest lives at
`backend/app/data/breakers.json`.

**Schema — 11 FK-linked tables** (`backend/app/models.py`):

```
annotator ─┐
task ──────┼─< review_session ─< trajectory ─< trajectory_step
           │        ├─< verifier_suite ─< verifier
           │        │            └─< benchmark_run
           │        ├─< trajectory_branch     (correction forks — versioned)
           │        └─< submission
           └────────< audit_log
```

Deleting a `review_session` cascades to its suites/verifiers/runs/branches/
submissions; annotators + audit rows are `SET NULL`.

**Browse it** — Adminer at http://localhost:8081 (System `PostgreSQL`, Server
`postgres`, User/Pass `annotator`, DB `browser_gym_annotator`), or any client:

```bash
PGPASSWORD=annotator psql -h localhost -p 5433 -U annotator -d browser_gym_annotator
```

**Reset to a clean slate** (dev-only, hard-gated to `ENV=dev` + `auto_create_all`)
— wipes all sessions/suites/runs/submissions/branches but keeps the task catalog,
so every task reopens fresh at 0-reviewed:

```bash
curl -X POST http://localhost:8090/api/admin/reset-sessions
```

**Production** uses Alembic instead of `create_all`: set `AUTO_CREATE_ALL=false`
+ `RUN_MIGRATIONS=1` and the container runs `alembic upgrade head` before serving
(6 revisions in `backend/migrations/`). See `docs/DEPLOY.md`.

---

## Reviewing breakers (the live gym)

Breaker tasks are reviewed by running the agent in the **live gym** and loading the
real trajectory. Start the gym from the `ecommerce-browser-gym` repo (a separate
terminal), then the annotator reaches it at `GYM_URL`
(`http://host.docker.internal:8000` from Docker):

```bash
# in the ecommerce-browser-gym repo:
python -m uvicorn server.main:app --port 8000
```

- **Opening a breaker** runs the **oracle** (deterministic, no API key) and loads
  its trajectory + milestone verifiers.
- **Correcting a step** drives a **live agent (`openai` / gpt-5.1)** forward from
  the corrected state — this needs `OPENAI_API_KEY` set in the **gym's** `.env`
  (the Anthropic `llm` agent is used elsewhere but is currently org-capped).
- `GET /api/gym/status` → `{connected:true}` when the gym is reachable. If it
  isn't, breaker review degrades cleanly (and the 3 `Demos` fixtures still work).

The annotator's own optional **fixture** live re-run uses Anthropic — set
`ANTHROPIC_API_KEY` in the (gitignored) `infra/.env`; without it, the fixture
re-run falls back to the deterministic gold path.

```bash
# optional keys, passed at runtime, never baked into the image:
cat > infra/.env <<'EOF'
ANTHROPIC_API_KEY=sk-ant-...        # optional — fixture re-run + semantic judge
GYM_HARNESS_TOKEN=dev-annotator-token
EOF
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d --build backend
```

---

## The annotator workflow

1. **Pick a task** — `Breaker N of 85` (prev/next/skip), or `Demos` for fixtures.
2. **Review & correct (Section 1)** — step through the run; **Verify** each step or
   **Correct** one. Correcting drives the agent forward from that state and forks
   the trajectory with the real continuation (marked *"Re-ran from step N · via
   live agent"*); the new steps start unreviewed, so walk them, then **Approve**.
3. **Build the verifier suite (Section 2)** — generate multi-level verifiers, edit/
   add them, **Run** the benchmark. Reward = 1 requires every verifier to pass;
   override a failing check (stamped) if warranted.
4. **Submit** — writes a golden (reward 1) or breaker (reward 0) row.
5. **QA review** — a second annotator adjudicates agreement.

Everything persists per action; a refresh restores exactly where you left off.

---

## Local dev (without Docker)

**Frontend:**
```bash
cd frontend
npm install
npm run dev      # http://localhost:5180
npm run build    # tsc + vite build
npm run test     # vitest — the review state machine
```

**Backend (needs a local Postgres on 5432, or point DATABASE_URL at the Docker one on 5433):**
```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
createdb browser_gym_annotator          # once (skip if using the Docker postgres)
uvicorn app.main:app --port 8090 --reload
python -m pytest                        # executor · agent · registry · sessions · gym
```

---

## Project structure
```
frontend/     Vite + React + TS SPA (the Task Review screen)
  src/ds/           re-implemented Deccan Vault DS primitives + tokens (ADR 0001)
  src/features/     the Task Review feature (replay pane, action trace, verifier suite)
  src/lib/          types, the review state machine (+ .test.ts), API client
backend/      FastAPI platform API
  app/api/          tasks · sessions (persistence/run/rerun/rerun-gym) · gym · qa · export · admin
  app/verify.py     the verifier execution engine (check IR → real evaluation)
  app/agent.py      live agent + LLM judge (Anthropic; key from env)
  app/gym_client.py + gym_review.py   the live-gym bridge + trajectory→review mapping
  app/data/         breakers.json (the 85 curated breaker queue)
  app/seed.py       catalog seeding (fixtures + 312 gym tasks)
  app/models.py     the 11-table ORM schema
  migrations/       Alembic (prod schema)
  tests/            pytest (68 tests)
infra/        docker-compose (postgres · backend · frontend · adminer)
docs/         build plan, design spec, DS notes, DEPLOY.md, ADRs
```

## Environment variables (backend)

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | local Postgres | Postgres connection (psycopg3) |
| `ENV` | `dev` | `dev` enables auto-create + the admin reset; set `prod` in production |
| `AUTO_CREATE_ALL` | `true` | dev bootstraps the schema; prod sets `false` + `RUN_MIGRATIONS=1` |
| `GYM_URL` | `http://host.docker.internal:8000` | the live gym harness |
| `GYM_HARNESS_TOKEN` | — | gym auth token |
| `ANTHROPIC_API_KEY` | — | optional: fixture re-run + semantic/safety judge |
| `AGENT_MODEL` | `claude-haiku-4-5-20251001` | annotator-side model |
| `CORS_ORIGINS` | `["http://localhost:8080"]` | allowed origins |

## Deploy

Cloud-Run-ready. `docs/DEPLOY.md` covers the GCP path (Cloud SQL + two Cloud Run
services, Alembic migrations, templated nginx). Deploy is owner-run and billable.

## Prerequisites
Docker Desktop (for the full stack) · Node 20+ · Python 3.12 · Postgres 17
(native, or via the Docker stack) · a running `ecommerce-browser-gym` for breaker review.
