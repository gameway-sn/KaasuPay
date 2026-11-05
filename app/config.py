"""App settings, read from environment variables or the .env file.

pydantic-settings matches each field to an env var with the same name
(case-insensitive), e.g. JWT_SECRET_KEY -> jwt_secret_key. If neither is set,
the default below is used. A field with no default is required: the app
refuses to start without it.
"""
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The project folder (the one that holds app/, tests/, uploads/).
PROJECT_DIR = Path(__file__).resolve().parent.parent


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

    # Encrypts Aadhaar numbers in the database. Also secret, also no default.
    fernet_key: str

    # KYC uploads. Outside app/static, so the web server never serves them directly.
    upload_dir: Path = PROJECT_DIR / "uploads"

    seed_staff_password: str = "Staff@Demo123"

    @field_validator("fernet_key")
    @classmethod
    def fernet_key_is_valid(cls, value: str) -> str:
        try:
            Fernet(value)
        except ValueError:
            raise ValueError(
                "FERNET_KEY is not a valid Fernet key. Make one with: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            ) from None
        return value


# One shared settings object for the whole app.
settings = Settings()
