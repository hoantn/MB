"""
core/tool_context.py

Container cho tất cả tài nguyên của 1 tool slot (1-4):
  - BrowserManager (đọc đúng config slot)
  - GameController
  - WSCardStore (per-tool, tránh clash với Tool 1 global)
  - WS event / command queue (per-tool)
  - RoomControlTab + RoomEngine (tạo lazy khi start())
  - StrategyTab (tạo lazy khi build_widgets())
  - WS bridge server (khởi động khi start())

Mọi widget (QWidget/QObject) phải được tạo trên UI thread.
Gọi build_widgets() từ UI thread trước, rồi gọi start() để bắt bridge.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal


class ToolGateway(QObject):
    """
    Implement WebSocketGateway cho mỗi tool độc lập.
    Thay vì dùng global enqueue_command(), nó push vào per-tool command_queue.
    """

    def __init__(self, command_queue: "queue.Queue[Dict[str, Any]]", parent: Optional[QObject] = None):
        super().__init__(parent)
        self._cmd_q = command_queue

    def _enqueue(self, cmd: Dict[str, Any]) -> None:
        from ui2.bridge.ws_http_bridge import enqueue_command_to
        enqueue_command_to(cmd, self._cmd_q)

    # ---- WebSocketGateway interface ----

    def yeu_cau_cap_nhat_danh_sach_phong(self, profile_id: str, bet_muc_tieu: Optional[int]) -> None:
        from ui2.bridge.ws_payloads import build_ws_payload_update_room_list
        self._enqueue({
            "profile_id": profile_id,
            "action": "update_room_list",
            "bet_muc_tieu": bet_muc_tieu,
            "ws_payload": build_ws_payload_update_room_list(),
        })

    def gui_lenh_tao_phong(self, profile_id: str, bet: Optional[int]) -> None:
        # Tạo phòng chưa có payload riêng, log là đủ
        from core.logger import log
        log.info("[ToolGateway slot=%s] %s yêu cầu TẠO PHÒNG bet=%s", self.parent(), profile_id, bet)

    def gui_lenh_vao_phong(self, profile_id: str, room_id: int) -> None:
        from ui2.bridge.ws_payloads import build_ws_payload_join_room
        self._enqueue({
            "profile_id": profile_id,
            "action": "join_room",
            "room_id": int(room_id),
            "ws_payload": build_ws_payload_join_room(int(room_id)),
        })

    def gui_lenh_thoat_phong(self, profile_id: str) -> None:
        from ui2.bridge.ws_payloads import build_ws_payload_leave_room
        self._enqueue({
            "profile_id": profile_id,
            "action": "leave_room",
            "ws_payload": build_ws_payload_leave_room(),
        })


class ToolContext:
    """
    Tất cả tài nguyên cho 1 tool slot.

    Vòng đời:
      1. __init__(slot)             — khởi tạo non-UI resources
      2. build_widgets(parent)      — tạo Qt widgets (gọi trên UI thread)
      3. start()                    — khởi động WS bridge server
      4. stop()                     — dừng server (cleanup)
    """

    def __init__(self, slot: int, card_store=None) -> None:
        """
        slot: vị trí config (1-4).
        card_store: truyền vào để inject per-tool store.
            - None → tự tạo WSCardStore() mới (dùng cho slot 2-4)
            - ws_card_store (global) → dùng cho slot 1 để nhận cards từ main.py bridge
        """
        from core.config import load_config
        from core.tool_instance import get_bridge_port
        from browser.manager import BrowserManager
        from ui2.game_controller import GameController
        from ui2.bridge.ws_card_store import WSCardStore

        self.slot = slot
        self._config = load_config(slot)
        self.tool_index: int = self._config.get("ui", {}).get("tool_index", slot)

        # BrowserManager đọc đúng config-slot
        self.browser_manager = BrowserManager(slot=slot)

        # GameController dùng browser_manager của slot này
        self.game_controller = GameController(
            browser_manager=self.browser_manager,
            config=self.browser_manager.config,
        )

        # card_store: None → tạo mới (slot 2-4); hoặc inject global (slot 1)
        self.card_store = card_store if card_store is not None else WSCardStore()

        # Per-tool WS queues
        self.event_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.command_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()

        # WS bridge port theo tool_index
        self._bridge_port: int = get_bridge_port(self.tool_index)
        self._ws_server = None

        # Qt widgets (None cho đến khi build_widgets() được gọi trên UI thread)
        self.gateway: Optional[ToolGateway] = None
        self.room_tab = None          # RoomControlTab
        self.room_engine = None       # RoomEngine
        self.strategy_tab = None      # StrategyTab

        # Activity log sink (set sau bởi AutoFourToolTab)
        self.log_sink = None

    def build_widgets(self, parent=None) -> None:
        """
        Tạo tất cả Qt widgets cho tool này.
        PHẢI gọi từ UI thread.
        """
        from ui2.tabs.room_tab import RoomControlTab
        from ui2.tabs.strategy2.strategy_tab import StrategyTab
        from engine.room_engine import RoomEngine

        self.gateway = ToolGateway(self.command_queue)

        # RoomControlTab — không cần visible, RoomEngine đọc panel signals từ nó
        self.room_tab = RoomControlTab(self.browser_manager, parent=parent)

        # RoomEngine kết nối gateway per-tool thay vì MainWindow global
        self.room_engine = RoomEngine(
            room_tab=self.room_tab,
            ws_gateway=self.gateway,
            game_controller=self.game_controller,
        )

        # StrategyTab với per-tool card_store
        self.strategy_tab = StrategyTab(
            browser_manager=self.browser_manager,
            parent=parent,
            card_store=self.card_store,
        )

    def start(self) -> None:
        """Khởi động WS HTTP bridge cho tool này."""
        from ui2.bridge.ws_http_bridge import start_ws_http_bridge
        from core.logger import log

        self._ws_server = start_ws_http_bridge(
            host="127.0.0.1",
            port=self._bridge_port,
            event_queue=self.event_queue,
            command_queue=self.command_queue,
            slot=self.slot,
        )
        log.info(
            "[ToolContext] slot=%d tool_index=%d bridge started port=%d",
            self.slot, self.tool_index, self._bridge_port,
        )

    def stop(self) -> None:
        """Dừng WS bridge (nếu đang chạy)."""
        if self._ws_server is not None:
            try:
                self._ws_server.shutdown()
            except Exception:
                pass
            self._ws_server = None

    def dispatch_event(self, evt: Dict[str, Any]) -> None:
        """
        Xử lý 1 event từ per-tool event_queue — gương của _handle_bridge_event trong MainWindow
        nhưng dùng per-tool resources (card_store, room_engine).

        Gọi từ UI thread (timer trong AutoFourToolTab).
        """
        from core.logger import log

        kind = evt.get("kind")
        profile_id = str(evt.get("profile_id") or "P1")

        # Unwrap payload list dạng [opcode, {...}]
        payload = evt.get("payload")
        if isinstance(payload, list) and len(payload) >= 2 and isinstance(payload[1], dict):
            payload = payload[1]
            evt["payload"] = payload

        cmd = None
        if isinstance(payload, dict):
            cmd = payload.get("cmd") or payload.get("CMD")

        cs = evt.get("cs")
        if cs is None and isinstance(payload, dict):
            cs_p = payload.get("cs")
            if isinstance(cs_p, list):
                cs = cs_p

        # --- extension_ready ---
        if kind == "extension_ready":
            try:
                from ui2.bridge.ws_layout_store import ws_layout_store
                version = evt.get("version")
                if version is None and isinstance(payload, dict):
                    version = payload.get("version")
                ws_layout_store.mark_extension_ready(profile_id, str(version or "unknown"))
            except Exception:
                pass
            return

        # --- cmd=606: layout sau kéo (chia sẻ ws_layout_store global, phân biệt qua profile_id) ---
        if kind == "layout_snapshot" and cmd == 606 and isinstance(cs, list):
            try:
                from ui2.bridge.ws_layout_store import ws_layout_store
                sent_at_ms = evt.get("sent_at_ms")
                event_at = float(sent_at_ms) / 1000.0 if sent_at_ms is not None else None
                ws_layout_store.update_layout(profile_id, cs, event_at=event_at)
            except Exception:
                log.exception("[ToolContext] cmd606 failed slot=%d", self.slot)
            return

        # --- cmd=600: 13 lá gốc → per-tool card_store + ws_layout_store begin_hand ---
        if cs is not None and cmd == 600:
            try:
                self.card_store.update_cards(profile_id, cs)
                from ui2.bridge.ws_layout_store import ws_layout_store
                ws_layout_store.begin_hand(profile_id, cs)
            except Exception:
                log.exception("[ToolContext] cmd600 card update failed slot=%d", self.slot)

            # Room roster từ cmd=600 payload
            if self.room_engine is not None and isinstance(payload, dict):
                try:
                    self.room_engine.on_room_roster(profile_id, payload.get("lpi") or [])
                except Exception:
                    pass

        # --- cmd=100: self info ---
        if isinstance(payload, dict) and cmd == 100 and self.room_engine is not None:
            try:
                self.room_engine.on_self_info_100(profile_id, payload)
            except Exception:
                pass

        # --- cmd=200: vào/ra phòng ---
        if isinstance(payload, dict) and cmd == 200 and self.room_engine is not None:
            try:
                self.room_engine.on_room_event_200(profile_id, payload)
            except Exception:
                pass
            return

        # --- cmd=202 / kind=room_snapshot ---
        if kind == "room_snapshot" and self.room_engine is not None:
            try:
                snap_payload = evt.get("payload") or {}
                if isinstance(snap_payload, dict):
                    self._dispatch_room_snapshot(profile_id, snap_payload)
            except Exception:
                log.exception("[ToolContext] room_snapshot failed slot=%d", self.slot)

        # --- cmd=205 / kind=room_balance ---
        if isinstance(payload, dict) and (cmd == 205 or kind == "room_balance") and self.room_engine is not None:
            try:
                self.room_engine.on_room_balance_205(profile_id, payload)
            except Exception:
                pass
            return

        # --- kind=room_list ---
        if kind == "room_list" and self.room_engine is not None:
            try:
                rooms = evt.get("rooms") or []
                if isinstance(rooms, list):
                    self._dispatch_room_list(profile_id, rooms)
            except Exception:
                log.exception("[ToolContext] room_list failed slot=%d", self.slot)

    def _dispatch_room_list(self, profile_id: str, raw_rooms: List[Dict[str, Any]]) -> None:
        """Chuyển đổi raw room list → PhongLobby[] rồi gọi room_engine."""
        from engine.room_engine import PhongLobby  # PhongLobby định nghĩa trong room_engine
        ds = []
        for r in raw_rooms:
            try:
                ds.append(PhongLobby(
                    room_id=int(r.get("rid")),
                    bet=int(r.get("b")),
                    so_nguoi_hien_tai=int(r.get("c", 0) or 0),
                    so_nguoi_toi_da=int(r.get("Mu", 4) or 4),
                    co_mat_khau=bool(r.get("l")),
                ))
            except Exception:
                continue
        self.room_engine.on_danh_sach_phong(profile_id, ds)

    def _dispatch_room_snapshot(self, profile_id: str, payload: Dict[str, Any]) -> None:
        """Chuyển đổi raw room snapshot → TrangThaiPhong rồi gọi room_engine."""
        # TrangThaiPhong / NguoiChoiPhong được định nghĩa trong room_tab và re-export qua room_engine
        from ui2.tabs.room_tab import NguoiChoiPhong, TrangThaiPhong
        ps = payload.get("ps") or []
        so_nguoi = len(ps)
        so_nguoi_toi_da = int(payload.get("Mu", so_nguoi or 4) or 4)
        ds_nguoi_choi = []
        for p in ps:
            table_gold = p.get("m")
            if table_gold is None:
                table_gold = (p.get("As") or {}).get("gold")
            ds_nguoi_choi.append(NguoiChoiPhong(
                ghe=int(p.get("sit", -1) or -1),
                uid=str(p.get("uid", "")),
                ten=str(p.get("dn", "")),
                vang=table_gold,
            ))
        my_uid = self.room_engine.get_self_uid(profile_id)
        if not my_uid and ds_nguoi_choi:
            try:
                fi_ps_uids = {
                    str(p.get("uid", ""))
                    for p in ((payload.get("fi") or {}).get("ps") or [])
                    if p.get("uid")
                }
                if fi_ps_uids:
                    candidates = [p for p in ds_nguoi_choi if str(p.uid or "") not in fi_ps_uids]
                    if len(candidates) == 1:
                        my_uid = candidates[0].uid
                        self.room_engine.register_profile_uid_from_snapshot(profile_id, my_uid)
            except Exception:
                pass
            if not my_uid and ds_nguoi_choi:
                my_uid = ds_nguoi_choi[0].uid
        trang_thai = TrangThaiPhong(
            room_id=payload.get("rid"),
            bet=payload.get("b"),
            so_nguoi_hien_tai=so_nguoi,
            so_nguoi_toi_da=so_nguoi_toi_da,
            nguoi_choi=ds_nguoi_choi,
            my_uid=my_uid,
        )
        self.room_engine.on_trang_thai_phong(profile_id, trang_thai)
