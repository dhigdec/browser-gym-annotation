#!/usr/bin/env bash
# Deploy the annotation platform to GCP: Cloud SQL (Postgres) + two Cloud Run
# services (backend + frontend). Idempotent — safe to re-run to ship updates.
#
#   ./infra/deploy-gcp.sh
#
# Prereqs: gcloud authed (`gcloud auth login`), billing enabled on the project.
# Override any of the vars below via the environment.
set -euo pipefail

PROJECT="${PROJECT:-mlproject-501205}"
REGION="${REGION:-us-central1}"
REPO="${REPO:-annotator}"                     # Artifact Registry repo
SQL_INSTANCE="${SQL_INSTANCE:-annotator-db}"
DB_NAME="${DB_NAME:-browser_gym_annotator}"
DB_USER="${DB_USER:-annotator}"
DB_TIER="${DB_TIER:-db-f1-micro}"             # smallest/cheapest; bump for load
DB_PASS="${DB_PASS:-}"                         # required on first run (or set via Secret Manager)
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"    # optional (M6b live agent)
GYM_URL="${GYM_URL:-}"                         # optional (M6c/M8) — a reachable gym URL

AR="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"
CONN="${PROJECT}:${REGION}:${SQL_INSTANCE}"

say() { printf "\n\033[1;34m▸ %s\033[0m\n" "$*"; }

gcloud config set project "$PROJECT" >/dev/null

say "Enabling APIs"
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com

say "Artifact Registry repo ($REPO)"
gcloud artifacts repositories describe "$REPO" --location="$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$REPO" --repository-format=docker --location="$REGION"

say "Cloud SQL instance ($SQL_INSTANCE)"
if ! gcloud sql instances describe "$SQL_INSTANCE" >/dev/null 2>&1; then
  [ -n "$DB_PASS" ] || { echo "Set DB_PASS on first run (a strong password)"; exit 1; }
  gcloud sql instances create "$SQL_INSTANCE" --database-version=POSTGRES_16 \
    --tier="$DB_TIER" --region="$REGION" --storage-auto-increase
  gcloud sql databases create "$DB_NAME" --instance="$SQL_INSTANCE"
  gcloud sql users create "$DB_USER" --instance="$SQL_INSTANCE" --password="$DB_PASS"
fi

DB_URL="postgresql+psycopg://${DB_USER}:${DB_PASS}@/${DB_NAME}?host=/cloudsql/${CONN}"

say "Build + push images (Cloud Build)"
gcloud builds submit backend  --tag "$AR/backend:latest"
gcloud builds submit frontend --tag "$AR/frontend:latest"

say "Deploy backend (Cloud Run) — runs migrations on boot"
BACKEND_ENV="ENV=prod,AUTO_CREATE_ALL=false,RUN_MIGRATIONS=1,DATABASE_URL=${DB_URL},CORS_ORIGINS=[\"*\"]"
[ -n "$ANTHROPIC_API_KEY" ] && BACKEND_ENV="${BACKEND_ENV},ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"
[ -n "$GYM_URL" ]           && BACKEND_ENV="${BACKEND_ENV},GYM_URL=${GYM_URL}"
gcloud run deploy annotator-backend \
  --image "$AR/backend:latest" --region "$REGION" --platform managed --allow-unauthenticated \
  --add-cloudsql-instances "$CONN" --set-env-vars "$BACKEND_ENV" \
  --min-instances 1 --cpu 1 --memory 512Mi --timeout 300

BACKEND_URL="$(gcloud run services describe annotator-backend --region "$REGION" --format='value(status.url)')"

say "Deploy frontend (Cloud Run) — proxies /api → $BACKEND_URL"
gcloud run deploy annotator-frontend \
  --image "$AR/frontend:latest" --region "$REGION" --platform managed --allow-unauthenticated \
  --set-env-vars "BACKEND_ORIGIN=${BACKEND_URL}" --cpu 1 --memory 256Mi

FRONTEND_URL="$(gcloud run services describe annotator-frontend --region "$REGION" --format='value(status.url)')"
say "Done"
echo "  backend : $BACKEND_URL"
echo "  app     : $FRONTEND_URL"
