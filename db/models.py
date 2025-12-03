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
