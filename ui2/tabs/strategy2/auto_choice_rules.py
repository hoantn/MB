from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable, Optional, Sequence, Tuple

from core.logger import log
from db.database import get_connection
from .auto_choice_similarity import (
    combined_similarity,
    extract_hand_features,
    extract_suggestion_features,
)


DEFAULT_SCOPE = "global"
RULES_TABLE = "auto_choice_rules"
SETTINGS_TABLE = "auto_choice_settings"
DEFAULT_SIMILARITY_ENABLED = True
DEFAULT_SIMILARITY_THRESHOLD = 80


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def normalize_codes_key(codes: Sequence[str]) -> str:
    values = [str(c).strip().upper() for c in list(codes or []) if str(c).strip()]
    if len(values) != 13:
        return ""
    return ",".join(sorted(values))


def split_key_from_suggestion(suggestion: Optional[dict]) -> str:
    if not suggestion:
        return ""
    try:
        c1 = tuple(sorted(str(c).strip().upper() for c in (suggestion.get("chi1_codes") or [])))
        c2 = tuple(sorted(str(c).strip().upper() for c in (suggestion.get("chi2_codes") or [])))
        c3 = tuple(sorted(str(c).strip().upper() for c in (suggestion.get("chi3_codes") or [])))
        if len(c1) != 5 or len(c2) != 5 or len(c3) != 3:
            return ""
        return "|".join([",".join(c3), ",".join(c2), ",".join(c1)])
    except Exception:
        return ""


def hand_key_from_suggestion(suggestion: Optional[dict]) -> str:
    if not suggestion:
        return ""
    codes = (
        list(suggestion.get("chi1_codes") or [])
        + list(suggestion.get("chi2_codes") or [])
        + list(suggestion.get("chi3_codes") or [])
    )
    return normalize_codes_key(codes)


