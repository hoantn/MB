from __future__ import annotations
from typing import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

from core.logger import log
from db.database import get_connection


@dataclass
class PlayerRow:
    uid: str
    name_last: str
    meet_times: int
    first_seen: str
    last_seen: str
    last_gold: Optional[int]
    top_bet: Optional[int]
    top_profile: Optional[str]


def _normalize_search(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = str(s).strip()
    return s if s else None


def _calc_since_iso(time_filter: str) -> Optional[str]:
    """
    time_filter: "ALL" | "24H" | "7D" | "30D"
    DB đang lưu ISO UTC (datetime.utcnow().isoformat()).
    """
    now = datetime.utcnow()
    if time_filter == "24H":
        return (now - timedelta(hours=24)).isoformat()
    if time_filter == "7D":
        return (now - timedelta(days=7)).isoformat()
    if time_filter == "30D":
        return (now - timedelta(days=30)).isoformat()
    return None


def list_distinct_bets() -> List[int]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT bet FROM room_sessions WHERE bet IS NOT NULL ORDER BY bet ASC")
    rows = cur.fetchall()
    out: List[int] = []
    for r in rows:
        try:
            out.append(int(r[0]))
        except Exception:
            pass
    return out


def get_player_history(uid: str, limit: int = 20) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
          rps.last_seen_at,
          rs.profile_id,
          rs.bet,
          rs.room_id,
          rps.seen_name,
          rps.seen_gold
        FROM room_players_seen rps
        JOIN room_sessions rs ON rs.id = rps.session_id
        WHERE rps.seen_uid = ?
        ORDER BY rps.last_seen_at DESC
        LIMIT ?
        """,
        (uid, int(limit)),
    )
    rows = cur.fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "last_seen_at": r[0],
                "profile_id": r[1],
                "bet": r[2],
                "room_id": r[3],
                "seen_name": r[4],
                "seen_gold": r[5],
            }
        )
    return out


def get_top_bets(uid: str, limit: int = 3) -> List[Tuple[Optional[int], int]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT rs.bet, COUNT(*) AS c
        FROM room_players_seen rps
        JOIN room_sessions rs ON rs.id = rps.session_id
        WHERE rps.seen_uid = ?
        GROUP BY rs.bet
        ORDER BY c DESC
        LIMIT ?
        """,
        (uid, int(limit)),
    )
    rows = cur.fetchall()
    out: List[Tuple[Optional[int], int]] = []
    for r in rows:
        out.append((r[0], int(r[1])))
    return out


def get_top_profiles(uid: str, limit: int = 3) -> List[Tuple[Optional[str], int]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT rs.profile_id, COUNT(*) AS c
        FROM room_players_seen rps
        JOIN room_sessions rs ON rs.id = rps.session_id
        WHERE rps.seen_uid = ?
        GROUP BY rs.profile_id
        ORDER BY c DESC
        LIMIT ?
        """,
        (uid, int(limit)),
    )
    rows = cur.fetchall()
    out: List[Tuple[Optional[str], int]] = []
    for r in rows:
        out.append((r[0], int(r[1])))
    return out


def list_players_aggregated(
    search: Optional[str],
    profile_id: Optional[str],
    bet: Optional[int],
    time_filter: str,
    limit: int,
    offset: int,
) -> List[PlayerRow]:
    """
    Danh sách tổng hợp theo UID:
      - meet_times = COUNT DISTINCT session_id
      - last_gold = MAX(seen_gold) (v1, đủ dùng)
      - top_bet / top_profile: tính bằng subquery nhỏ (nhẹ, vì limit/offset đã giới hạn)
    """
    search = _normalize_search(search)
    since_iso = _calc_since_iso(time_filter)

    # LIKE param
    like = None
    if search:
        like = f"%{search}%"

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
          rps.seen_uid AS uid,
          COALESCE(MAX(rps.seen_name), '') AS name_last,
          COUNT(
            DISTINCT
            (COALESCE(CAST(rs.room_id AS TEXT), rs.my_uid, '0') || ':' || CAST(COALESCE(rs.bet, 0) AS TEXT) || ':' || SUBSTR(rs.started_at, 1, 16))
          ) AS meet_times,
          MIN(rps.first_seen_at) AS first_seen,
          MAX(rps.last_seen_at) AS last_seen,
          MAX(rps.seen_gold) AS last_gold
        FROM room_players_seen rps
        JOIN room_sessions rs ON rs.id = rps.session_id
        WHERE
          (? IS NULL OR rs.profile_id = ?)
          AND (? IS NULL OR rs.bet = ?)
          AND (? IS NULL OR rps.last_seen_at >= ?)
          AND (
              ? IS NULL
              OR rps.seen_uid LIKE ?
              OR rps.seen_name LIKE ?
          )
        GROUP BY rps.seen_uid
        ORDER BY meet_times DESC, last_seen DESC
        LIMIT ? OFFSET ?
        """,
        (
            profile_id,
            profile_id,
            bet,
            bet,
            since_iso,
            since_iso,
            like,
            like,
            like,
            int(limit),
            int(offset),
        ),
    )

    rows = cur.fetchall()

    out: List[PlayerRow] = []
    for r in rows:
        uid = str(r[0] or "")
        name_last = str(r[1] or "")
        meet_times = int(r[2] or 0)
        first_seen = str(r[3] or "")
        last_seen = str(r[4] or "")
        last_gold = r[5]
        try:
            last_gold = int(last_gold) if last_gold is not None else None
        except Exception:
            last_gold = None

        # top bet/profile (nhẹ vì chỉ chạy cho số row trên 1 page)
        top_bet = None
        try:
            tb = get_top_bets(uid, limit=1)
            if tb:
                top_bet = tb[0][0]
        except Exception:
            pass

        top_profile = None
        try:
            tp = get_top_profiles(uid, limit=1)
            if tp:
                top_profile = tp[0][0]
        except Exception:
            pass

        out.append(
            PlayerRow(
                uid=uid,
                name_last=name_last,
                meet_times=meet_times,
                first_seen=first_seen,
                last_seen=last_seen,
                last_gold=last_gold,
                top_bet=top_bet,
                top_profile=top_profile,
            )
        )

    return out

def get_meet_counts_for_uids(uids: Iterable[str]) -> Dict[str, int]:
    """
    Trả về dict {uid: meet_times}.
    meet_times = COUNT DISTINCT theo encounter key (room_id + bet + started_at theo phút),
    để coi 3P là 1 khi cùng bàn.
    """

    uids = [str(u or "").strip() for u in (uids or [])]
    uids = [u for u in uids if u]
    if not uids:
        return {}

    conn = get_connection()
    cur = conn.cursor()

    placeholders = ",".join(["?"] * len(uids))
    cur.execute(
        f"""
        SELECT
          rps.seen_uid,
          COUNT(
            DISTINCT
            (COALESCE(CAST(rs.room_id AS TEXT), rs.my_uid, '0') || ':' || CAST(COALESCE(rs.bet, 0) AS TEXT) || ':' || SUBSTR(rs.started_at, 1, 16))
          ) AS c
        FROM room_players_seen rps
        JOIN room_sessions rs ON rs.id = rps.session_id
        WHERE rps.seen_uid IN ({placeholders})
        GROUP BY rps.seen_uid
        """,
        tuple(uids),
    )
    rows = cur.fetchall()

    out: Dict[str, int] = {u: 0 for u in uids}
    for r in rows:
        uid = str(r[0] or "").strip()
        try:
            out[uid] = int(r[1] or 0)
        except Exception:
            out[uid] = 0
    return out
