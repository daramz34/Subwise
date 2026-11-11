from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    SECRET_KEY: str

    APP_NAME: str = "Subwise"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"  # development | production

    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    BCRYPT_ROUNDS: int = 12
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    RESET_TOKEN_EXPIRE_MINUTES: int = 30

    MAX_FAILED_LOGINS: int = 5
    LOCKOUT_MINUTES: int = 15

    # AI provider: Google Gemini (receipts, PDFs, pasted emails)
    AI_API_KEY: str = ""
    AI_MODEL: str = "gemini-2.5-flash"  # set AI_MODEL in .env to the exact ID shown in AI Studio
    AI_API_URL: str = "https://generativelanguage.googleapis.com/v1beta/models"
    AI_TIMEOUT_SECONDS: int = 45
    # Uploads
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024
    MAX_CSV_ROWS: int = 5000
    RATE_LIMIT_ENABLED: bool = True

        # PayPal (Sandbox)
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_BASE_URL: str = "https://api-m.sandbox.paypal.com"
    PAYPAL_WEBHOOK_ID: str = ""   # set after deploy, when the webhook exists
    PAYPAL_RETURN_URL: str = "http://localhost:8000/?paypal=return"
    PAYPAL_CANCEL_URL: str = "http://localhost:8000/?paypal=cancel"

    # Used only by tests. The database name MUST contain the word 'test'.
    TEST_DATABASE_URL: str = ""

    # Comma-separated list of frontend origins allowed to call the API
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_must_be_long(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()