def ensure_schema() -> None:
    conn = get_connection()
    conn.execute("DROP TABLE IF EXISTS auto_choice_overrides")
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {RULES_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hand_key TEXT NOT NULL,
            scope TEXT NOT NULL,
            selected_split_key TEXT NOT NULL,
            selected_template TEXT,
            chi1_codes TEXT NOT NULL,
            chi2_codes TEXT NOT NULL,
            chi3_codes TEXT NOT NULL,
            label TEXT,
            source TEXT NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_used_at TEXT,
            hand_features_json TEXT,
            selected_features_json TEXT,
            UNIQUE(hand_key, scope)
        );
        """
    )
    cur = conn.execute(f"PRAGMA table_info({RULES_TABLE})")
    cols = {str(row[1]) for row in cur.fetchall()}
    if "hand_features_json" not in cols:
        conn.execute(f"ALTER TABLE {RULES_TABLE} ADD COLUMN hand_features_json TEXT")
    if "selected_features_json" not in cols:
        conn.execute(f"ALTER TABLE {RULES_TABLE} ADD COLUMN selected_features_json TEXT")
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SETTINGS_TABLE} (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    conn.commit()


def get_ai_learning_settings() -> dict:
    try:
        ensure_schema()
        rows = get_connection().execute(f"SELECT key, value FROM {SETTINGS_TABLE}").fetchall()
        data = {str(r["key"]): str(r["value"]) for r in rows}
        enabled_raw = data.get("similarity_enabled")
        threshold_raw = data.get("similarity_threshold")
        enabled = DEFAULT_SIMILARITY_ENABLED if enabled_raw is None else enabled_raw not in ("0", "false", "False")
        try:
            threshold = int(threshold_raw) if threshold_raw is not None else DEFAULT_SIMILARITY_THRESHOLD
        except Exception:
            threshold = DEFAULT_SIMILARITY_THRESHOLD
        return {
            "similarity_enabled": bool(enabled),
            "similarity_threshold": max(50, min(100, int(threshold))),
        }
    except Exception:
        log.exception("[AUTO-CHOICE] read learning settings failed")
        return {
            "similarity_enabled": DEFAULT_SIMILARITY_ENABLED,
            "similarity_threshold": DEFAULT_SIMILARITY_THRESHOLD,
        }


def save_ai_learning_settings(
    *,
    similarity_enabled: Optional[bool] = None,
    similarity_threshold: Optional[int] = None,
) -> bool:
    try:
        ensure_schema()
        conn = get_connection()
        if similarity_enabled is not None:
            conn.execute(
                f"INSERT OR REPLACE INTO {SETTINGS_TABLE}(key, value) VALUES (?, ?)",
                ("similarity_enabled", "1" if similarity_enabled else "0"),
            )
        if similarity_threshold is not None:
            threshold = max(50, min(100, int(similarity_threshold)))
            conn.execute(
                f"INSERT OR REPLACE INTO {SETTINGS_TABLE}(key, value) VALUES (?, ?)",
                ("similarity_threshold", str(threshold)),
            )
        conn.commit()
        return True
    except Exception:
        log.exception("[AUTO-CHOICE] save learning settings failed")
        return False


def save_rule(
    hand_codes: Sequence[str],
    suggestion: dict,
    *,
    scope: str = DEFAULT_SCOPE,
    source: str = "user_context_menu",
) -> bool:
    hand_key = normalize_codes_key(hand_codes)
    selected_split_key = split_key_from_suggestion(suggestion)
    if not hand_key or not selected_split_key:
        return False

    now = _now_iso()
    chi1 = ",".join(str(c).strip().upper() for c in (suggestion.get("chi1_codes") or []))
    chi2 = ",".join(str(c).strip().upper() for c in (suggestion.get("chi2_codes") or []))
    chi3 = ",".join(str(c).strip().upper() for c in (suggestion.get("chi3_codes") or []))
    template = str(suggestion.get("template_key") or suggestion.get("label") or "").strip()
    label = str(suggestion.get("label") or suggestion.get("label_html") or "").strip()
    hand_features_json = json.dumps(extract_hand_features(hand_codes), ensure_ascii=False, separators=(",", ":"))
    selected_features_json = json.dumps(extract_suggestion_features(suggestion), ensure_ascii=False, separators=(",", ":"))

    try:
        ensure_schema()
        conn = get_connection()
        conn.execute(
            f"""
            INSERT INTO {RULES_TABLE} (
                hand_key, scope, selected_split_key, selected_template,
                chi1_codes, chi2_codes, chi3_codes, label, source,
                hand_features_json, selected_features_json,
                hit_count, enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?)
            ON CONFLICT(hand_key, scope) DO UPDATE SET
                selected_split_key=excluded.selected_split_key,
                selected_template=excluded.selected_template,
                chi1_codes=excluded.chi1_codes,
                chi2_codes=excluded.chi2_codes,
                chi3_codes=excluded.chi3_codes,
                label=excluded.label,
                source=excluded.source,
                hand_features_json=excluded.hand_features_json,
                selected_features_json=excluded.selected_features_json,
                enabled=1,
                updated_at=excluded.updated_at
            ;
            """,
            (
                hand_key,
                str(scope or DEFAULT_SCOPE),
                selected_split_key,
                template,
                chi1,
                chi2,
                chi3,
                label,
                str(source or "unknown"),
                hand_features_json,
                selected_features_json,
                now,
                now,
            ),
        )
        conn.commit()
        return True
    except Exception:
        log.exception("[AUTO-CHOICE] save rule failed hand=%s", hand_key)
        return False


def find_rule_match(
    hand_codes: Sequence[str],
    suggestions: Iterable[dict],
    *,
    scope: str = DEFAULT_SCOPE,
) -> Tuple[int, Optional[int], dict]:
    hand_key = normalize_codes_key(hand_codes)
    if not hand_key:
        return -1, None, {}
    try:
        ensure_schema()
        suggestion_list = list(suggestions or [])
        row = get_connection().execute(
            f"""
            SELECT id, selected_split_key
            FROM {RULES_TABLE}
            WHERE hand_key=? AND scope=? AND COALESCE(enabled, 1)=1
            LIMIT 1
            """,
            (hand_key, str(scope or DEFAULT_SCOPE)),
        ).fetchone()
        if row is not None:
            wanted = str(row["selected_split_key"] or "")
            for idx, item in enumerate(suggestion_list):
                if isinstance(item, dict) and split_key_from_suggestion(item) == wanted:
                    return int(idx), int(row["id"]), {"match_type": "exact", "similarity": 100.0}

        settings = get_ai_learning_settings()
        if not settings.get("similarity_enabled"):
            return -1, None, {}
        return find_similar_rule_match(
            hand_codes,
            suggestion_list,
            scope=scope,
            threshold=float(settings.get("similarity_threshold") or DEFAULT_SIMILARITY_THRESHOLD),
        )
    except Exception:
        log.exception("[AUTO-CHOICE] find rule failed hand=%s", hand_key)
        return -1, None, {}


def _decode_json(value: object) -> dict:
    try:
        if not value:
            return {}
        data = json.loads(str(value))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _row_hand_features(row: dict) -> dict:
    data = _decode_json(row.get("hand_features_json"))
    if data:
        return data
    return extract_hand_features(str(row.get("hand_key") or "").split(","))


def _row_choice_features(row: dict) -> dict:
    data = _decode_json(row.get("selected_features_json"))
    if data:
        return data
    return extract_suggestion_features(
        {
            "chi1_codes": str(row.get("chi1_codes") or "").split(","),
            "chi2_codes": str(row.get("chi2_codes") or "").split(","),
            "chi3_codes": str(row.get("chi3_codes") or "").split(","),
        }
    )


def find_similar_rule_match(
    hand_codes: Sequence[str],
    suggestions: Iterable[dict],
    *,
    scope: str = DEFAULT_SCOPE,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    limit: int = 2000,
) -> Tuple[int, Optional[int], dict]:
    hand_key = normalize_codes_key(hand_codes)
    suggestion_list = [s for s in list(suggestions or []) if isinstance(s, dict) and split_key_from_suggestion(s)]
    if not hand_key or not suggestion_list:
        return -1, None, {}

    current_hand = extract_hand_features(hand_codes)
    current_choices = [extract_suggestion_features(s) for s in suggestion_list]
    try:
        rows = [
            dict(row)
            for row in get_connection().execute(
                f"""
                SELECT id, hand_key, selected_split_key, selected_template,
                       chi1_codes, chi2_codes, chi3_codes, label, hit_count,
                       hand_features_json, selected_features_json
                FROM {RULES_TABLE}
                WHERE scope=? AND COALESCE(enabled, 1)=1
                ORDER BY hit_count DESC, updated_at DESC, id DESC
                LIMIT ?
                """,
                (str(scope or DEFAULT_SCOPE), max(1, int(limit or 2000))),
            ).fetchall()
        ]
    except Exception:
        log.exception("[AUTO-CHOICE] similar query failed hand=%s", hand_key)
        return -1, None, {}

    threshold_f = max(0.0, min(100.0, float(threshold or DEFAULT_SIMILARITY_THRESHOLD)))
    best: Optional[tuple[float, int, int, dict]] = None
    for row in rows:
        saved_hand = _row_hand_features(row)
        saved_choice = _row_choice_features(row)
        for idx, current_choice in enumerate(current_choices):
            raw_score = combined_similarity(saved_hand, current_hand, saved_choice, current_choice) * 100.0
            if raw_score < threshold_f:
                continue
            hit_bonus = min(2.5, float(row.get("hit_count") or 0) * 0.05)
            adjusted_score = min(100.0, raw_score + hit_bonus)
            info = {
                "match_type": "similar",
                "similarity": round(raw_score, 2),
                "similarity_adjusted": round(adjusted_score, 2),
                "threshold": threshold_f,
                "matched_rule_id": int(row.get("id") or 0),
                "matched_rule_template": row.get("selected_template") or row.get("label") or "",
            }
            candidate = (adjusted_score, int(row.get("id") or 0), int(idx), info)
            if best is None or candidate[0] > best[0]:
                best = candidate

    if best is None:
        return -1, None, {}
    _score, rule_id, idx, info = best
    return int(idx), int(rule_id), info


def mark_rule_used(rule_id: Optional[int]) -> None:
    if not rule_id:
        return
    try:
        ensure_schema()
        get_connection().execute(
            f"""
            UPDATE {RULES_TABLE}
            SET hit_count=hit_count+1, last_used_at=?, updated_at=?
            WHERE id=?
            """,
            (_now_iso(), _now_iso(), int(rule_id)),
        )
        get_connection().commit()
    except Exception:
        log.exception("[AUTO-CHOICE] mark rule used failed id=%s", rule_id)


def list_rules(
    *,
    scope: str = "",
    enabled: Optional[bool] = None,
    search: str = "",
    limit: int = 1000,
) -> list[dict]:
    """Return saved auto-choice rules for management UI."""
    try:
        ensure_schema()
        where: list[str] = []
        params: list[object] = []
        if scope:
            where.append("scope=?")
            params.append(str(scope))
        if enabled is not None:
            where.append("COALESCE(enabled, 1)=?")
            params.append(1 if enabled else 0)
        needle = str(search or "").strip().upper()
        if needle:
            where.append(
                "("
                "UPPER(hand_key) LIKE ? OR UPPER(selected_split_key) LIKE ? OR "
                "UPPER(COALESCE(selected_template,'')) LIKE ? OR UPPER(COALESCE(label,'')) LIKE ?"
                ")"
            )
            like = f"%{needle}%"
            params.extend([like, like, like, like])
        sql = f"""
            SELECT id, hand_key, scope, selected_split_key, selected_template,
                   chi1_codes, chi2_codes, chi3_codes, label, source, hit_count,
                   COALESCE(enabled, 1) AS enabled,
                   created_at, updated_at, last_used_at,
                   hand_features_json, selected_features_json
            FROM {RULES_TABLE}
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(max(1, int(limit or 1000)))
        return [dict(row) for row in get_connection().execute(sql, params).fetchall()]
    except Exception:
        log.exception("[AUTO-CHOICE] list rules failed")
        return []


