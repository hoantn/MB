# kendz/core/app_context.py
"""AppContext: chứa toàn bộ ngữ cảnh dùng chung cho Kendz.

Phase 1:
- Gom config, logger, event_bus.

Phase 2:
- Bổ sung database (SQLite local) với SessionLocal để các module khác sử dụng.

Mục tiêu:
- Tập trung tất cả "tài nguyên lõi" vào một chỗ, truyền đi đâu cũng gọn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kendz import __app_name__, __version__
from kendz.core.config_loader import KendzConfig, load_kendz_config
from kendz.core.logging_setup import create_logger
from kendz.core.events import EventBus
from kendz.database.db_session import SessionLocal, init_db


@dataclass
class AppContext:
    """Ngữ cảnh ứng dụng Kendz.

    Thuộc tính:
    - app_name: tên ứng dụng
    - app_version: phiên bản
    - config: toàn bộ cấu hình Kendz (KendzConfig)
    - logger: logger chuẩn
    - event_bus: bus event nội bộ
    - db_session_factory: sessionmaker để tạo session làm việc với DB
    """

    app_name: str
    app_version: str
    config: KendzConfig
    logger: Any
    event_bus: EventBus
    db_session_factory: Any  # sqlalchemy.orm.sessionmaker

    @classmethod
    def bootstrap(cls) -> "AppContext":
        """Khởi tạo toàn bộ AppContext cho Kendz.

        Các bước:
        1. Load config
        2. Tạo logger
        3. Khởi tạo EventBus
        4. Khởi tạo database local (SQLite) và session factory

        Hàm này được gọi ở entry point (main.py) đúng 1 lần.
        """
        config = load_kendz_config()
        logger = create_logger(app_name=__app_name__, log_level=config.core.log_level)
        event_bus = EventBus()

        # Khởi tạo database local
        init_db()
        logger.info("Database local (SQLite) đã được khởi tạo.")

        db_session_factory = SessionLocal

        logger.info("Khởi tạo AppContext thành công.")

        return cls(
            app_name=__app_name__,
            app_version=__version__,
            config=config,
            logger=logger,
            event_bus=event_bus,
            db_session_factory=db_session_factory,
        )
