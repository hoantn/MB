from __future__ import annotations

from typing import List, Tuple, Optional, Dict, Any
import hashlib
import copy

from engine.card import Card
from engine.arranger import arrange_cards, arrange_13_cards, ArrangeStrategy
from engine.arranger_parts import arrange_cached_money_split

from ui2.tabs.dashboard.dashboard_constants import classify_chis, _format_suggestion_label

from ui2.tabs.strategy2.strategy_special13 import detect_special_13, build_special_split

def special_html_7colors(text: str) -> str:
    colors = ["#ff3b30", "#ff9500", "#ffcc00", "#34c759", "#32ade6", "#007aff", "#af52de"]
    parts = []
    for i, ch in enumerate(text):
        c = colors[i % len(colors)]
        if ch == " ":
            parts.append("&nbsp;")
        else:
            parts.append(f'<span style="color:{c};">{ch}</span>')
    return "".join(parts)

# -----------------------------------------------------------------------------
# Worker-level cache (per hand)
# Key: (pid, hand_hash, stage) -> suggestions(list[dict])
# -----------------------------------------------------------------------------
_SUGG_CACHE: Dict[Tuple[str, str, str], List[dict]] = {}
_SUGG_CACHE_MAX = 800  # keep modest


def _hand_hash(codes: List[str]) -> str:
    """Stable hash for a 13-card hand (order-insensitive)."""
    s = "|".join(sorted(codes))
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _cache_get(pid: str, hand_h: str, stage: str) -> Optional[List[dict]]:
    key = (pid, hand_h, stage)
    v = _SUGG_CACHE.get(key)
    if v is None:
        return None
    return copy.deepcopy(v)


def _cache_set(pid: str, hand_h: str, stage: str, suggestions: List[dict]) -> None:
    key = (pid, hand_h, stage)
    _SUGG_CACHE[key] = copy.deepcopy(suggestions)
    if len(_SUGG_CACHE) > _SUGG_CACHE_MAX:
        _SUGG_CACHE.clear()


def clear_cache_for_pid(pid: str) -> None:
    """Invalidate mọi cache của pid (khi WS báo hand mới)."""
    try:
        keys = [k for k in _SUGG_CACHE.keys() if k and k[0] == pid]
        for k in keys:
            _SUGG_CACHE.pop(k, None)
    except Exception:
        pass


def _safe_classify_and_label(name: str, c1, c2, c3):
    """Không để lỗi classify/format làm UI mất toàn bộ gợi ý."""
    try:
        chi_types = classify_chis(c1, c2, c3)
    except Exception:
        chi_types = {}
    try:
        label = _format_suggestion_label(name, None, None, chi_types)
    except Exception:
        label = name
    return chi_types, label


def _split_key_from_codes(chi1_codes: List[str], chi2_codes: List[str], chi3_codes: List[str]) -> str:
    try:
        if len(chi1_codes) != 5 or len(chi2_codes) != 5 or len(chi3_codes) != 3:
            return ""
        c1 = ",".join(sorted(str(c).strip().upper() for c in chi1_codes))
        c2 = ",".join(sorted(str(c).strip().upper() for c in chi2_codes))
        c3 = ",".join(sorted(str(c).strip().upper() for c in chi3_codes))
        return "|".join([c3, c2, c1])
    except Exception:
        return ""


def _build_money_suggestion(pid: str, stage: str, cards: List[Card]) -> Optional[dict]:
    try:
        money_split = arrange_cached_money_split(cards)
    except Exception:
        money_split = None
    if not money_split:
        return None

    try:
        c1, c2, c3 = money_split
        chi1_codes = [c.to_code() for c in c1]
        chi2_codes = [c.to_code() for c in c2]
        chi3_codes = [c.to_code() for c in c3]
        chi_types, _ = _safe_classify_and_label("auto", c1, c2, c3)
    except Exception:
        return None

    split_key = _split_key_from_codes(chi1_codes, chi2_codes, chi3_codes)
    if not split_key:
        return None

    return {
        "pid": pid,
        "stage": stage,
        "mode": "money",
        "variant": 0,
        "label": "[auto]",
        "chi1_codes": chi1_codes,
        "chi2_codes": chi2_codes,
        "chi3_codes": chi3_codes,
        "chi_types": chi_types,
        "_split_key": split_key,
        "_auto_engine_money": True,
    }


