from __future__ import annotations

import sys
import secrets
import string
from datetime import datetime, timedelta
from uuid import uuid4
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.settings import settings  # noqa: E402
from app.models import Base, License  # noqa: E402
from app.security import HashingConfig, hash_license_key  # noqa: E402

ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits


def gen_key_15() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(15))


def main():
    # ALWAYS match API settings
    pepper = settings.license_key_pepper
    sqlite_path = settings.sqlite_path
    days = 30

    db_url = f"sqlite:///{sqlite_path}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False}, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(bind=engine)

    cfg = HashingConfig(pepper=pepper)

    with SessionLocal() as db:
        for _ in range(100):
            key = gen_key_15()
            key_hash = hash_license_key(key, cfg)

            exists = db.execute(select(License).where(License.key_hash == key_hash)).scalar_one_or_none()
            if exists is None:
                lic = License(
                    id=str(uuid4()),
                    key_hash=key_hash,
                    status="active",
                    expires_at=datetime.utcnow() + timedelta(days=days),  # DEV SQLite naive UTC
                    device_limit=1,
                    session_limit=1,
                    offline_grace_hours=72,
                )
                db.add(lic)
                db.commit()

                print("DB:", sqlite_path)
                print("PEPPER_PREFIX:", (pepper or "")[:6])
                print("KEY:", key)
                print("LICENSE_ID:", lic.id)
                print("EXPIRES_AT_UTC:", lic.expires_at.isoformat())
                return

        raise RuntimeError("Failed to generate unique key after many attempts")


if __name__ == "__main__":
    main()
