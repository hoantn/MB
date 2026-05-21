from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, Optional


def _default_db_path() -> str:
    """
    Trả về path tuyệt đối của file DB ở thư mục gốc project.

    File này thường nằm tại:
        ui2/bridge/taixiu_store.py

    => đi lên 3 cấp để ra thư mục gốc project.
    """
    here = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(project_root, "taixiu_history.sqlite3")


class TaiXiuStore:
    """
    Store duy nhất cho dữ liệu Tài/Xỉu.

    Mục tiêu:
    - 1 schema mới thống nhất
    - path DB tuyệt đối
    - có đủ:
        + tx_rounds
        + tx_user_bets
        + tx_round_packets
    - có API lưu round, lưu bet, settle win/lose
    - giữ tương thích với vài API cũ để tránh gãy hệ thống
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or _default_db_path()
        self._lock = threading.RLock()
        self.init_db()

    # ==========================================================
    # Low-level
    # ==========================================================

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=30,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _now(self) -> int:
        return int(time.time())

    def _to_json_text(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)

    # ==========================================================
    # Schema
    # ==========================================================

    def init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.cursor()

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tx_rounds (
                        game_type TEXT NOT NULL,
                        sid TEXT NOT NULL,

                        profile_id_first_seen TEXT,
                        profile_id_last_seen TEXT,

                        game_state INTEGER,
                        remain_time_ms INTEGER,

                        dice_1 INTEGER,
                        dice_2 INTEGER,
                        dice_3 INTEGER,
                        total INTEGER,
                        result_side TEXT,
                        is_triple INTEGER DEFAULT 0,

                        md5_hash TEXT,

                        tai_total_bet INTEGER DEFAULT 0,
                        xiu_total_bet INTEGER DEFAULT 0,
                        tai_total_users INTEGER DEFAULT 0,
                        xiu_total_users INTEGER DEFAULT 0,

                        result_cmd INTEGER,
                        totals_cmd INTEGER,

                        first_seen_at INTEGER,
                        last_seen_at INTEGER,
                        is_final INTEGER DEFAULT 0,

                        raw_last_json TEXT,

                        PRIMARY KEY (game_type, sid)
                    )
                    """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tx_user_bets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        game_type TEXT NOT NULL,
                        sid TEXT NOT NULL,
                        profile_id TEXT NOT NULL,
                        bet_side TEXT,
                        bet_amount INTEGER,
                        eid_raw TEXT,
                        source_cmd INTEGER,
                        created_at INTEGER,
                        is_win INTEGER,
                        settled_at INTEGER
                    )
                    """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tx_round_packets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        game_type TEXT NOT NULL,
                        sid TEXT,
                        profile_id TEXT NOT NULL,
                        cmd INTEGER,
                        payload_json TEXT NOT NULL,
                        created_at INTEGER
                    )
                    """
                )

                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tx_rounds_sid ON tx_rounds(sid)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tx_user_bets_sid ON tx_user_bets(sid)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tx_round_packets_sid ON tx_round_packets(sid)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tx_rounds_last_seen ON tx_rounds(last_seen_at)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tx_user_bets_created ON tx_user_bets(created_at)"
                )

                conn.commit()
            finally:
                conn.close()

    # ==========================================================
    # Packet log
    # ==========================================================

    def save_packet(
        self,
        game_type: str,
        sid: Optional[str],
        profile_id: str,
        cmd: Optional[int],
        payload: Dict[str, Any],
    ) -> None:
        """
        Hiện tại tắt ghi raw packet để tránh:
        - đơ UI
        - phình DB
        - insert/commit quá dày

        Khi cần debug sâu có thể bật lại.
        """
        return

    # ==========================================================
    # Round upsert
    # ==========================================================

    def upsert_round(self, game_type: str, sid: str, updates: Dict[str, Any]) -> None:
        """
        Upsert 1 phiên theo (game_type, sid).

        Chỉ ghi đè field nào có dữ liệu mới.
        """
        if not sid:
            return

        now_ts = self._now()

        with self._lock:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT * FROM tx_rounds WHERE game_type=? AND sid=?",
                    (str(game_type), str(sid)),
                )
                row = cur.fetchone()

                if row is None:
                    data = {
                        "game_type": str(game_type),
                        "sid": str(sid),
                        "profile_id_first_seen": updates.get("profile_id_first_seen"),
                        "profile_id_last_seen": updates.get("profile_id_last_seen"),
                        "game_state": updates.get("game_state"),
                        "remain_time_ms": updates.get("remain_time_ms"),
                        "dice_1": updates.get("dice_1"),
                        "dice_2": updates.get("dice_2"),
                        "dice_3": updates.get("dice_3"),
                        "total": updates.get("total"),
                        "result_side": updates.get("result_side"),
                        "is_triple": int(updates.get("is_triple", 0) or 0),
                        "md5_hash": updates.get("md5_hash"),
                        "tai_total_bet": int(updates.get("tai_total_bet", 0) or 0),
                        "xiu_total_bet": int(updates.get("xiu_total_bet", 0) or 0),
                        "tai_total_users": int(updates.get("tai_total_users", 0) or 0),
                        "xiu_total_users": int(updates.get("xiu_total_users", 0) or 0),
                        "result_cmd": updates.get("result_cmd"),
                        "totals_cmd": updates.get("totals_cmd"),
                        "first_seen_at": int(updates.get("first_seen_at") or now_ts),
                        "last_seen_at": int(updates.get("last_seen_at") or now_ts),
                        "is_final": int(updates.get("is_final", 0) or 0),
                        "raw_last_json": self._to_json_text(updates.get("raw_last_json")),
                    }

                    cur.execute(
                        """
                        INSERT INTO tx_rounds(
                            game_type, sid,
                            profile_id_first_seen, profile_id_last_seen,
                            game_state, remain_time_ms,
                            dice_1, dice_2, dice_3, total, result_side, is_triple,
                            md5_hash,
                            tai_total_bet, xiu_total_bet, tai_total_users, xiu_total_users,
                            result_cmd, totals_cmd,
                            first_seen_at, last_seen_at, is_final, raw_last_json
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            data["game_type"],
                            data["sid"],
                            data["profile_id_first_seen"],
                            data["profile_id_last_seen"],
                            data["game_state"],
                            data["remain_time_ms"],
                            data["dice_1"],
                            data["dice_2"],
                            data["dice_3"],
                            data["total"],
                            data["result_side"],
                            data["is_triple"],
                            data["md5_hash"],
                            data["tai_total_bet"],
                            data["xiu_total_bet"],
                            data["tai_total_users"],
                            data["xiu_total_users"],
                            data["result_cmd"],
                            data["totals_cmd"],
                            data["first_seen_at"],
                            data["last_seen_at"],
                            data["is_final"],
                            data["raw_last_json"],
                        ),
                    )
                else:
                    merged = dict(row)

                    overwrite_keys = {
                        "profile_id_last_seen",
                        "game_state",
                        "remain_time_ms",
                        "dice_1",
                        "dice_2",
                        "dice_3",
                        "total",
                        "result_side",
                        "is_triple",
                        "md5_hash",
                        "tai_total_bet",
                        "xiu_total_bet",
                        "tai_total_users",
                        "xiu_total_users",
                        "result_cmd",
                        "totals_cmd",
                        "is_final",
                        "raw_last_json",
                    }

                    for key, value in updates.items():
                        if value is None:
                            continue

                        if key == "profile_id_first_seen":
                            if not merged.get("profile_id_first_seen"):
                                merged["profile_id_first_seen"] = value
                            continue

                        if key in overwrite_keys:
                            if key in {
                                "tai_total_bet",
                                "xiu_total_bet",
                                "tai_total_users",
                                "xiu_total_users",
                                "is_triple",
                                "is_final",
                            }:
                                merged[key] = int(value or 0)
                            elif key == "raw_last_json":
                                merged[key] = self._to_json_text(value)
                            else:
                                merged[key] = value

                    merged["last_seen_at"] = now_ts

                    cur.execute(
                        """
                        UPDATE tx_rounds
                        SET profile_id_first_seen=?,
                            profile_id_last_seen=?,
                            game_state=?,
                            remain_time_ms=?,
                            dice_1=?,
                            dice_2=?,
                            dice_3=?,
                            total=?,
                            result_side=?,
                            is_triple=?,
                            md5_hash=?,
                            tai_total_bet=?,
                            xiu_total_bet=?,
                            tai_total_users=?,
                            xiu_total_users=?,
                            result_cmd=?,
                            totals_cmd=?,
                            last_seen_at=?,
                            is_final=?,
                            raw_last_json=?
                        WHERE game_type=? AND sid=?
                        """,
                        (
                            merged.get("profile_id_first_seen"),
                            merged.get("profile_id_last_seen"),
                            merged.get("game_state"),
                            merged.get("remain_time_ms"),
                            merged.get("dice_1"),
                            merged.get("dice_2"),
                            merged.get("dice_3"),
                            merged.get("total"),
                            merged.get("result_side"),
                            int(merged.get("is_triple", 0) or 0),
                            merged.get("md5_hash"),
                            int(merged.get("tai_total_bet", 0) or 0),
                            int(merged.get("xiu_total_bet", 0) or 0),
                            int(merged.get("tai_total_users", 0) or 0),
                            int(merged.get("xiu_total_users", 0) or 0),
                            merged.get("result_cmd"),
                            merged.get("totals_cmd"),
                            int(merged.get("last_seen_at") or now_ts),
                            int(merged.get("is_final", 0) or 0),
                            self._to_json_text(merged.get("raw_last_json")),
                            str(game_type),
                            str(sid),
                        ),
                    )

                conn.commit()
            finally:
                conn.close()

    # ==========================================================
    # User bet
    # ==========================================================

    def save_user_bet(
        self,
        game_type: str,
        sid: str,
        profile_id: str,
        bet_side: Optional[str],
        bet_amount: int,
        eid_raw: Optional[str] = None,
        source_cmd: Optional[int] = None,
    ) -> None:
        """
        Lưu 1 bản ghi cược user.

        Có chống trùng mềm trong 2 giây:
        - cùng game_type
        - cùng sid
        - cùng profile_id
        - cùng bet_side
        - cùng bet_amount
        - cùng eid_raw
        - cùng source_cmd
        """
        if not sid:
            return

        now_ts = self._now()
        dedupe_window_sec = 2

        with self._lock:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT id, created_at
                    FROM tx_user_bets
                    WHERE game_type = ?
                      AND sid = ?
                      AND profile_id = ?
                      AND COALESCE(bet_side, '') = COALESCE(?, '')
                      AND bet_amount = ?
                      AND COALESCE(eid_raw, '') = COALESCE(?, '')
                      AND COALESCE(source_cmd, -1) = COALESCE(?, -1)
                      AND created_at >= ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (
                        str(game_type or "normal"),
                        str(sid),
                        str(profile_id),
                        bet_side,
                        int(bet_amount or 0),
                        str(eid_raw) if eid_raw is not None else None,
                        int(source_cmd) if source_cmd is not None else None,
                        now_ts - dedupe_window_sec,
                    ),
                )
                existed = cur.fetchone()
                if existed is not None:
                    return

                conn.execute(
                    """
                    INSERT INTO tx_user_bets(
                        game_type, sid, profile_id, bet_side, bet_amount,
                        eid_raw, source_cmd, created_at, is_win, settled_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        str(game_type or "normal"),
                        str(sid),
                        str(profile_id),
                        bet_side,
                        int(bet_amount or 0),
                        str(eid_raw) if eid_raw is not None else None,
                        int(source_cmd) if source_cmd is not None else None,
                        now_ts,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def settle_user_bets(self, game_type: str, sid: str, result_side: str) -> None:
        """
        Chốt thắng/thua cho toàn bộ bet của 1 phiên.
        """
        if not sid:
            return

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    UPDATE tx_user_bets
                    SET is_win = CASE
                        WHEN bet_side = ? THEN 1
                        WHEN bet_side IS NULL THEN NULL
                        ELSE 0
                    END,
                    settled_at = ?
                    WHERE game_type = ? AND sid = ?
                    """,
                    (
                        result_side,
                        self._now(),
                        str(game_type or "normal"),
                        str(sid),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def save_result_from_dice(
        self,
        game_type: str,
        sid: str,
        profile_id: str,
        d1: int,
        d2: int,
        d3: int,
        result_cmd: Optional[int] = None,
        game_state: Optional[int] = None,
        remain_time_ms: Optional[int] = None,
        raw_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Helper lưu kết quả phiên trực tiếp từ 3 viên xúc xắc.
        """
        total = int(d1) + int(d2) + int(d3)
        result_side = "tai" if total >= 11 else "xiu"
        is_triple = 1 if int(d1) == int(d2) == int(d3) else 0

        self.upsert_round(
            game_type=game_type,
            sid=sid,
            updates={
                "profile_id_first_seen": profile_id,
                "profile_id_last_seen": profile_id,
                "game_state": game_state,
                "remain_time_ms": remain_time_ms,
                "dice_1": int(d1),
                "dice_2": int(d2),
                "dice_3": int(d3),
                "total": total,
                "result_side": result_side,
                "is_triple": is_triple,
                "result_cmd": result_cmd,
                "is_final": 1,
                "raw_last_json": raw_payload or {},
            },
        )
        self.settle_user_bets(
            game_type=game_type,
            sid=sid,
            result_side=result_side,
        )

    # ==========================================================
    # Backward-compatible API
    # ==========================================================

    def save_round_totals(self, sid: str, tai: int, xiu: int, profile_id: str = "P1") -> None:
        """
        API cũ: lưu tổng tiền 2 cửa.
        """
        self.upsert_round(
            game_type="normal",
            sid=str(sid),
            updates={
                "profile_id_first_seen": profile_id,
                "profile_id_last_seen": profile_id,
                "tai_total_bet": int(tai or 0),
                "xiu_total_bet": int(xiu or 0),
                "totals_cmd": 10003,
            },
        )

    def update_result(self, sid: str, result: str, profile_id: str = "P1") -> None:
        """
        API cũ: chỉ update result_side.
        """
        self.upsert_round(
            game_type="normal",
            sid=str(sid),
            updates={
                "profile_id_first_seen": profile_id,
                "profile_id_last_seen": profile_id,
                "result_side": result,
                "is_final": 1,
            },
        )
        self.settle_user_bets(
            game_type="normal",
            sid=str(sid),
            result_side=result,
        )

    def save_user_bet_legacy(self, sid: str, profile_id: str, side: str, amount: int) -> None:
        """
        Tương thích code cũ nếu còn dùng tên hàm cũ.
        """
        self.save_user_bet(
            game_type="normal",
            sid=str(sid),
            profile_id=str(profile_id),
            bet_side=side,
            bet_amount=int(amount or 0),
            eid_raw=None,
            source_cmd=None,
        )
        
    def get_round_by_sid(self, game_type: str, sid: str) -> Optional[dict]:
        if not sid:
            return None

        with self._lock:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT *
                    FROM tx_rounds
                    WHERE game_type = ? AND sid = ?
                    LIMIT 1
                    """,
                    (str(game_type or "normal"), str(sid)),
                )
                row = cur.fetchone()
                return dict(row) if row is not None else None
            finally:
                conn.close()

    def get_latest_round(self, game_type: str = "normal") -> Optional[dict]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT *
                    FROM tx_rounds
                    WHERE game_type = ?
                    ORDER BY last_seen_at DESC, sid DESC
                    LIMIT 1
                    """,
                    (str(game_type or "normal"),),
                )
                row = cur.fetchone()
                return dict(row) if row is not None else None
            finally:
                conn.close()

    def get_recent_final_rounds(self, game_type: str = "normal", limit: int = 200) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT *
                    FROM tx_rounds
                    WHERE game_type = ?
                      AND is_final = 1
                      AND result_side IN ('tai', 'xiu')
                    ORDER BY last_seen_at ASC, sid ASC
                    LIMIT ?
                    """,
                    (str(game_type or "normal"), int(limit)),
                )
                return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()
    # ==========================================================
    # Debug query helpers
    # ==========================================================

    def fetch_latest_rounds(self, limit: int = 20) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT *
                    FROM tx_rounds
                    ORDER BY last_seen_at DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                )
                return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

    def fetch_latest_packets(self, limit: int = 50) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT *
                    FROM tx_round_packets
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                )
                return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

    def fetch_latest_user_bets(self, limit: int = 50) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT *
                    FROM tx_user_bets
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                )
                return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()


# ==============================================================
# Singleton dùng chung toàn hệ thống
# ==============================================================
tx_store = TaiXiuStore()