# kendz/database/db_session.py
"""Khởi tạo kết nối SQLite local cho Kendz.

Nhiệm vụ:
- Tạo engine SQLite trỏ tới file `data/kendz.db`
- Cung cấp SessionLocal (sessionmaker) cho toàn hệ thống
- Hàm init_db() để tạo toàn bộ bảng nếu chưa tồn tại

Lưu ý:
- Tầng DB chỉ xử lý kết nối và transaction, không chứa logic nghiệp vụ.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kendz.database.models import Base


def get_db_path() -> Path:
    """Trả về đường dẫn file SQLite local của Kendz.

    Mặc định:
    - data/kendz.db (tạo thư mục data nếu chưa có)
    """
    project_root = Path(__file__).resolve().parents[2]
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "kendz.db"


def create_engine_sqlite(echo: bool = False):
    """Tạo SQLAlchemy Engine cho SQLite.

    Tham số:
    - echo: nếu True sẽ in ra toàn bộ câu SQL (chỉ nên bật khi debug)
    """
    db_path = get_db_path()
    url = f"sqlite:///{db_path}"
    engine = create_engine(
        url,
        echo=echo,
        future=True,
    )
    return engine


# Engine và SessionLocal sẽ được khởi tạo một lần khi AppContext bootstrap
engine = create_engine_sqlite(echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Tạo toàn bộ bảng trong database nếu chưa tồn tại.

    Hàm này nên được gọi đúng 1 lần lúc khởi động ứng dụng.
    """
    Base.metadata.create_all(bind=engine)
