# Deploying to GCP (Cloud Run + Cloud SQL)

Two Cloud Run services (backend API + nginx-served SPA) backed by a Cloud SQL
Postgres instance. Schema is applied with Alembic migrations (not `create_all`)
in prod.

## Staged for a one-command deploy

Everything below has been verified locally so the billable deploy is low-risk:

- ✅ **Both images build** exactly as Cloud Build will (`docker build backend/`, `docker build frontend/`).
- ✅ **Prod boot path** — the backend image with `RUN_MIGRATIONS=1 AUTO_CREATE_ALL=false` against a fresh DB runs `alembic upgrade head`, builds all 11 tables at the head revision, and serves (exactly what Cloud Run does on boot).
- ✅ **No schema drift** — `alembic check` reports the models match the migrations.
- ✅ **nginx `/api` proxy** renders valid config against an HTTPS Cloud Run backend (Host + SNI set correctly — see the fix note below).

## 1 · Pre-flight (read-only, spends nothing)

```bash
./infra/preflight.sh
```
Checks gcloud is installed + authed, the project is accessible, billing is on,
and your inputs are set. Fix any ✗, then deploy.

## 2 · Deploy (billable)

```bash
gcloud auth login                       # project mlproject-501205, deccan.ai › MLTeam
DB_PASS='<a-strong-password>' \
ANTHROPIC_API_KEY='<optional>' \
./infra/deploy-gcp.sh
```
Re-run any time to ship an update (it rebuilds + redeploys; Cloud SQL is left as-is).

## What the deploy does
1. Enables the required APIs (Run, SQL Admin, Artifact Registry, Cloud Build, Secret Manager).
2. Creates an Artifact Registry docker repo (`annotator`).
3. Creates a Cloud SQL Postgres 16 instance (`annotator-db`, `db-f1-micro`), the database, and the user — **only on the first run**.
4. Builds + pushes the backend and frontend images with Cloud Build.
5. Deploys **annotator-backend** to Cloud Run (Cloud SQL socket; `RUN_MIGRATIONS=1` applies `alembic upgrade head` on boot; `AUTO_CREATE_ALL=false`). The catalog seeds on startup (3 fixtures always; the full 315 once `GYM_URL` is reachable).
6. Deploys **annotator-frontend** to Cloud Run, wiring `BACKEND_ORIGIN` + `BACKEND_HOST` so its `/api` proxy reaches the backend.
7. Prints the public backend + app URLs.

## Config (env vars, all overridable)
| Var | Default | Notes |
|---|---|---|
| `PROJECT` | `mlproject-501205` | GCP project |
| `REGION` | `us-central1` | Cloud Run + Cloud SQL region |
| `DB_PASS` | — | **required on first run** (URL-encoded automatically; any chars OK) |
| `DB_TIER` | `db-f1-micro` | smallest/cheapest; bump for load |
| `ANTHROPIC_API_KEY` | — | optional — enables the live agents + reward agent |
| `GYM_URL` | — | optional — a reachable gym URL (the live 312-task features) |

## Cost (rough, us-central1)
- **Cloud SQL** `db-f1-micro`: ~$8–10/mo (the main fixed cost).
- **Cloud Run**: pay-per-use; ~free at low traffic, backend pinned to 1 instance.
- **Artifact Registry / Cloud Build**: negligible (free tier covers this).

## The gym (optional, `GYM_URL`)
The live-agent-run, 312-task, resume, and autogen features need the
`ecommerce-browser-gym` server reachable at `GYM_URL`. Without it they gate
cleanly (the picker shows "gym not connected"); the sample tasks, verifier
engine, scoring, correction, and persistence all still work.

To host the gym, a `Dockerfile` is provided in that repo. It drives a real
headless browser and writes screenshots/trajectories to disk, so:
- **Easiest:** a small **Compute Engine VM** (e2-small+) — writable FS, run the image, open the port. Set the annotator's `GYM_URL` to `http://<vm-ip>:8000` and match `HARNESS_TOKEN` ↔ `GYM_HARNESS_TOKEN`.
- **Cloud Run:** works with `--memory 2Gi --cpu 2`, but mount tmpfs for `/app/screenshots` + `/app/trajectories` (its FS is read-only apart from `/tmp`).

## Inspecting the DB (DBeaver)
- **Local:** PostgreSQL · `localhost:5433` · db `browser_gym_annotator` · `annotator/annotator`. (Adminer web UI at `localhost:8081`.)
- **Cloud SQL:** run the [Cloud SQL Auth Proxy](https://cloud.google.com/sql/docs/postgres/sql-proxy) — `cloud-sql-proxy mlproject-501205:us-central1:annotator-db` — then point DBeaver at `localhost:5432` with the `annotator` user + your `DB_PASS`.

## Notes
- **Migrations**: `alembic upgrade head` runs on backend boot. New schema change → `alembic revision --autogenerate -m "…"`, commit, redeploy.
- **Secrets**: env vars are fine for staging. For production, move `DB_PASS` / `ANTHROPIC_API_KEY` into Secret Manager and reference with `--set-secrets`.
- The nginx `/api` proxy sends the **backend's hostname** as the `Host` header + SNI (`BACKEND_HOST`) — required for Cloud Run routing; sending the frontend's host 404s.
