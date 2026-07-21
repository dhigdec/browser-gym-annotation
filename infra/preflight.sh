#!/usr/bin/env bash
# Pre-flight checks BEFORE the (billable) GCP deploy. Read-only — creates nothing,
# spends nothing. Run this first; when it's all green, run ./infra/deploy-gcp.sh.
#
#   ./infra/preflight.sh
#
# Override PROJECT / REGION via the environment to match deploy-gcp.sh.
set -uo pipefail

PROJECT="${PROJECT:-mlproject-501205}"
REGION="${REGION:-us-central1}"
DB_PASS="${DB_PASS:-}"

pass=0; fail=0; warn=0
ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; pass=$((pass+1)); }
no()   { printf "  \033[31m✗\033[0m %s\n     ↳ %s\n" "$1" "$2"; fail=$((fail+1)); }
note() { printf "  \033[33m!\033[0m %s\n     ↳ %s\n" "$1" "$2"; warn=$((warn+1)); }

printf "\n\033[1mGCP deploy pre-flight\033[0m  (project %s · region %s)\n\n" "$PROJECT" "$REGION"

# --- tooling -------------------------------------------------------------- #
command -v gcloud  >/dev/null 2>&1 && ok "gcloud CLI installed" || no "gcloud CLI missing" "Install the Google Cloud SDK: https://cloud.google.com/sdk/docs/install"
command -v python3 >/dev/null 2>&1 && ok "python3 installed (URL-encodes the DB password)" || no "python3 missing" "Install python3 (the deploy script uses it to encode DB_PASS)"

# --- auth + project ------------------------------------------------------- #
if command -v gcloud >/dev/null 2>&1; then
  ACCT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1)"
  [ -n "$ACCT" ] && ok "authenticated as $ACCT" || no "not authenticated" "Run: gcloud auth login"

  if gcloud projects describe "$PROJECT" >/dev/null 2>&1; then
    ok "project $PROJECT is accessible"
    BILL="$(gcloud beta billing projects describe "$PROJECT" --format='value(billingEnabled)' 2>/dev/null)"
    case "$BILL" in
      True|true) ok "billing is enabled on $PROJECT" ;;
      False|false) no "billing NOT enabled on $PROJECT" "Enable it: https://console.cloud.google.com/billing" ;;
      *) note "could not read billing status" "Check manually, or install the gcloud beta component (gcloud components install beta)" ;;
    esac
  else
    no "project $PROJECT not accessible" "Check the project id, or your account's access to it"
  fi
fi

# --- inputs --------------------------------------------------------------- #
if command -v gcloud >/dev/null 2>&1 && gcloud sql instances describe "${SQL_INSTANCE:-annotator-db}" >/dev/null 2>&1; then
  ok "Cloud SQL instance already exists — DB_PASS not needed for this run"
elif [ -n "$DB_PASS" ]; then
  ok "DB_PASS is set (first run will create the Cloud SQL user)"
else
  note "DB_PASS is not set" "Required on the FIRST deploy: DB_PASS='a-strong-password' ./infra/deploy-gcp.sh"
fi
[ -n "${ANTHROPIC_API_KEY:-}" ] && ok "ANTHROPIC_API_KEY set (enables the live agents + reward agent)" \
  || note "ANTHROPIC_API_KEY not set" "Optional — without it the LLM verifiers/agents fall back; deterministic features still work"
[ -n "${GYM_URL:-}" ] && ok "GYM_URL set (live 312-task gym features will work hosted)" \
  || note "GYM_URL not set" "Optional — the gym features gate cleanly without it; the fixture/verifier/scoring/persistence flow works regardless"

# --- verdict -------------------------------------------------------------- #
printf "\n  %s passed · %s warnings · %s blocking\n\n" "$pass" "$warn" "$fail"
if [ "$fail" -gt 0 ]; then
  printf "\033[31mNot ready.\033[0m Resolve the ✗ items above, then re-run.\n\n"
  exit 1
fi
printf "\033[32mReady to deploy.\033[0m  Run:\n  DB_PASS='…' ./infra/deploy-gcp.sh\n\n"
