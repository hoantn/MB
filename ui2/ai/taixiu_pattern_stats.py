from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

VALID_SIDES = {"tai", "xiu"}


@dataclass
class PatternMatch:
    key: str
    display_name: str
    length: int
    side: Optional[str]
    strength_label: str
    note: str


@dataclass
class PatternStat:
    key: str
    display_name: str
    count: int


@dataclass
class PatternStatsResult:
    current_pattern: PatternMatch
    recent_sequence_text: str
    total_rounds_used: int
    stat_items: List[PatternStat]
    notes: List[str]


def _norm(side: Optional[str]) -> Optional[str]:
    s = str(side or "").strip().lower()
    return s if s in VALID_SIDES else None


def _seq_to_tokens(sides: Sequence[str]) -> str:
    mapping = {"tai": "T", "xiu": "X"}
    return " ".join(mapping.get(s, "?") for s in sides)


def _strength_label(length: int, thresholds: Tuple[int, int]) -> str:
    if length >= thresholds[1]:
        return "MẠNH"
    if length >= thresholds[0]:
        return "TRUNG BÌNH"
    return "YẾU"


def detect_streak(sides: Sequence[str]) -> Optional[PatternMatch]:
    if len(sides) < 3:
        return None
    last = sides[-1]
    count = 1
    for idx in range(len(sides) - 2, -1, -1):
        if sides[idx] == last:
            count += 1
        else:
            break
    if count < 3:
        return None
    display = "BỆT TÀI" if last == "tai" else "BỆT XỈU"
    return PatternMatch(
        key="streak",
        display_name=display,
        length=count,
        side=last,
        strength_label=_strength_label(count, (3, 5)),
        note=f"{count} phiên cuối liên tiếp cùng 1 bên.",
    )


def detect_alt_1_1(sides: Sequence[str]) -> Optional[PatternMatch]:
    if len(sides) < 4:
        return None
    length = 1
    for idx in range(len(sides) - 2, -1, -1):
        if sides[idx] != sides[idx + 1]:
            length += 1
        else:
            break
    if length < 4:
        return None
    return PatternMatch(
        key="alt_1_1",
        display_name="CẦU 1:1",
        length=length,
        side=None,
        strength_label=_strength_label(length, (4, 6)),
        note=f"{length} phiên cuối đang xen kẽ đều 1:1.",
    )


def _match_block(sides: Sequence[str], block_size: int, min_blocks: int = 2) -> Optional[PatternMatch]:
    need = block_size * min_blocks
    if len(sides) < need:
        return None

    rev = list(reversed(sides))
    blocks: List[List[str]] = []
    pos = 0
    while pos + block_size <= len(rev):
        block = rev[pos: pos + block_size]
        if len(set(block)) != 1:
            break
        blocks.append(block)
        pos += block_size
        if pos + block_size <= len(rev):
            next_block = rev[pos: pos + block_size]
            if len(set(next_block)) != 1:
                break
            if next_block[0] == block[0]:
                break

    if len(blocks) < min_blocks:
        return None

    total_len = len(blocks) * block_size
    label = f"CẦU {block_size}:{block_size}"
    thresholds = (need, max(need + block_size, need + 2))
    return PatternMatch(
        key=f"block_{block_size}_{block_size}",
        display_name=label,
        length=total_len,
        side=None,
        strength_label=_strength_label(total_len, thresholds),
        note=f"{len(blocks)} block gần nhất khớp nhịp {block_size}:{block_size}.",
    )


def detect_block_2_2(sides: Sequence[str]) -> Optional[PatternMatch]:
    return _match_block(sides, 2, min_blocks=2)


def detect_block_3_3(sides: Sequence[str]) -> Optional[PatternMatch]:
    return _match_block(sides, 3, min_blocks=2)


def detect_current_pattern(sides: Sequence[str]) -> PatternMatch:
    seq = [s for s in sides if s in VALID_SIDES]
    if not seq:
        return PatternMatch(
            key="unknown",
            display_name="KHÔNG RÕ",
            length=0,
            side=None,
            strength_label="YẾU",
            note="Chưa có dữ liệu final hợp lệ.",
        )

    # Priority: bệt > 1:1 > 2:2 > 3:3 > không rõ
    for detector in (detect_streak, detect_alt_1_1, detect_block_2_2, detect_block_3_3):
        found = detector(seq)
        if found is not None:
            return found

    return PatternMatch(
        key="unknown",
        display_name="KHÔNG RÕ",
        length=0,
        side=None,
        strength_label="YẾU",
        note="Chuỗi gần nhất chưa đủ điều kiện để kết luận thành 1 mẫu rõ.",
    )


def _window_pattern_at(sides: Sequence[str], end_index: int, max_window: int = 12) -> PatternMatch:
    start = max(0, end_index - max_window + 1)
    window = list(sides[start: end_index + 1])
    return detect_current_pattern(window)


def summarize_patterns(final_sides: Sequence[Optional[str]], limit: int = 200) -> PatternStatsResult:
    normalized = [_norm(s) for s in final_sides]
    seq = [s for s in normalized if s in VALID_SIDES]
    if limit > 0:
        seq = seq[-limit:]

    current = detect_current_pattern(seq)
    counts = {
        "streak": 0,
        "alt_1_1": 0,
        "block_2_2": 0,
        "block_3_3": 0,
        "unknown": 0,
    }

    for idx in range(len(seq)):
        match = _window_pattern_at(seq, idx, max_window=12)
        counts[match.key] = counts.get(match.key, 0) + 1

    stat_items = [
        PatternStat("streak", "BỆT", counts.get("streak", 0)),
        PatternStat("alt_1_1", "1:1", counts.get("alt_1_1", 0)),
        PatternStat("block_2_2", "2:2", counts.get("block_2_2", 0)),
        PatternStat("block_3_3", "3:3", counts.get("block_3_3", 0)),
        PatternStat("unknown", "KHÔNG RÕ", counts.get("unknown", 0)),
    ]

    notes = [
        f"Lấy {len(seq)} phiên final gần nhất để thống kê mẫu.",
        f"Mẫu hiện tại: {current.display_name} | Độ dài: {current.length} | {current.strength_label}.",
        current.note,
    ]

    return PatternStatsResult(
        current_pattern=current,
        recent_sequence_text=_seq_to_tokens(seq[-12:]),
        total_rounds_used=len(seq),
        stat_items=stat_items,
        notes=notes,
    )
