"""App settings, read from environment variables or the .env file.

pydantic-settings matches each field to an env var with the same name
(case-insensitive), e.g. JWT_SECRET_KEY -> jwt_secret_key. If neither is set,
the default below is used. A field with no default is required: the app
refuses to start without it.
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "KaasuPay Loan Portal"
    environment: str = "local"

    database_url: str = "sqlite:///./kaasupay.db"

    # No default on purpose: a secret must come from .env, never from the code.
    jwt_secret_key: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    cookie_secure: bool = False

    seed_staff_password: str = "Staff@Demo123"


# One shared settings object for the whole app.
settings = Settings()
