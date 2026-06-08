from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import threading
import time
from typing import Deque, Dict, List, Optional

from core.apply_trace import apply_trace
from engine.ws_card_mapping import ws_codes_to_tool_slot_order


def layout606_to_slot_order(ws_codes: List[int]) -> List[str]:
    """
    cmd=606/cmd=603 dùng thứ tự logic 5-5-3: chi dưới, chi giữa, chi trên.
    UI/apply của tool dùng thứ tự slot 3-5-5: trên, giữa, dưới.
    """
    return ws_codes_to_tool_slot_order(list(ws_codes or []))


@dataclass(frozen=True)
class LayoutSnapshot:
    profile_id: str
    sequence: int
    ws_codes: List[int]
    cards: List[str]
    event_at: float
    received_at: float
    hand_generation: int


class WSLayoutStore:
    """Lưu cmd=606 riêng biệt; tuyệt đối không thay đổi bộ bài gốc cmd=600."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._sequence = 0
        self._original_by_profile: Dict[str, List[int]] = {}
        self._hand_generation_by_profile: Dict[str, int] = {}
        self._history_by_profile: Dict[str, Deque[LayoutSnapshot]] = {}
        self._extension_version_by_profile: Dict[str, str] = {}

    @staticmethod
    def _valid_codes(codes: List[int]) -> bool:
        return (
            isinstance(codes, list)
            and len(codes) == 13
            and len(set(codes)) == 13
            and all(isinstance(code, int) and 0 <= code <= 51 for code in codes)
        )

    def begin_hand(self, profile_id: str, ws_codes: List[int]) -> None:
        pid = str(profile_id)
        codes = list(ws_codes or [])
        if not self._valid_codes(codes):
            return
        with self._condition:
            if self._original_by_profile.get(pid) != codes:
                self._original_by_profile[pid] = codes
                self._hand_generation_by_profile[pid] = (
                    int(self._hand_generation_by_profile.get(pid, 0)) + 1
                )
                self._history_by_profile[pid] = deque(maxlen=24)
                self._condition.notify_all()
                apply_trace("layout606_hand_begin", pid)

    def update_layout(
        self,
        profile_id: str,
        ws_codes: List[int],
        *,
        event_at: Optional[float] = None,
    ) -> Optional[LayoutSnapshot]:
        pid = str(profile_id)
        codes = list(ws_codes or [])
        if not self._valid_codes(codes):
            apply_trace("layout606_drop_invalid", pid, codes_len=len(codes))
            return None

        received_at = time.time()
        with self._condition:
            original = self._original_by_profile.get(pid)
            if original is None or Counter(codes) != Counter(original):
                apply_trace("layout606_drop_hand_mismatch", pid)
                return None

            history = self._history_by_profile.setdefault(pid, deque(maxlen=24))
            first_for_hand = not history
            if history and history[-1].ws_codes == codes:
                # Cùng layout vẫn là heartbeat mới và có thể xác nhận lần kéo vừa hoàn tất.
                pass
            self._sequence += 1
            snapshot = LayoutSnapshot(
                profile_id=pid,
                sequence=self._sequence,
                ws_codes=codes,
                cards=layout606_to_slot_order(codes),
                event_at=float(event_at or received_at),
                received_at=received_at,
                hand_generation=int(self._hand_generation_by_profile.get(pid, 0)),
            )
            history.append(snapshot)
            self._condition.notify_all()
            if first_for_hand:
                apply_trace(
                    "layout606_ready",
                    pid,
                    seq=snapshot.sequence,
                    hand_generation=snapshot.hand_generation,
                )
            return snapshot

    def latest_sequence(self, profile_id: str) -> int:
        with self._condition:
            history = self._history_by_profile.get(str(profile_id))
            return int(history[-1].sequence) if history else 0

    def mark_extension_ready(self, profile_id: str, version: str) -> None:
        pid = str(profile_id)
        with self._condition:
            self._extension_version_by_profile[pid] = str(version or "unknown")
            self._condition.notify_all()
        apply_trace("layout606_extension_ready", pid, version=str(version or "unknown"))

    def extension_version(self, profile_id: str) -> Optional[str]:
        with self._condition:
            return self._extension_version_by_profile.get(str(profile_id))

    def latest_snapshot(self, profile_id: str) -> Optional[LayoutSnapshot]:
        with self._condition:
            history = self._history_by_profile.get(str(profile_id))
            return history[-1] if history else None

    def hand_generation(self, profile_id: str) -> int:
        with self._condition:
            return int(self._hand_generation_by_profile.get(str(profile_id), 0))

    def ready_snapshot(self, profile_id: str, expected_cards: List[str]) -> Optional[LayoutSnapshot]:
        """Trả snapshot 606 của đúng ván hiện tại để xác nhận/sửa sau khi kéo."""
        pid = str(profile_id)
        expected = list(expected_cards or [])
        with self._condition:
            history = self._history_by_profile.get(pid)
            if not history:
                return None
            snapshot = history[-1]
            if len(expected) != 13 or Counter(map(str, snapshot.cards)) != Counter(map(str, expected)):
                return None
            if snapshot.hand_generation != self._hand_generation_by_profile.get(pid, 0):
                return None
            return snapshot

    def wait_for_newer(
        self,
        profile_id: str,
        *,
        after_sequence: int,
        after_event_at: float,
        timeout_s: float,
        expected_hand_generation: Optional[int] = None,
    ) -> Optional[LayoutSnapshot]:
        pid = str(profile_id)
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        with self._condition:
            while True:
                if (
                    expected_hand_generation is not None
                    and self._hand_generation_by_profile.get(pid, 0) != expected_hand_generation
                ):
                    return None
                history = self._history_by_profile.get(pid) or ()
                for snapshot in history:
                    if (
                        snapshot.sequence > int(after_sequence)
                        and snapshot.event_at >= float(after_event_at)
                    ):
                        return snapshot
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)


ws_layout_store = WSLayoutStore()
