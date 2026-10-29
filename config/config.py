from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "TicketFlow"
    debug: bool = False

    database_url: str = "postgresql+psycopg://ticketflow:ticketflow@localhost:5432/ticketflow"

    secret_key: str = "change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    reservation_minutes: int = 10
    max_tickets_per_order: int = 10
    run_expiry_task: bool = True

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

    payment_provider: str = "mock"  # "mock" or "paystack"
    paystack_secret_key: str = ""
    currency: str = "NGN"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