def set_rule_enabled(rule_id: int, enabled: bool) -> bool:
    try:
        ensure_schema()
        get_connection().execute(
            f"""
            UPDATE {RULES_TABLE}
            SET enabled=?, updated_at=?
            WHERE id=?
            """,
            (1 if enabled else 0, _now_iso(), int(rule_id)),
        )
        get_connection().commit()
        return True
    except Exception:
        log.exception("[AUTO-CHOICE] set rule enabled failed id=%s enabled=%s", rule_id, enabled)
        return False


def delete_rule(rule_id: int) -> bool:
    try:
        ensure_schema()
        get_connection().execute(f"DELETE FROM {RULES_TABLE} WHERE id=?", (int(rule_id),))
        get_connection().commit()
        return True
    except Exception:
        log.exception("[AUTO-CHOICE] delete rule failed id=%s", rule_id)
        return False


def export_rules() -> list[dict]:
    return list_rules(limit=100000)


def import_rules(rows: Iterable[dict]) -> int:
    """Import unified AI rules."""
    ensure_schema()
    now = _now_iso()
    count = 0
    conn = get_connection()
    for raw in list(rows or []):
        if not isinstance(raw, dict):
            continue
        hand_key = str(raw.get("hand_key") or "").strip().upper()
        split_key = str(raw.get("selected_split_key") or "").strip().upper()
        scope = str(raw.get("scope") or DEFAULT_SCOPE).strip() or DEFAULT_SCOPE
        if not hand_key or not split_key:
            continue
        hand_features_json = str(raw.get("hand_features_json") or "")
        if not hand_features_json:
            hand_features_json = json.dumps(
                extract_hand_features(hand_key.split(",")),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        selected_features_json = str(raw.get("selected_features_json") or "")
        if not selected_features_json:
            selected_features_json = json.dumps(
                extract_suggestion_features(
                    {
                        "chi1_codes": str(raw.get("chi1_codes") or "").split(","),
                        "chi2_codes": str(raw.get("chi2_codes") or "").split(","),
                        "chi3_codes": str(raw.get("chi3_codes") or "").split(","),
                    }
                ),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        conn.execute(
            f"""
            INSERT INTO {RULES_TABLE} (
                hand_key, scope, selected_split_key, selected_template,
                chi1_codes, chi2_codes, chi3_codes, label, source,
                hand_features_json, selected_features_json,
                hit_count, enabled, created_at, updated_at, last_used_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hand_key, scope) DO UPDATE SET
                selected_split_key=excluded.selected_split_key,
                selected_template=excluded.selected_template,
                chi1_codes=excluded.chi1_codes,
                chi2_codes=excluded.chi2_codes,
                chi3_codes=excluded.chi3_codes,
                label=excluded.label,
                source=excluded.source,
                hand_features_json=excluded.hand_features_json,
                selected_features_json=excluded.selected_features_json,
                enabled=excluded.enabled,
                updated_at=excluded.updated_at,
                last_used_at=excluded.last_used_at
            ;
            """,
            (
                hand_key,
                scope,
                split_key,
                str(raw.get("selected_template") or ""),
                str(raw.get("chi1_codes") or ""),
                str(raw.get("chi2_codes") or ""),
                str(raw.get("chi3_codes") or ""),
                str(raw.get("label") or ""),
                str(raw.get("source") or "import"),
                hand_features_json,
                selected_features_json,
                int(raw.get("hit_count") or 0),
                1 if int(raw.get("enabled", 1) or 0) else 0,
                str(raw.get("created_at") or now),
                now,
                raw.get("last_used_at"),
            ),
        )
        count += 1
    conn.commit()
    return count


def export_rules_json() -> str:
    return json.dumps(export_rules(), ensure_ascii=False, indent=2)
