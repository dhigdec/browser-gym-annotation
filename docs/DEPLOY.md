# Deploying to GCP (Cloud Run + Cloud SQL)

The platform ships as two Cloud Run services (backend API + nginx-served SPA)
backed by a Cloud SQL Postgres instance. Schema is applied with Alembic
migrations (not `create_all`) in prod.

## Prerequisites
- `gcloud` authed: `gcloud auth login` (project `mlproject-501205`, deccan.ai › MLTeam)
- Billing enabled on the project
- Docker not required — images build with Cloud Build

## One command
```bash
DB_PASS='<a-strong-password>' \
ANTHROPIC_API_KEY='<optional, for the live agent>' \
./infra/deploy-gcp.sh
```
Re-run any time to ship an update (it rebuilds + redeploys; Cloud SQL is left as-is).

## What it does
1. Enables the required APIs (Run, SQL Admin, Artifact Registry, Cloud Build, Secret Manager).
2. Creates an Artifact Registry docker repo (`annotator`).
3. Creates a Cloud SQL Postgres 16 instance (`annotator-db`, `db-f1-micro`), the
   database, and the user — **only on the first run**.
4. Builds + pushes the backend and frontend images with Cloud Build.
5. Deploys **annotator-backend** to Cloud Run (connected to Cloud SQL via the
   built-in socket; `RUN_MIGRATIONS=1` applies `alembic upgrade head` on boot;
   `AUTO_CREATE_ALL=false`). The 315-task catalog seeds on startup.
6. Deploys **annotator-frontend** to Cloud Run, pointing its `/api` proxy at the
   backend's URL (`BACKEND_ORIGIN`).
7. Prints the public backend + app URLs.

## Config (env vars, all overridable)
| Var | Default | Notes |
|---|---|---|
| `PROJECT` | `mlproject-501205` | GCP project |
| `REGION` | `us-central1` | Cloud Run + Cloud SQL region |
| `DB_PASS` | — | **required on first run** |
| `DB_TIER` | `db-f1-micro` | smallest/cheapest; bump for load |
| `ANTHROPIC_API_KEY` | — | optional — enables the M6b live agent re-run |
| `GYM_URL` | — | optional — a reachable gym URL for M6c/M8 |

## Cost (rough, us-central1)
- **Cloud SQL** `db-f1-micro`: ~$8–10/mo (the main fixed cost).
- **Cloud Run**: pay-per-use; ~free at low traffic, backend pinned to 1 instance.
- **Artifact Registry / Cloud Build**: negligible (free tier covers this).

## Notes
- **Migrations**: `alembic upgrade head` runs on backend boot (`RUN_MIGRATIONS=1`).
  New schema changes → add a migration (`alembic revision --autogenerate -m "…"`),
  commit it, redeploy.
- **The gym (M6c/M8)** — the live-agent-run and 312-gym-task features need the
  `ecommerce-browser-gym` server reachable at `GYM_URL`. Until it's hosted, those
  features degrade gracefully (the gym picker reports "gym not reachable"); the
  fixture tasks, persistence, verifiers, and correction flow work fully.
- **Secrets**: for production, move `DB_PASS` / `ANTHROPIC_API_KEY` into Secret
  Manager and reference them with `--set-secrets` instead of `--set-env-vars`.
