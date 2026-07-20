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

## Run (frontend)
```bash
cd frontend
npm install
npm run dev      # http://localhost:5180  (fixed 1440px design)
npm run lint     # oxlint DS adherence
npm run build    # tsc + vite build
```

## Design fidelity notes
- Consumes the Deccan Vault tokens verbatim; primitives re-implemented from spec
  rather than loading the self-mounting compiled bundle (ADR 0001).
- Self-hosted Inter Display + JetBrains Mono (SIL OFL); Season Mix TRIAL dropped.
- Two integrity rules baked in vs. the prototype: an empty/placeholder verifier
  scores **0, never 1**; "override to submit" is per-check and stamped.
