from datetime import datetime
from typing import List
from .database import get_connection
from core.logger import log
from engine.card import Card

def insert_round(profile: str, cards: List[Card],
                 chi1: List[Card], chi2: List[Card], chi3: List[Card],
                 total_score: int, note: str = "") -> None:
    conn = get_connection()
    cur = conn.cursor()

    cards_raw = ",".join(c.to_code() for c in cards)
    chi1_str = ",".join(c.to_code() for c in chi1)
    chi2_str = ",".join(c.to_code() for c in chi2)
    chi3_str = ",".join(c.to_code() for c in chi3)

    cur.execute(
        """
        INSERT INTO rounds (profile, timestamp, cards_raw, chi1, chi2, chi3, total_score, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            profile,
            datetime.utcnow().isoformat(),
            cards_raw,
            chi1_str,
            chi2_str,
            chi3_str,
            total_score,
            note,
        ),
    )
    conn.commit()
    log.info("Inserted round for profile %s", profile)

def get_rounds(limit: int = 50):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, profile, timestamp, cards_raw, chi1, chi2, chi3, total_score, note "
        "FROM rounds ORDER BY id DESC LIMIT ?", (limit,)
    )
    return cur.fetchall()

# ================== ROOM HISTORY ==================

def start_room_session(profile_id: str, room_id: int | None,
                       bet: int | None, my_uid: str | None) -> int:
    """
    Mở 1 phiên phòng mới.
    Trả về session_id.
    """
    conn = get_connection()
    cur = conn.cursor()

    now = datetime.utcnow().isoformat()

    cur.execute(
        """
        INSERT INTO room_sessions
        (profile_id, room_id, bet, my_uid, started_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (profile_id, room_id, bet, my_uid, now),
    )
    conn.commit()

    session_id = cur.lastrowid
    log.info("Start room session %s for %s", session_id, profile_id)
    return session_id


def end_room_session(session_id: int) -> None:
    """
    Đóng phiên phòng.
    """
    conn = get_connection()
    cur = conn.cursor()

    now = datetime.utcnow().isoformat()

    cur.execute(
        """
        UPDATE room_sessions
        SET ended_at = ?
        WHERE id = ?
        """,
        (now, session_id),
    )
    conn.commit()
    log.info("End room session %s", session_id)


def upsert_room_player_seen(session_id: int, uid: str, name: str | None, gold: int | None) -> None:
    """
    Ghi nhận 1 UID đã xuất hiện trong phiên phòng.
    Lưu thêm vàng (seen_gold) nếu có.
    """
    conn = get_connection()
    cur = conn.cursor()

    now = datetime.utcnow().isoformat()

    cur.execute(
        """
        INSERT INTO room_players_seen
        (session_id, seen_uid, seen_name, first_seen_at, last_seen_at, seen_gold)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id, seen_uid)
        DO UPDATE SET
            seen_name = excluded.seen_name,
            last_seen_at = excluded.last_seen_at,
            seen_gold = COALESCE(excluded.seen_gold, room_players_seen.seen_gold)
        """,
        (session_id, uid, name, now, now, gold),
    )
    conn.commit()
    
def delete_room_player_seen_by_uid(uid: str) -> None:
    uid = str(uid or "").strip()
    if not uid:
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM room_players_seen WHERE seen_uid = ?", (uid,))
    conn.commit()

