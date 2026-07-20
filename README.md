# Browser-Use Gym — Annotator Platform

The internal annotation/review platform for Deccan AI's browser-use gym. Annotators
review a model's run step-by-step, correct it (re-running the agent from the
corrected state), then build and run a multi-level **verifier suite** — and submit
the reward-gated result to the dataset.

Built on the existing `ecommerce-browser-gym` (task schema, deterministic seeding,
end-state verifiers, oracle solvers, 2k+ trajectories) and skinned with the
**Deccan Vault Design System**.

## Status
**Milestone 1 — done:** pixel-faithful **Task Review** screen on fixtures (no live
backend yet). Reproduces the full two-stage flow: review & correct → verifier suite
→ benchmark → submit, including the correct-and-re-run fork and the
Safety-fails-until-corrected trap. Adapted to our apps (ShopGym · ValueMart ·
Calendar · ShopMail).

Roadmap (see `docs/BUILD_PLAN.md`): real trajectory data → DOM capture + replay →
process-per-session + branch re-run → verifiers-as-data → oracle gate + breaker
path → queue/auth/multi-user.

## Structure
```
frontend/     Vite + React + TS SPA (the Task Review screen)
  src/ds/           re-implemented DS primitives + tokens (see docs/adr/0001)
  src/features/     the Task Review feature
  src/fixtures/     M1 mock data (an adapted gym task)
  src/lib/          types + the review state machine
packages/ds/  vendored Deccan Vault DS (tokens + fonts) — reference
backend/      FastAPI platform API (M2+)
infra/        docker-compose etc. (M2+)
docs/         build plan, exact design spec, DS notes, feasibility, ADRs
```

## Run

**Frontend (the M1 screen):**
```bash
cd frontend
npm install
npm run dev      # http://localhost:5180  (fixed 1440px design)
npm run lint     # oxlint DS adherence
npm run build    # tsc + vite build
```

**Backend (FastAPI + your local Postgres):**
```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
createdb browser_gym_annotator      # once
uvicorn app.main:app --port 8090 --reload
# → /health  /api/tasks  /api/tasks/GYM-2041/review   (schema auto-created)
```

**Full stack (Docker):**
```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
# frontend :8080 · backend :8090 · postgres :5433 · adminer :8081
```

## Prerequisites
Node 20+, Python 3.12, Postgres 16/17 (native or via Docker), Docker (optional, for the full stack).

## Design fidelity notes
- Consumes the Deccan Vault tokens verbatim; primitives re-implemented from spec
  rather than loading the self-mounting compiled bundle (ADR 0001).
- Self-hosted Inter Display + JetBrains Mono (SIL OFL); Season Mix TRIAL dropped.
- Two integrity rules baked in vs. the prototype: an empty/placeholder verifier
  scores **0, never 1**; "override to submit" is per-check and stamped.
