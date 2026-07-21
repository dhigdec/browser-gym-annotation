# Browser-Use Gym — Annotator Platform

The internal annotation/review platform for Deccan AI's browser-use gym. Annotators
review a model's run step-by-step, correct it (re-running the agent from the
corrected state), then build and run a multi-level **verifier suite** — and submit
the reward-gated result to the dataset.

Built on the existing `ecommerce-browser-gym` (task schema, deterministic seeding,
end-state verifiers, oracle solvers, 2k+ trajectories) and skinned with the
**Deccan Vault Design System**.

## Status — a functional platform (M1–M7 shipped)

| | Milestone | What's real |
|---|---|---|
| M1 | Pixel-faithful **Task Review** screen | ~95% to `docs/design-spec.md` |
| M2 | Live FastAPI review payload | `/api/tasks/{id}/review` |
| M3 | Captured **DOM snapshots** in the replay pane | self-contained, served per step |
| M4 | **Postgres persistence** | all 8 tables written; state survives a refresh; real submissions |
| M5 | **Verifier execution engine** | reward computed vs captured DOM + ground-truth state + trace (not flags) |
| M5b | **LLM judge** for the Semantic level | all 5 verifier levels execute for real |
| M6 | Re-run as a backend service | immutable, **versioned trajectory branches** |
| M6b | **Live agent re-run** | a real model generates the corrected continuation |
| M7 | **Multi-task queue** | task registry + working pager |
| M6c | **Live-gym bridge** | verify against the **real** gym world (true milestone verdict) |

The full loop runs for real: replay a recorded run → verify each step → correct →
**live agent re-runs from that state** → the five-level verifier suite **executes**
→ the reward is **computed** → submit writes a golden/breaker row → next task.

Integrity rules enforced in code: an empty/placeholder or unexecutable verifier
scores **0, never 1**; "override to submit" is per-check and stamped; reward = 1
requires **every** verifier to pass; correcting a step re-locks Section 2 entirely.

Still ahead: execute the agent's generated actions against a *live* gym world and
verify the true outcome (M6c), multi-annotator QA/agreement, per-step DOM capture.

## Structure
```
frontend/     Vite + React + TS SPA (the Task Review screen)
  src/ds/           re-implemented DS primitives + tokens (see docs/adr/0001)
  src/features/     the Task Review feature (replay, trace, verifier suite, dock)
  src/lib/          types, the review state machine (+ .test.ts), API client
  src/fixtures/     offline fallback payload
backend/      FastAPI platform API
  app/api/          tasks (registry) + sessions (persistence, run, rerun)
  app/verify.py     the verifier execution engine (check IR → real evaluation)
  app/agent.py      live agent + LLM judge (Anthropic; key from env)
  app/fixtures/     the primary task + tasks/ (the queue) + snapshots/
  app/scripts/      capture_snapshots.py (Playwright, run vs a live gym)
  tests/            pytest (executor, agent, registry, session lifecycle)
infra/        docker-compose (postgres · backend · frontend · adminer)
docs/         build plan, exact design spec, DS notes, feasibility, ADRs
```

## Run

**Frontend:**
```bash
cd frontend
npm install
npm run dev      # http://localhost:5180  (fixed 1440px design)
npm run lint     # oxlint DS adherence
npm run build    # tsc + vite build
npm run test     # vitest — the review state machine
```

**Backend (FastAPI + your local Postgres):**
```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
createdb browser_gym_annotator      # once
uvicorn app.main:app --port 8090 --reload
python -m pytest                    # executor · agent · registry · session lifecycle
```

**Full stack (Docker):**
```bash
docker compose -f infra/docker-compose.yml up --build
# frontend :8080 · backend :8090 · postgres :5433 · adminer :8081
```

**Live agent re-run (optional).** The correct-and-re-run flow uses a real model
to generate the corrected continuation. Set the key in the (gitignored)
`infra/.env` — never committed, read from the container's environment:
```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > infra/.env
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d --build backend
```
Without a key, the re-run cleanly falls back to the deterministic gold path (and
the Semantic verifiers to a deterministic proxy).

**Live gym (M6c, optional).** To verify against the *real* gym world, run the
`ecommerce-browser-gym` harness and point the annotator at it:
```bash
# in the gym repo, separate terminal:
HARNESS_TOKEN=dev-annotator-token python -m uvicorn server.main:app --port 8000
# then set the same token for the annotator (gitignored infra/.env):
echo "GYM_HARNESS_TOKEN=dev-annotator-token" >> infra/.env
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d backend
# GET /api/gym/status → {connected:true}; POST /api/gym/verify → the real milestone verdict.
```
The gym is reached at `GYM_URL` (default `http://host.docker.internal:8000` in
Docker). If it isn't running, the bridge degrades to a clean 502.

## Prerequisites
Node 20+, Python 3.12, Postgres 16/17 (native or via Docker), Docker (optional, for the full stack).

## Design fidelity notes
- Consumes the Deccan Vault tokens verbatim; primitives re-implemented from spec
  rather than loading the self-mounting compiled bundle (ADR 0001).
- Self-hosted Inter Display + JetBrains Mono (SIL OFL); Season Mix TRIAL dropped.
- Two integrity rules baked in vs. the prototype: an empty/placeholder verifier
  scores **0, never 1**; "override to submit" is per-check and stamped.
