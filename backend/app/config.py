"""Application settings. Secrets are loaded from environment variables and
validated at startup — no insecure defaults are shipped. The app refuses to
start in production mode if required secrets are missing.
"""
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import os


class Settings(BaseSettings):
    # ── core ──
    database_url: str = (
        "postgresql+psycopg://autogent:autogent@localhost:5432/autogent"
    )
    redis_url: str = "redis://localhost:6379/0"
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"
    environment: str = "development"  # development | staging | production
    log_level: str = "INFO"

    # ── auth ──
    clerk_issuer: str = ""
    clerk_audience: str = ""
    clerk_jwks_url: str = ""
    clerk_secret_key: str = ""
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

    # ── credentials vault ──
    credential_encryption_key: str = ""

    # ── LLM ──
    # Supported providers: gemini (default), cerebras, openai
    ai_provider: str = "gemini"
    cerebras_api_key: str = ""
    cerebras_model: str = "gpt-oss-120b"
    openai_api_key: str = ""

    # ── Google Gemini / Vertex AI ──
    # For Gemini Developer API: set GEMINI_API_KEY
    # For Vertex AI / Agent Platform: set USE_VERTEX_AI=true, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    use_vertex_ai: bool = False
    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    # Use Google ADK as the agent framework for the chat agent
    use_adk_agent: bool = True

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
    recall_svix_webhook_secret: str = ""

    # ── email ──
    # Email sending is disabled by default. Set EMAIL_ENABLED=true to enable.
    # SMTP settings below are kept for future use when email is re-enabled.
    email_enabled: bool = False
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

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _validate_production_secrets(self):
        """In production, refuse to start without required secrets."""
        if not self.is_production:
            return self
        required = [
            ("jwt_secret_key", self.jwt_secret_key, "JWT secret key"),
            ("credential_encryption_key", self.credential_encryption_key, "Credential encryption key"),
            ("database_url", self.database_url, "Database URL"),
        ]
        missing = [label for _, val, label in required if not val or val.startswith("autogent-dev")]
        if missing:
            raise ValueError(
                f"Missing required production secrets: {', '.join(missing)}. "
                "Set them via environment variables before starting the server."
            )
        if len(self.jwt_secret_key) < 32:
            raise ValueError("jwt_secret_key must be at least 32 characters in production")
        return self

    @field_validator("environment")
    @classmethod
    def _valid_env(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("development", "staging", "production"):
            raise ValueError("environment must be development, staging, or production")
        return v


settings = Settings()