def build_suggestions_for_codes(profile_id: str, codes: List[str], stage: str = "FULL") -> List[dict]:
    """
    StrategyTab suggestions (STYLE brute-force).

    - Luôn trả stage "FULL" để ổn định UI.
    - Sinh gợi ý bằng arrange_13_cards (bruteforce theo chi) để trả nhiều split.
    - Không dùng beauty_flow / arrange_all.
    - Không lọc áp chế / không dedup nâng cao: giữ nguyên tất cả split để bạn quan sát.
    """
    pid = profile_id
    stage_u = "FULL"

    usable = [c for c in (codes or []) if c and c not in ("--", "??")]
    if len(usable) != 13:
        return []

    # CACHE: mặc định tắt để bạn debug (bật lại khi cần tối ưu).
    hand_h = _hand_hash(usable)
    cached = _cache_get(pid, hand_h, stage_u)
    if cached is not None:
        return cached

    try:
        cards = [Card.from_code(c) for c in usable]
    except Exception:
        return []
    # --------------------------
    # SPECIAL (build in WORKER)
    # --------------------------
    special_sugg = None
    try:
        sp = detect_special_13(usable)  # (special_name, chi_pts) or None
    except Exception:
        sp = None

    if sp:
        special_name, chi_pts = sp
        try:
            built = build_special_split(cards, special_name)  # (c1,c2,c3) or None
        except Exception:
            built = None

        if built:
            c1, c2, c3 = built
            try:
                chi1_codes = [c.to_code() for c in c1]
                chi2_codes = [c.to_code() for c in c2]
                chi3_codes = [c.to_code() for c in c3]
            except Exception:
                chi1_codes = chi2_codes = chi3_codes = None

            if chi1_codes and chi2_codes and chi3_codes:
                # vẫn classify để UI nơi khác dùng nếu cần, nhưng KHÔNG dùng format label
                try:
                    chi_types = classify_chis(c1, c2, c3)
                except Exception:
                    chi_types = {}

                label = f"[SPECIAL] {special_name}"  # chỉ tên bài đặc biệt, không ghép chi-types
                title = f"🏆 {special_name} ({chi_pts} chi) 🏆"
                label_html = (
                    "<div style='font-weight:900; font-size:15px; line-height:1.2;'>"
                    f"{special_html_7colors(title)}"
                    "</div>"
                )

                special_sugg = {
                    "pid": pid,
                    "stage": stage_u,
                    "mode": "special",
                    "variant": -999,
                    "label": label,
                    "chi1_codes": chi1_codes,
                    "chi2_codes": chi2_codes,
                    "chi3_codes": chi3_codes,
                    "chi_types": chi_types,
                    "_is_special_row": True,
                    "special_name": special_name,
                    "special_chi_points": int(chi_pts),
                    "label_html": label_html,
                    "is_special": True,
                    "special_has_split": True,
                }

    # 1) ALL splits từ arrange_13_cards (max_candidates=None => không cắt)
    all_splits: List[Tuple[List[Card], List[Card], List[Card]]] = []
    try:
        all_splits = arrange_13_cards(cards, max_candidates=None)
    except Exception:
        all_splits = []

    # 2) Fallback: nếu engine trả rỗng, lấy best-1 bằng brute-force style
    if not all_splits:
        try:
            c1, c2, c3 = arrange_cards(cards, strategy=ArrangeStrategy.STYLE_BRUTEFORCE_ALL)
            all_splits = [(c1, c2, c3)]
        except Exception:
            all_splits = []

    out: List[dict] = []

    for idx0, (c1, c2, c3) in enumerate(all_splits, start=1):
        try:
            chi1_codes = [c.to_code() for c in c1]
            chi2_codes = [c.to_code() for c in c2]
            chi3_codes = [c.to_code() for c in c3]
        except Exception:
            continue

        base_name = f"Max{idx0}"
        chi_types, label = _safe_classify_and_label(base_name, c1, c2, c3)

        out.append(
            {
                "pid": pid,
                "stage": stage_u,
                "mode": "max",   # giữ để UI/logic khác không đổi
                "variant": idx0,
                "label": label,
                "chi1_codes": chi1_codes,
                "chi2_codes": chi2_codes,
                "chi3_codes": chi3_codes,
                "chi_types": chi_types,
            }
        )

    # CACHE: mặc định tắt để tránh reuse list cũ khi bạn đang test/đổi arrange.
    money_sugg = _build_money_suggestion(pid, stage_u, cards)
    if money_sugg:
        money_key = str(money_sugg.get("_split_key") or "")
        deduped: List[dict] = []
        for item in out:
            item_key = _split_key_from_codes(
                list(item.get("chi1_codes") or []),
                list(item.get("chi2_codes") or []),
                list(item.get("chi3_codes") or []),
            )
            if money_key and item_key == money_key:
                continue
            deduped.append(item)
        out = [money_sugg] + deduped

    _cache_set(pid, hand_h, stage_u, out)
    # Prepend SPECIAL (nếu có) -> trả đúng 1 row special có đủ chi1/chi2/chi3 để APPLY
    if special_sugg:
        return [special_sugg] + out
    return out
