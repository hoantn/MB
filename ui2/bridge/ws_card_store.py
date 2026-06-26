# ui2/bridge/ws_card_store.py
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

try:
    import logging
    logger = logging.getLogger("MauBinhTool.WSCards")
except Exception:  # pragma: no cover
    logger = None  # type: ignore

# Import queue event từ bridge
from .ws_http_bridge import WS_EVENT_QUEUE  # type: ignore

# Mapping 0..51 -> "2B", "TT", ...
from engine.ws_card_mapping import ws_codes_to_cards


class WSCardStore:
    """
    Lưu 13 lá bài mới nhất đọc từ WebSocket cho từng profile.
    Contract: store trả về list[str] mã bài TOOL (2B, TT, AC, ...).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cards_by_profile: Dict[str, List[str]] = {}
        self._hand_context_by_profile: Dict[str, Any] = {}
        # Dedup theo ws_codes (int) để tránh spam/replay cùng nội dung
        self._last_ws_codes_by_profile: Dict[str, List[int]] = {}

    # ---- API công khai -------------------------------------------------

    def update_cards(
        self,
        profile_id: str,
        ws_codes: List[int],
        *,
        hand_context: Any = None,
    ) -> List[str]:
        """
        Cập nhật 13 lá bài mới nhất cho profile_id từ list mã WS (0..51).
        Trả về list mã lá bài TOOL (2B, TT,...).
        """
        cards = ws_codes_to_cards(ws_codes)

        with self._lock:
            self._cards_by_profile[profile_id] = cards
            self._hand_context_by_profile[profile_id] = hand_context

        if logger:
            logger.info(
                "[MB WS CARDS] profile=%s ws_codes=%s -> cards=%s",
                profile_id,
                ws_codes,
                cards,
            )
        else:
            print(f"[MB WS CARDS] profile={profile_id} ws_codes={ws_codes} -> cards={cards}")

        return cards

    def get_last_cards(self, profile_id: str) -> Optional[List[str]]:
        """
        Lấy 13 lá bài mới nhất cho profile_id.
        Trả về list mã bài (2B, TT,...) hoặc None nếu chưa có.
        """
        with self._lock:
            cards = self._cards_by_profile.get(profile_id)
            return list(cards) if cards is not None else None

    def get_last_hand_context(self, profile_id: str) -> Any:
        """Return metadata captured at the cmd=600 hand-start moment."""
        with self._lock:
            return self._hand_context_by_profile.get(profile_id)

    def clear_profile(self, profile_id: str) -> None:
        """Forget the last hand for one profile after it leaves/changes table."""
        pid = str(profile_id or "")
        if not pid:
            return
        with self._lock:
            self._cards_by_profile.pop(pid, None)
            self._hand_context_by_profile.pop(pid, None)
            self._last_ws_codes_by_profile.pop(pid, None)


# Singleton dùng chung
ws_card_store = WSCardStore()


# ---------------------------------------------------------------------------
# Consumer: đọc WS_EVENT_QUEUE và feed vào WSCardStore
# CHỈ nhận CMD=600 (gốc rễ). CMD=606 ignore hoàn toàn.
# ---------------------------------------------------------------------------

def _extract_cmd600(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Trích thông tin cần thiết cho cmd=600 từ event thô.

    Extension của anh đang gửi dạng:
      {
        "profile_id": "P1",
        "kind": "cards_snapshot",
        "payload": {"cmd":600, "cs":[...13 ints...]}
      }

    Yêu cầu:
      - cmd == 600
      - cs là list 13 int
      - BẮT BUỘC có profile_id (không fallback)
    """
    # 1) profile_id: extension luôn gửi. Không fallback để tránh đổ nhầm.
    profile_id = event.get("profile_id") or event.get("profile") or event.get("pid")
    if not profile_id:
        if logger:
            logger.warning("[MB WS CARDS] drop cmd600: missing profile_id event=%s", event)
        return None

    # 2) cmd/cs có thể nằm top-level hoặc trong payload/data
    cmd = event.get("cmd")
    cs = event.get("cs")

    payload = event.get("payload")
    if isinstance(payload, dict):
        if cmd is None:
            cmd = payload.get("cmd")
        if cs is None:
            cs = payload.get("cs")

    data = event.get("data")
    if isinstance(data, dict):
        if cmd is None:
            cmd = data.get("cmd")
        if cs is None:
            cs = data.get("cs")

    # 3) Chỉ nhận cmd=600
    if cmd != 600:
        return None

    # 4) Validate cs
    if not isinstance(cs, list) or len(cs) != 13 or not all(isinstance(x, int) for x in cs):
        if logger:
            logger.warning("[MB WS CARDS] drop cmd600: invalid cs=%s event=%s", cs, event)
        return None

    return {"profile_id": str(profile_id), "codes": cs}


def ws_event_consumer_loop(stop_event: Optional[threading.Event] = None) -> None:
    """
    Vòng lặp chạy nền:
        - Lấy event từ WS_EVENT_QUEUE
        - Lọc cmd=600 (gốc rễ)
        - Dedup theo ws_codes
        - Cập nhật WSCardStore (đã convert 0..51 -> "2B/TT/..")
    """
    while True:
        if stop_event is not None and stop_event.is_set():
            break

        event = WS_EVENT_QUEUE.get()  # block

        try:
            info = _extract_cmd600(event)
            if info is None:
                continue

            profile_id = info["profile_id"]
            ws_codes: List[int] = info["codes"]

            # Dedup: nếu ws_codes y hệt lần trước của profile -> bỏ qua
            with ws_card_store._lock:
                prev_ws = ws_card_store._last_ws_codes_by_profile.get(profile_id)
                if prev_ws == ws_codes:
                    continue
                ws_card_store._last_ws_codes_by_profile[profile_id] = list(ws_codes)

            ws_card_store.update_cards(profile_id, ws_codes)

        except Exception as exc:  # pragma: no cover
            if logger:
                logger.exception("Error while processing WS event: %s", exc)
            else:
                print("Error while processing WS event:", exc)
