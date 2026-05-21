from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Mapping, Optional, Sequence

from ui2.ai.taixiu_pattern_stats import summarize_patterns

VN_TZ = timezone(timedelta(hours=7))


@dataclass
class TaiXiuOverviewResult:
    today_total: int
    today_tai: int
    today_xiu: int
    today_bias_text: str
    streak_segments_today: int
    longest_streak_today: int
    longest_streak_today_side: Optional[str]
    current_streak: int
    current_streak_side: Optional[str]
    current_pattern_name: str
    current_pattern_strength: str
    current_pattern_length: int
    highlight_lines: List[str]
    warning_lines: List[str]


def _norm_side(value: object) -> Optional[str]:
    s = str(value or "").strip().lower()
    return s if s in {"tai", "xiu"} else None


def _ts_to_dt(value: object) -> Optional[datetime]:
    try:
        raw = float(value)
    except Exception:
        return None
    if raw <= 0:
        return None
    if raw > 10_000_000_000:
        raw = raw / 1000.0
    try:
        return datetime.fromtimestamp(raw, tz=VN_TZ)
    except Exception:
        return None


def _extract_rows(rows: Iterable[Mapping[str, object]]) -> List[dict]:
    items: List[dict] = []
    for row in rows:
        side = _norm_side(row["result_side"] if "result_side" in row.keys() else row.get("result_side"))
        if side not in {"tai", "xiu"}:
            continue
        ts = row["last_seen_at"] if "last_seen_at" in row.keys() else row.get("last_seen_at")
        items.append({
            "sid": row["sid"] if "sid" in row.keys() else row.get("sid"),
            "result_side": side,
            "last_seen_at": ts,
            "dt": _ts_to_dt(ts),
        })
    items.sort(key=lambda x: (x["last_seen_at"] or 0))
    return items


def _calc_current_streak(sides: Sequence[str]) -> tuple[int, Optional[str]]:
    if not sides:
        return 0, None
    last = sides[-1]
    count = 1
    for idx in range(len(sides) - 2, -1, -1):
        if sides[idx] == last:
            count += 1
        else:
            break
    return count, last


def _calc_streak_segments(sides: Sequence[str], threshold: int = 3) -> tuple[int, int, Optional[str]]:
    if not sides:
        return 0, 0, None

    count_segments = 0
    longest = 0
    longest_side: Optional[str] = None

    current_side = sides[0]
    current_len = 1

    def close_segment(side: str, length: int) -> None:
        nonlocal count_segments, longest, longest_side
        if length >= threshold:
            count_segments += 1
            if length > longest:
                longest = length
                longest_side = side

    for side in sides[1:]:
        if side == current_side:
            current_len += 1
            continue
        close_segment(current_side, current_len)
        current_side = side
        current_len = 1

    close_segment(current_side, current_len)
    return count_segments, longest, longest_side


def _fmt_side(side: Optional[str]) -> str:
    if side == "tai":
        return "TÀI"
    if side == "xiu":
        return "XỈU"
    return "-"


def _bias_text(tai_count: int, xiu_count: int) -> str:
    total = tai_count + xiu_count
    if total <= 0:
        return "CHƯA ĐỦ DỮ LIỆU"
    tai_ratio = tai_count / total
    xiu_ratio = xiu_count / total
    if tai_ratio >= 0.58:
        return "THIÊN TÀI"
    if xiu_ratio >= 0.58:
        return "THIÊN XỈU"
    return "CÂN BẰNG"


def build_taixiu_overview(rows: Iterable[Mapping[str, object]]) -> TaiXiuOverviewResult:
    items = _extract_rows(rows)
    if not items:
        return TaiXiuOverviewResult(
            today_total=0,
            today_tai=0,
            today_xiu=0,
            today_bias_text="CHƯA CÓ DỮ LIỆU",
            streak_segments_today=0,
            longest_streak_today=0,
            longest_streak_today_side=None,
            current_streak=0,
            current_streak_side=None,
            current_pattern_name="KHÔNG RÕ",
            current_pattern_strength="-",
            current_pattern_length=0,
            highlight_lines=["Chưa có dữ liệu final hợp lệ để phân tích AI tổng quan."],
            warning_lines=["Kiểm tra lại DB hoặc luồng ghi kết quả final."],
        )

    sides_all = [x["result_side"] for x in items]
    current_streak, current_streak_side = _calc_current_streak(sides_all)
    current_pattern = summarize_patterns(sides_all, limit=200).current_pattern

    dated_items = [x for x in items if x["dt"] is not None]
    if dated_items:
        latest_date = dated_items[-1]["dt"].date()
        today_items = [x for x in dated_items if x["dt"].date() == latest_date]
    else:
        today_items = items[-200:]

    today_sides = [x["result_side"] for x in today_items]
    today_tai = sum(1 for s in today_sides if s == "tai")
    today_xiu = sum(1 for s in today_sides if s == "xiu")
    today_bias = _bias_text(today_tai, today_xiu)

    streak_segments_today, longest_streak_today, longest_streak_today_side = _calc_streak_segments(today_sides, threshold=3)

    today_pattern = summarize_patterns(today_sides, limit=200)

    highlights: List[str] = [
        f"Hôm nay có {len(today_sides)} phiên final | Tài {today_tai} | Xỉu {today_xiu} | {today_bias}.",
        f"Số cầu bệt hôm nay: {streak_segments_today} | Bệt dài nhất: {longest_streak_today} {_fmt_side(longest_streak_today_side)}.",
        f"Mẫu hiện tại: {current_pattern.display_name} | Độ dài: {current_pattern.length} | {current_pattern.strength_label}.",
    ]

    warnings: List[str] = []
    if current_streak >= 5:
        warnings.append(f"Đang có bệt {_fmt_side(current_streak_side)} {current_streak} phiên, chú ý khả năng kéo dài hoặc gãy mạnh.")
    if current_pattern.key == "unknown":
        warnings.append("Chuỗi gần nhất đang nhiễu, chưa đủ rõ để kết luận 1 mẫu cầu mạnh.")
    if today_pattern.current_pattern.key == "alt_1_1":
        warnings.append("Trong ngày đang nổi bật nhịp xen kẽ 1:1, tránh nhìn nhầm thành bệt ngắn.")
    if not warnings:
        warnings.append("Chưa thấy tín hiệu bất thường quá mạnh trong phạm vi dữ liệu hiện tại.")

    return TaiXiuOverviewResult(
        today_total=len(today_sides),
        today_tai=today_tai,
        today_xiu=today_xiu,
        today_bias_text=today_bias,
        streak_segments_today=streak_segments_today,
        longest_streak_today=longest_streak_today,
        longest_streak_today_side=longest_streak_today_side,
        current_streak=current_streak,
        current_streak_side=current_streak_side,
        current_pattern_name=current_pattern.display_name,
        current_pattern_strength=current_pattern.strength_label,
        current_pattern_length=current_pattern.length,
        highlight_lines=highlights,
        warning_lines=warnings,
    )
