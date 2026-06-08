from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import time
from typing import Callable, List, Optional

from core.apply_trace import apply_trace
from ui2.bridge.ws_layout_store import LayoutSnapshot, WSLayoutStore, ws_layout_store


def same_layout_groups(left: List[str], right: List[str]) -> bool:
    if len(left or []) != 13 or len(right or []) != 13:
        return False
    return all(
        Counter(map(str, left[start:end])) == Counter(map(str, right[start:end]))
        for start, end in ((0, 3), (3, 8), (8, 13))
    )


@dataclass(frozen=True)
class ApplyConfirmationResult:
    confirmed: bool
    layout: Optional[List[str]]
    snapshot: Optional[LayoutSnapshot]
    repair_attempts: int
    reason: str


def confirm_and_repair_layout(
    profile_id: str,
    target_layout: List[str],
    *,
    after_sequence: int,
    drag_finished_at: float,
    repair: Callable[[List[str]], float],
    store: WSLayoutStore = ws_layout_store,
    timeout_s: float = 6.5,
    first_snapshot_timeout_s: float = 11.5,
    max_repairs: Optional[int] = None,
    timeout_retry_count: int = 0,
    timeout_retry_s: float = 6.5,
    transaction_id: str = "-",
    expected_hand_generation: Optional[int] = None,
) -> ApplyConfirmationResult:
    """Chỉ xác nhận từ cmd=606 mới; mỗi lần sửa phải chờ một snapshot mới hơn."""
    pid = str(profile_id)
    sequence = int(after_sequence)
    event_floor = float(drag_finished_at)
    attempt = 0
    timeout_retries_used = 0
    max_timeout_retries = max(0, int(timeout_retry_count or 0))
    timeout_retry_s = max(0.01, float(timeout_retry_s or timeout_s or 0.01))

    while True:
        apply_trace(
            "layout606_wait",
            pid,
            after_seq=sequence,
            repair_attempt=attempt,
            tx=transaction_id,
        )
        # HAR thực tế: heartbeat 606 tiếp theo khoảng 5 giây, nhưng snapshot đầu
        # tiên của ván có thể đến sau cmd=600 khoảng 10 giây.
        if timeout_retries_used > 0:
            wait_timeout_s = float(timeout_retry_s)
        else:
            wait_timeout_s = (
                max(float(timeout_s), float(first_snapshot_timeout_s))
                if sequence <= 0
                else float(timeout_s)
            )
        snapshot = store.wait_for_newer(
            pid,
            after_sequence=sequence,
            after_event_at=event_floor,
            timeout_s=wait_timeout_s,
            expected_hand_generation=expected_hand_generation,
        )
        if snapshot is None:
            reason = (
                "hand_changed"
                if expected_hand_generation is not None
                and store.hand_generation(pid) != expected_hand_generation
                else "timeout"
            )
            apply_trace(
                f"layout606_{reason}",
                pid,
                repair_attempt=attempt,
                timeout_retry=timeout_retries_used,
                tx=transaction_id,
            )
            # 606 co the den cham hon mot chu ky heartbeat. Timeout dau tien chi
            # la soft timeout: cho them 606 moi, khong keo lai mu. Neu da sang
            # hand moi thi fail ngay de tranh xep sai van.
            if reason == "timeout" and timeout_retries_used < max_timeout_retries:
                timeout_retries_used += 1
                apply_trace(
                    "layout606_timeout_retry",
                    pid,
                    retry=timeout_retries_used,
                    retry_max=max_timeout_retries,
                    timeout_s=timeout_retry_s,
                    repair_attempt=attempt,
                    tx=transaction_id,
                )
                continue
            return ApplyConfirmationResult(False, None, None, attempt, reason)

        actual = list(snapshot.cards)
        apply_trace(
            "layout606_verify",
            pid,
            seq=snapshot.sequence,
            match=same_layout_groups(actual, target_layout),
            repair_attempt=attempt,
            tx=transaction_id,
        )
        if same_layout_groups(actual, target_layout):
            apply_trace(
                "layout606_confirmed",
                pid,
                seq=snapshot.sequence,
                repair_attempts=attempt,
                tx=transaction_id,
            )
            return ApplyConfirmationResult(True, actual, snapshot, attempt, "confirmed")
        if max_repairs is not None and attempt >= max(0, int(max_repairs)):
            apply_trace(
                "layout606_repair_exhausted",
                pid,
                seq=snapshot.sequence,
                repair_attempts=attempt,
                tx=transaction_id,
            )
            return ApplyConfirmationResult(False, actual, snapshot, attempt, "repair_exhausted")

        sequence = snapshot.sequence
        next_attempt = attempt + 1
        apply_trace(
            "layout606_repair_start",
            pid,
            seq=sequence,
            repair_attempt=next_attempt,
            tx=transaction_id,
        )
        event_floor = float(repair(actual))
        apply_trace(
            "layout606_repair_finished",
            pid,
            repair_attempt=next_attempt,
            tx=transaction_id,
        )
        attempt = next_attempt
