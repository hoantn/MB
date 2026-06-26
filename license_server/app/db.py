from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .settings import settings

DB_URL = f"sqlite:///{settings.sqlite_path}"

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
