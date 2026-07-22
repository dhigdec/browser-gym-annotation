from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Platform API configuration (env-driven; see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres — the local dev default matches a stock Homebrew install.
    database_url: str = "postgresql+psycopg://localhost:5432/browser_gym_annotator"

    # CORS — the Vite dev server.
    cors_origins: list[str] = ["http://localhost:5180", "http://127.0.0.1:5180"]

    # Path to the gym repo (imported directly in later milestones for
    # verifiers/oracle); optional until then.
    gym_repo_path: str = ""

    # Live agent re-run (M6b). Key read from the environment — never committed.
    # Empty key → the re-run falls back to the deterministic gold path.
    anthropic_api_key: str = ""
    agent_model: str = "claude-haiku-4-5-20251001"

    # Live gym (M6c). The running ecommerce-browser-gym harness — for verifying
    # against the real world state. In Docker this is host.docker.internal.
    gym_url: str = "http://localhost:8000"
    gym_harness_token: str = ""

    env: str = "dev"

    # Dev bootstraps the schema with create_all; prod (GCP) sets this false and
    # applies Alembic migrations instead (`alembic upgrade head`).
    auto_create_all: bool = True

    # Minimal auth (login-gated platform). `auth_secret` signs the session token —
    # SET A REAL VALUE via AUTH_SECRET in prod. The token rides in an HttpOnly,
    # SameSite=Lax cookie. auth_enabled=false leaves the platform open (dev only).
    auth_secret: str = "dev-insecure-auth-secret-change-me"
    auth_cookie: str = "bg_auth"
    auth_ttl_hours: int = 168  # 7 days
    auth_enabled: bool = True
    # Open self-registration is OFF: accounts are the 5 seeded dummy annotators
    # (see seed.py). This also closes the account-claim takeover hole. Flip on via
    # ALLOW_REGISTRATION=1 when self-signup is wanted.
    allow_registration: bool = False


settings = Settings()
