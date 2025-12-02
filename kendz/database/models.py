# kendz/database/models.py
"""Định nghĩa các model (ORM) cho SQLite local của Kendz.

Mục tiêu:
- Lưu lại thông tin session chơi, từng ván (round), từng hand và log event.
- Phục vụ cho:
  + Debug
  + Phân tích dữ liệu
  + Huấn luyện AI sau này

Lưu ý:
- Chỉ chứa cấu trúc bảng, không chứa logic nghiệp vụ.
- Mọi thay đổi schema về sau nên có migration (alembic),
  nhưng giai đoạn đầu có thể create_all đơn giản.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class cho tất cả ORM model của Kendz."""
    pass


class SessionModel(Base):
    """Bảng `sessions` - đại diện cho một phiên chạy Kendz.

    Một session bắt đầu khi người dùng mở tool Kendz
    và kết thúc khi người dùng tắt tool (hoặc sau một khoảng idle).

    Các trường chính:
    - id: khóa chính
    - started_at / ended_at: thời gian bắt đầu / kết thúc
    - client_version: version tool tại thời điểm đó
    - license_key: (để sau này map với license server nếu cần)
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    client_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    license_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    rounds: Mapped[list["RoundModel"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class RoundModel(Base):
    """Bảng `rounds` - đại diện cho một ván chơi.

    Một session sẽ có nhiều round.

    Các trường chính:
    - game_id: mã game (vd: 'mau_binh_siteA')
    - table_id: mã bàn/phòng nếu đọc được
    - round_index: thứ tự ván trong session
    - result_status: trạng thái (completed / aborted / timeout / error)
    - error_code: mã lỗi (nếu có)
    """

    __tablename__ = "rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    game_id: Mapped[str] = mapped_column(String(64), nullable=False)
    table_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    round_index: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    result_status: Mapped[str] = mapped_column(String(32), default="pending")
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    session: Mapped["SessionModel"] = relationship(back_populates="rounds")
    hands: Mapped[list["HandModel"]] = relationship(
        back_populates="round", cascade="all, delete-orphan"
    )


class HandModel(Base):
    """Bảng `hands` - lưu thông tin bài của từng profile trong một round.

    Một round có thể có:
    - 3 hand dành cho 3 profile Kendz
    - 1 hand cho đối thủ (is_opponent = True) nếu suy luận được bài đối thủ

    Các trường chính:
    - profile_id: id profile (1,2,3) hoặc None nếu là đối thủ
    - is_opponent: đánh dấu hand thuộc về đối thủ hay không
    - raw_cards_str: 13 lá gốc, dạng text 'AS,KH,7D,...'
    - arranged_chi1/2/3: 3 chi sau khi xếp
    - is_lung: có bị binh lủng không
    - special_type: loại bài đặc biệt (6 đôi, 3 sảnh, mậu binh...)
    - strategy_mode: safe / balance / aggressive / fallback
    - engine_used: engine nào được dùng (vd: 'basic', 'multi_opt', 'ai_v1')
    - decision_time_ms: thời gian (ms) để quyết định xếp bài
    """

    __tablename__ = "hands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), nullable=False)

    profile_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_opponent: Mapped[bool] = mapped_column(Boolean, default=False)

    raw_cards_str: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    arranged_chi1: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    arranged_chi2: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    arranged_chi3: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_lung: Mapped[bool] = mapped_column(Boolean, default=False)
    special_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    strategy_mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    engine_used: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    decision_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    round: Mapped["RoundModel"] = relationship(back_populates="hands")


class LogEventModel(Base):
    """Bảng `log_events` - log sự kiện dạng cấu trúc.

    Lưu ý:
    - Đây là log ở mức "vừa", không phải mọi debug nhỏ.
    - Dùng để phân tích sau này, ví dụ:
      + Vision lỗi bao nhiêu lần
      + Automation fail bao nhiêu lần
    """

    __tablename__ = "log_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sessions.id"), nullable=True
    )
    round_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("rounds.id"), nullable=True
    )
    profile_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    module: Mapped[str] = mapped_column(String(64))  # vd: 'vision', 'engine', 'automation'
    level: Mapped[str] = mapped_column(String(16))   # DEBUG / INFO / WARNING / ERROR
    event_type: Mapped[str] = mapped_column(String(64))  # vd: 'capture_start', 'arrange_done'

    message: Mapped[str] = mapped_column(Text)
    context_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
