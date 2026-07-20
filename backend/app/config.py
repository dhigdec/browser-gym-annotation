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

    env: str = "dev"


settings = Settings()
