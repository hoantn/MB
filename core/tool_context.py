"""
core/tool_context.py

Container cho tất cả tài nguyên của 1 tool slot:
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
        slot: vị trí config.
        card_store: truyền vào để inject per-tool store.
            - None → tự tạo WSCardStore() mới (dùng cho slot 2+)
            - ws_card_store (global) → dùng cho slot 1 để nhận cards từ main.py bridge
        """
        from core.config import load_config
        from core.tool_instance import get_bridge_port
        from browser.manager import BrowserManager
        from ui2.game_controller import GameController
        from ui2.bridge.ws_card_store import WSCardStore
        from ui2.bridge.ws_layout_store import WSLayoutStore
        from ui2.runtime.tool_action_gate import ToolActionGate

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

        # card_store: None → tạo mới (slot 2+); hoặc inject global (slot 1)
        self.card_store = card_store if card_store is not None else WSCardStore()
        self.layout_store = WSLayoutStore()
        self.action_gate = ToolActionGate(slot=slot)

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
        self.profiles_tab = None      # ProfilesTabV2
        self.config_tab = None        # ConfigTab
        self.xao_vang_tab = None      # XaoVangTab
        self.xao_vang_adapter = None  # XaoVangToolAdapter

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
        from ui2.tabs.profiles_tab_v2 import ProfilesTabV2
        from ui2.tabs.config_tab import ConfigTab
        from ui2.tabs.xao_vang_tab import XaoVangTab
        from ui2.tabs.xao_vang_tool_adapter import XaoVangToolAdapter

        # Slot 1: extension polls main.py bridge (port 9527) → dùng global WS_COMMAND_QUEUE.
        # Slot 2+: per-tool bridge riêng → dùng per-tool command_queue.
        if self.slot == 1:
            from ui2.bridge.ws_http_bridge import WS_COMMAND_QUEUE as _GLOBAL_CMD_Q
            self.gateway = ToolGateway(_GLOBAL_CMD_Q)
        else:
            self.gateway = ToolGateway(self.command_queue)

        # RoomControlTab — không cần visible, RoomEngine đọc panel signals từ nó
        self.room_tab = RoomControlTab(self.browser_manager, parent=parent)

        # RoomEngine kết nối gateway per-tool thay vì MainWindow global
        self.room_engine = RoomEngine(
            room_tab=self.room_tab,
            ws_gateway=self.gateway,
            game_controller=self.game_controller,
            action_gate=self.action_gate,
        )

        # StrategyTab với per-tool card_store
        self.strategy_tab = StrategyTab(
            browser_manager=self.browser_manager,
            parent=parent,
            card_store=self.card_store,
            room_engine=self.room_engine,
            layout_store=self.layout_store,
            game_controller=self.game_controller,
            action_gate=self.action_gate,
        )

        # ProfilesTabV2 — cấu hình chrome_path/proxy/URL per-slot
        self.profiles_tab = ProfilesTabV2(
            browser_manager=self.browser_manager,
            parent=parent,
        )

        self.config_tab = ConfigTab(
            parent=parent,
            slot=self.slot,
            embedded=True,
        )

        self.xao_vang_tab = XaoVangTab(
            parent=parent,
            slot=self.slot,
        )
        self.xao_vang_adapter = XaoVangToolAdapter(
            slot=self.slot,
            xao_vang_tab=self.xao_vang_tab,
            game_controller=self.game_controller,
            action_gate=self.action_gate,
            parent=self.gateway,
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

        if kind == "extension_stats":
            try:
                import json
                import time

                stats = evt.get("stats") if isinstance(evt.get("stats"), dict) else {}
                reported_at_ms = evt.get("reported_at_ms")
                try:
                    lag_ms = int(time.time() * 1000.0 - float(reported_at_ms))
                except Exception:
                    lag_ms = -1
                try:
                    qsize = int(self.event_queue.qsize())
                except Exception:
                    qsize = -1
                log.info(
                    "[WS-EXT-STATS] slot=%d profile=%s qsize=%s lag_ms=%s stats=%s",
                    self.slot,
                    profile_id,
                    qsize,
                    lag_ms,
                    json.dumps(stats, ensure_ascii=False, sort_keys=True),
                )
            except Exception:
                log.exception("[ToolContext] extension_stats log failed slot=%d", self.slot)
            return

        # Unwrap payload list dạng [opcode, {...}]
        payload = evt.get("payload")
        if isinstance(payload, list) and len(payload) >= 2 and isinstance(payload[1], dict):
            payload = payload[1]
            evt["payload"] = payload

        cmd = None
        if isinstance(payload, dict):
            cmd = payload.get("cmd") or payload.get("CMD")

        # --- Tai/Xiu cmd=1008: trigger Xao Vang auto per-tool ---
        # MainWindow only owns the legacy global Xao Vang tab. In Auto Play,
        # each ToolContext has its own XaoVangTab, so the per-tool bridge must
        # trigger auto here to keep slot isolation.
        if kind == "taixiu_ws" and isinstance(payload, dict):
            try:
                if int(cmd or 0) == 1008:
                    sid = payload.get("sid")
                    sid_str = str(sid or "").strip()
                    direction = str(evt.get("direction") or payload.get("direction") or "").strip().lower()
                    has_round_snapshot = (
                        direction == "recv"
                        and sid_str
                        and (
                            payload.get("rmT") is not None
                            or bool(payload.get("gi"))
                        )
                    )
                    if has_round_snapshot and self.xao_vang_tab is not None:
                        fired = self.xao_vang_tab.trigger_auto_for_sid(sid_str)
                        if fired:
                            log.info(
                                "[ToolContext] Auto Xao Vang triggered slot=%d sid=%s profile=%s rmT=%s gS=%s",
                                self.slot,
                                sid_str,
                                profile_id,
                                payload.get("rmT"),
                                payload.get("gS"),
                            )
                    return
            except Exception:
                log.exception("[ToolContext] Auto Xao Vang trigger failed slot=%d", self.slot)
                return

        cs = evt.get("cs")
        if cs is None and isinstance(payload, dict):
            cs_p = payload.get("cs")
            if isinstance(cs_p, list):
                cs = cs_p

        if kind == "extension_ready":
            try:
                version = evt.get("version")
                if version is None and isinstance(payload, dict):
                    version = payload.get("version")
                self.layout_store.mark_extension_ready(profile_id, str(version or "unknown"))
            except Exception:
                log.exception("[ToolContext] extension_ready layout mark failed slot=%d", self.slot)
            return

        # --- cmd=606: layout sau kéo ---
        # 606 chi la layout hien tai. Khong ghi vao card_store vi card_store la
        # bai goc cmd=600 dung cho hand hash / van moi.
        if cs is not None and cmd == 606:
            try:
                sent_at_ms = evt.get("sent_at_ms")
                event_at = float(sent_at_ms) / 1000.0 if sent_at_ms is not None else None
                self.layout_store.update_layout(profile_id, cs, event_at=event_at)
            except Exception:
                log.exception("[ToolContext] cmd606 layout_store update failed slot=%d", self.slot)
            return

        # --- cmd=600: 13 lá gốc → per-tool card_store ---
        if cs is not None and cmd == 600:
            hand_context = None
            # Room roster từ cmd=600 payload
            if self.room_engine is not None and isinstance(payload, dict):
                try:
                    lpi = payload.get("lpi")
                    if isinstance(lpi, list):
                        self.room_engine.on_room_roster(profile_id, lpi)
                except Exception:
                    pass
                try:
                    from ui2.tabs.strategy2.modules.auto_play_controller import (
                        classify_auto_room_context,
                        classify_hand_start_room_context,
                    )

                    if isinstance(lpi, list) and lpi:
                        hand_context = classify_hand_start_room_context(self.room_engine, lpi)
                    else:
                        hand_context = classify_auto_room_context(self.room_engine)
                except Exception:
                    hand_context = None
            try:
                try:
                    self.card_store.update_cards(profile_id, cs, hand_context=hand_context)
                except TypeError:
                    self.card_store.update_cards(profile_id, cs)
            except Exception:
                log.exception("[ToolContext] cmd600 card update failed slot=%d", self.slot)
            try:
                self.layout_store.begin_hand(profile_id, cs)
            except Exception:
                log.exception("[ToolContext] cmd600 layout hand begin failed slot=%d", self.slot)

        # --- cmd=100: self info (bỏ qua mini-game socket có id != 0 — giống main.py) ---
        if isinstance(payload, dict) and cmd == 100:
            msg_id = payload.get("id")
            if msg_id is not None:
                try:
                    if int(msg_id) != 0:
                        return
                except Exception:
                    return
            if self.room_engine is not None:
                try:
                    self.room_engine.on_self_info_100(profile_id, payload)
                except Exception:
                    pass
            return

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
