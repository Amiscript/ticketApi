from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT_KEY = "change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "TicketFlow"
    debug: bool = False

    database_url: str = "postgresql+psycopg://ticketflow:ticketflow@localhost:5432/ticketflow"
    # Convenience for local dev/tests. Use Alembic migrations in production.
    auto_create_tables: bool = False

    secret_key: str = _INSECURE_DEFAULT_KEY
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    max_tickets_per_order: int = 10

    rate_limit_enabled: bool = True
    rate_limit_storage_uri: str = "memory://"
    rate_limit_default: str = "100/minute"
    rate_limit_auth: str = "5/minute"
    rate_limit_purchase: str = "10/minute"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "tickets@ticketflow.local"

    @model_validator(mode="after")
    def _check_secrets(self) -> "Settings":
        if not self.debug and (
            self.secret_key == _INSECURE_DEFAULT_KEY or len(self.secret_key) < 32
        ):
            raise ValueError(
                "SECRET_KEY must be set to a random string of at least 32 characters "
                "(or set DEBUG=true for local development). "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
