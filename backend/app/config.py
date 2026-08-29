from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── core ──
    database_url: str = (
        "postgresql+psycopg://autogent:autogent@localhost:5432/autogent"
    )
    redis_url: str = "redis://localhost:6379/0"
    frontend_url: str = "http://localhost:3000"

    # ── auth ──
    clerk_issuer: str = ""
    clerk_audience: str = ""
    clerk_jwks_url: str = ""
    clerk_secret_key: str = ""
    jwt_secret_key: str = "autogent-dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 72

    # ── credentials vault ──
    credential_encryption_key: str = ""

    # ── LLM ──
    ai_provider: str = "cerebras"
    cerebras_api_key: str = ""
    cerebras_model: str = "gpt-oss-120b"
    openai_api_key: str = ""
    agent_max_steps: int = 8
    agent_model_temperature: float = 0.2

    # ── Slack ──
    slack_client_id: str = ""
    slack_client_secret: str = ""
    slack_signing_secret: str = ""

    # ── integrations ──
    github_client_id: str = ""
    github_client_secret: str = ""
    github_webhook_secret: str = ""
    jira_client_id: str = ""
    jira_client_secret: str = ""
    linear_client_id: str = ""
    linear_client_secret: str = ""
    notion_client_id: str = ""
    notion_client_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""

    # ── Recall.ai ──
    recall_api_key: str = ""
    recall_region: str = "us-east-1"
    recall_workspace_verification_secret: str = ""
    recall_svix_webhook_secret: str | None = None

    # ── email ──
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@autogent.ai"

    # ── payments ──
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_currency: str = "INR"

    # ── misc ──
    reports_dir: str = "/tmp/autogent-reports"
    monitoring_hour_utc: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
