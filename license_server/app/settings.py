from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Auto-load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


class Settings(BaseSettings):
    app_env: str = "dev"
    sqlite_path: str = "dev_license.sqlite3"
    license_key_pepper: str = "CHANGE_ME_NOW"
    license_product_id: str = "mb-auto"

    # admin web session secret (cookie signing)
    admin_session_secret: str = ""

    # admin credentials (prefer bcrypt hash)
    admin_username: str = "admin"
    admin_password_hash: str = ""  # env: ADMIN_PASSWORD_HASH

    # signing seed (prefer HEX)
    ed25519_seed_hex: str = ""   # env: ED25519_SEED_HEX
    ed25519_seed_b64: str = ""   # env: ED25519_SEED_B64

    class Config:
        env_prefix = ""
        case_sensitive = False


settings = Settings()
