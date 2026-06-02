from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, List, Literal, Tuple, Any

from PySide6.QtCore import QObject, QTimer, Signal

from ui2.tabs.room_tab import TrangThaiPhong, RoomControlTab, NguoiChoiPhong
from core.logger import log
from core.config import load_config

# ---------------------------------------------------------------------------
# Mô hình dữ liệu: danh sách phòng ở lobby (cmd=300)
# ---------------------------------------------------------------------------

@dataclass
class PhongLobby:
    room_id: int
    bet: int
    so_nguoi_hien_tai: int
    so_nguoi_toi_da: int
    co_mat_khau: bool = False


# Trạng thái tác vụ cho từng profile (P1 / P2 / P3)
@dataclass
class TacVuProfile:
    che_do: Optional[Literal["create", "join", "find_guest"]] = None
    target_uid: Optional[str] = None
    bet_muc_tieu: Optional[int] = None
    delay_ms: int = 0
    dang_cho_ket_qua: bool = False


# ---------------------------------------------------------------------------
# Gateway WebSocket: MainWindow implement
# ---------------------------------------------------------------------------

class WebSocketGateway:
    def gui_lenh_tao_phong(self, profile_id: str, bet: Optional[int]) -> None:
        raise NotImplementedError

    def gui_lenh_vao_phong(self, profile_id: str, room_id: int) -> None:
        raise NotImplementedError

    def gui_lenh_thoat_phong(self, profile_id: str) -> None:
        raise NotImplementedError

    def yeu_cau_cap_nhat_danh_sach_phong(
        self,
        profile_id: str,
        bet_muc_tieu: Optional[int],
    ) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# RoomEngine
# ---------------------------------------------------------------------------

class RoomEngine(QObject):
    """
    - Vào phòng / tạo phòng solo = CLICK Bet theo toạ độ (GameController).
    - Thoát phòng = CLICK Exit 2 lần (GameController.click_exit_room).
    - 202 (room_snapshot) dùng làm baseline + đổi phòng + ARM.
    - 200 (room_event) dùng để realtime join/leave/update danh sách người chơi theo mô hình "chỉ 202+200".
    """

    # args: profile_id, player_name, gold
    sig_player_joined = Signal(str, str, int)

    # args: profile_id, player_name, gold
    sig_player_left = Signal(str, str, int)

    # args: profiles mapping from get_room_monitor_state()
    sig_gold_monitor_changed = Signal(object)

    def __init__(
        self,
        room_tab: RoomControlTab,
        ws_gateway: WebSocketGateway,
        game_controller,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.room_tab = room_tab
        self.ws_gateway = ws_gateway
        self.game = game_controller
        # Delay giữa 2 lần click thoát phòng (click 2 lần) - lấy từ config
        self._exit_double_click_ms: int = 130
        try:
            cfg = load_config()
            ui = cfg.get("ui") or {}
            ui_room = ui.get("room") or {}
            v = int(ui_room.get("exit_double_click_ms", 130) or 0)
            # clamp an toàn
            self._exit_double_click_ms = max(0, min(v, 3000))
        except Exception as e:
            log.debug("RoomEngine: cannot load ui.room.exit_double_click_ms: %s", e)
            self._exit_double_click_ms = 130

        # thông tin chính mình
        self._self_uid_by_profile: dict[str, str] = {}
        self._self_uid_all: set[str] = set()
        # Monitoring cache stays independent from UI filtering.
        self._gold_by_uid: dict[str, int] = {}
        self._room_uids_by_profile: Dict[str, set[str]] = {
            "P1": set(),
            "P2": set(),
            "P3": set(),
        }

        self.tac_vu: Dict[str, TacVuProfile] = {
            "P1": TacVuProfile(),
            "P2": TacVuProfile(),
            "P3": TacVuProfile(),
        }
        # ===== Room history (DB) =====
        self._active_room_session: Dict[str, int] = {}
        self._last_room_key: Dict[str, Optional[tuple]] = {
            "P1": None,
            "P2": None,
            "P3": None,
        }
        # Target UID hiện tại để highlight trên UI
        self.target_hien_tai: Dict[str, Optional[str]] = {"P1": None, "P2": None, "P3": None}

        # Cache snapshot phòng gần nhất
        self._last_snapshot: Dict[str, Optional[TrangThaiPhong]] = {"P1": None, "P2": None, "P3": None}

        # Trạng thái đang chờ refresh snapshot (cmd=202) sau khi bấm 'Làm mới'
        self._refresh_waiting: Dict[str, bool] = {"P1": False, "P2": False, "P3": False}

        # ===== Realtime toast state (neo P1) =====
        self._p1_room_key: Optional[Tuple] = None
        self._p1_armed: bool = False
        self._p1_seen_uids: set[str] = set()

        # ===== Room UI throttling (giảm lag do repaint liên tục) =====
        # Mọi event 200/202 chỉ đánh dấu dirty, UI flush theo batch mỗi ~80ms/profile.
        self._room_ui_dirty: set[str] = set()
        self._room_ui_timers: Dict[str, QTimer] = {}
        self._room_ui_last_sig: Dict[str, Optional[Tuple[Any, ...]]] = {"P1": None, "P2": None, "P3": None}

        # Gắn slot UI -> Engine
        self.room_tab.request_auto_create_room.connect(self._ui_auto_create)
        self.room_tab.request_auto_join_room.connect(self._ui_auto_join)
        self.room_tab.request_stop_room_task.connect(self._ui_stop_task)
        self.room_tab.request_auto_find_guest_room.connect(self._ui_auto_find_guest)

        # Nút 'Làm mới' trên RoomTab (UI yêu cầu refresh)
        if hasattr(self.room_tab, "request_refresh_room"):
            self.room_tab.request_refresh_room.connect(self._ui_refresh_room)

    # ======================================================================
    # Helper: thoát phòng bằng 2 CLICK, nghỉ ~130ms (KHÔNG block UI)
    # ======================================================================

    def _double_click_exit(self, profile_id: str) -> None:
        def _safe_click_exit(pid: str, label: str) -> None:
            try:
                self.game.click_exit_room_1(pid) if label == 'first' else self.game.click_exit_room_2(pid)
            except Exception as e:
                log.exception("RoomEngine _double_click_exit(%s, %s) failed: %s", pid, label, e)

        _safe_click_exit(profile_id, "first")
        delay_ms = int(getattr(self, "_exit_double_click_ms", 130) or 0)
        QTimer.singleShot(delay_ms, lambda pid=profile_id: _safe_click_exit(pid, "second"))

    # ======================================================================
    # UI -> Engine
    # ======================================================================

    def register_profile_uid_from_snapshot(self, profile_id: str, uid: str) -> None:
        """
        Đăng ký UID của profile từ room snapshot (cmd=202) khi cmd=100 chưa đến.
        Chỉ set nếu profile chưa có UID — không override UID đã biết từ cmd=100.
        Không gọi _purge_uid_from_snapshots để tránh xóa nhầm data phòng.
        """
        uid = str(uid or "").strip()
        if not uid:
            return
        if self._self_uid_by_profile.get(profile_id):
            return  # cmd=100 đã set rồi, không cần override
        self._self_uid_by_profile[profile_id] = uid
        self._self_uid_all.add(uid)
        log.info(
            "[SELF_UID_SNAP] %s uid=%s (inferred from room snapshot, pending cmd=100)",
            profile_id, uid,
        )

    def on_self_info_100(self, profile_id: str, payload: dict) -> None:
        """
        cmd=100: thông tin của CHÍNH profile này.
        payload ví dụ: {"uid":"1_565...", "dn":"...", "As":{"gold":20884}, "cmd":100, ...}
        """
        try:
            # Mini-game sockets also emit cmd=100, but id=1 is not the table
            # identity. Accept legacy payloads without id and table payloads
            # with id=0 only, so a mini socket cannot overwrite P1/P2/P3 UID.
            msg_id = payload.get("id")
            if msg_id is not None:
                try:
                    if int(msg_id) != 0:
                        return
                except Exception:
                    return

            uid = payload.get("uid") or payload.get("u")
            if not uid:
                return

            uid = str(uid)
            old_uid = self._self_uid_by_profile.get(profile_id)
            self._self_uid_by_profile[profile_id] = uid
            if old_uid and old_uid != uid and old_uid not in self._self_uid_by_profile.values():
                self._self_uid_all.discard(old_uid)
            self._self_uid_all.add(uid)
            # NEW: nếu trước đó UID này từng bị ghi nhầm là "khách" (do 3P vào lần lượt),
            # thì purge lại để DB/UI nhất quán.
            try:
                self._purge_uid_from_snapshots(uid)
            except Exception:
                log.exception("purge self uid in snapshots failed: uid=%s", uid)

            dn = payload.get("dn") or payload.get("a")
            gold = None
            try:
                gold = int(((payload.get("As") or {}).get("gold")))
            except Exception:
                gold = None
            if gold is not None:
                self._gold_by_uid[uid] = gold

            # log nhẹ, không spam
            log.info("[SELF_INFO] %s uid=%s dn=%s gold=%s", profile_id, uid, dn, gold)
        except Exception:
            log.exception("on_self_info_100 failed (pid=%s)", profile_id)

    def _ui_auto_create(self, profile_id: str, params: dict) -> None:
        tv = self.tac_vu[profile_id]
        tv.che_do = "create"
        tv.target_uid = None
        tv.bet_muc_tieu = params.get("bet")
        tv.delay_ms = int(params.get("delay_ms", 0))
        tv.dang_cho_ket_qua = False

        self.room_tab.dat_trang_thai_tao(
            profile_id,
            "Bắt đầu tạo phòng solo bằng click Bet (loop tới khi thành công hoặc dừng tay)...",
            dang_chay=True,
        )
        self._click_bet_tao(profile_id)

    def _ui_auto_join(self, profile_id: str, params: dict) -> None:
        tv = self.tac_vu[profile_id]
        tv.che_do = "join"
        tv.target_uid = params.get("target_uid")
        tv.bet_muc_tieu = params.get("bet")
        tv.delay_ms = int(params.get("delay_ms", 0))
        tv.dang_cho_ket_qua = False

        self.target_hien_tai[profile_id] = tv.target_uid

        self.room_tab.dat_trang_thai_join(
            profile_id,
            f"Bắt đầu vào phòng theo UID {tv.target_uid} bằng click Bet (loop tới khi tìm thấy hoặc dừng tay)...",
            dang_chay=True,
        )
        self._click_bet_join(profile_id)

    def _ui_auto_find_guest(self, profile_id: str, params: dict) -> None:
        tv = self.tac_vu[profile_id]
        tv.che_do = "find_guest"
        tv.target_uid = None
        tv.bet_muc_tieu = params.get("bet")
        tv.delay_ms = int(params.get("delay_ms", 0))  # UI đã gửi delay_create_ms
        tv.dang_cho_ket_qua = False

        # dùng API UI mới
        if hasattr(self.room_tab, "dat_trang_thai_find"):
            self.room_tab.dat_trang_thai_find(
                profile_id,
                "Bắt đầu tìm khách bằng click Bet (loop tới khi vào bàn có sẵn 1 người)...",
                dang_chay=True,
            )
        else:
            # fallback cực an toàn (nếu chưa kịp add UI)
            self.room_tab.dat_trang_thai_tao(
                profile_id,
                "Bắt đầu tìm khách (fallback hiển thị ở Tạo phòng)...",
                dang_chay=True,
            )

        self._click_bet_find_guest(profile_id)

    def _ui_stop_task(self, profile_id: str) -> None:
        tv = self.tac_vu[profile_id]
        tv.che_do = None
        tv.dang_cho_ket_qua = False

        self.room_tab.dat_trang_thai_tao(profile_id, "Đã dừng.", dang_chay=False)
        self.room_tab.dat_trang_thai_join(profile_id, "Đã dừng.", dang_chay=False)
        if hasattr(self.room_tab, "dat_trang_thai_find"):
            self.room_tab.dat_trang_thai_find(profile_id, "Đã dừng.", dang_chay=False)

        self._active_room_session.pop(profile_id, None)
        self._last_room_key[profile_id] = None

    def _ui_refresh_room(self, profile_id: str) -> None:
        """UI yêu cầu làm mới trạng thái phòng (kéo 1 snapshot cmd=202 mới)."""
        try:
            self._refresh_waiting[profile_id] = True

            st = self._last_snapshot.get(profile_id)
            bet = getattr(st, "bet", None) if st is not None else None

            # Best-effort: gọi gateway để kích hoạt server gửi lại snapshot (cmd=202)
            try:
                self.ws_gateway.yeu_cau_cap_nhat_danh_sach_phong(profile_id, bet)
            except Exception as e:
                log.debug("RoomEngine refresh: gateway request failed (%s): %s", profile_id, e)

            # Fallback an toàn: nếu không nhận được 202, push lại cache (đã throttle)
            def _fallback(pid: str = profile_id) -> None:
                try:
                    if not self._refresh_waiting.get(pid):
                        return
                    st2 = self._last_snapshot.get(pid)
                    if st2 is not None:
                        self._schedule_room_ui(pid)
                    self._refresh_waiting[pid] = False
                except Exception:
                    log.exception("RoomEngine refresh fallback failed (pid=%s)", pid)

            QTimer.singleShot(800, _fallback)

        except Exception as e:
            log.exception("RoomEngine _ui_refresh_room(%s) crashed: %s", profile_id, e)

    # ======================================================================
    # Loop click Bet
    # ======================================================================

    def _click_bet_tao(self, profile_id: str) -> None:
        tv = self.tac_vu[profile_id]
        if tv.che_do != "create":
            return

        if tv.bet_muc_tieu is None:
            self.room_tab.dat_trang_thai_tao(
                profile_id,
                "Chưa chọn mức cược (Bet) cho tác vụ tạo phòng.",
                dang_chay=False,
            )
            tv.che_do = None
            return

        tv.dang_cho_ket_qua = True
        self.room_tab.dat_trang_thai_tao(
            profile_id,
            f"Click Bet {tv.bet_muc_tieu} để thử tạo / vào phòng solo...",
            dang_chay=True,
        )

        try:
            self.game.click_bet(profile_id, tv.bet_muc_tieu)
        except Exception as e:
            self.room_tab.dat_trang_thai_tao(profile_id, f"Lỗi khi click Bet {tv.bet_muc_tieu}: {e}", dang_chay=False)
            tv.che_do = None
            tv.dang_cho_ket_qua = False

    def _click_bet_join(self, profile_id: str) -> None:
        tv = self.tac_vu[profile_id]
        if tv.che_do != "join":
            return

        if tv.bet_muc_tieu is None:
            self.room_tab.dat_trang_thai_join(
                profile_id,
                "Chưa chọn mức cược (Bet) cho tác vụ vào phòng.",
                dang_chay=False,
            )
            tv.che_do = None
            return

        tv.dang_cho_ket_qua = True
        self.room_tab.dat_trang_thai_join(
            profile_id,
            f"Click Bet {tv.bet_muc_tieu} để thử tìm phòng chứa UID mục tiêu...",
            dang_chay=True,
        )

        try:
            self.game.click_bet(profile_id, tv.bet_muc_tieu)
        except Exception as e:
            self.room_tab.dat_trang_thai_join(profile_id, f"Lỗi khi click Bet {tv.bet_muc_tieu}: {e}", dang_chay=False)
            tv.che_do = None
            tv.dang_cho_ket_qua = False

    def _click_bet_find_guest(self, profile_id: str) -> None:
        tv = self.tac_vu[profile_id]
        if tv.che_do != "find_guest":
            return

        if tv.bet_muc_tieu is None:
            if hasattr(self.room_tab, "dat_trang_thai_find"):
                self.room_tab.dat_trang_thai_find(
                    profile_id,
                    "Chưa chọn mức cược (Bet) cho tác vụ tìm khách.",
                    dang_chay=False,
                )
            tv.che_do = None
            return

        tv.dang_cho_ket_qua = True

        if hasattr(self.room_tab, "dat_trang_thai_find"):
            self.room_tab.dat_trang_thai_find(
                profile_id,
                f"Click Bet {tv.bet_muc_tieu} để thử vào bàn có sẵn 1 người...",
                dang_chay=True,
            )

        try:
            self.game.click_bet(profile_id, tv.bet_muc_tieu)
        except Exception as e:
            if hasattr(self.room_tab, "dat_trang_thai_find"):
                self.room_tab.dat_trang_thai_find(
                    profile_id,
                    f"Lỗi khi click Bet {tv.bet_muc_tieu}: {e}",
                    dang_chay=False,
                )
            tv.che_do = None
            tv.dang_cho_ket_qua = False

    # ======================================================================
    # WS -> Engine
    # ======================================================================

    def on_danh_sach_phong(self, profile_id: str, ds_phong: List[PhongLobby]) -> None:
        # Hiện chưa dùng UI lobby list => giữ nguyên (no-op)
        return

    def _make_room_key(self, st: TrangThaiPhong) -> Tuple:
        return (
            getattr(st, "room_id", None),
            getattr(st, "bet", None),
            getattr(st, "my_uid", None),
        )

    def is_room_task_active(self, profile_id: str) -> bool:
        tv = self.tac_vu.get(str(profile_id or ""))
        return bool(tv and tv.che_do in ("create", "join", "find_guest"))

    def _purge_uid_from_snapshots(self, uid: str) -> None:
        uid = str(uid or "").strip()
        if not uid:
            return

        for pid, st in list(self._last_snapshot.items()):
            if st is None:
                continue
            ds = getattr(st, "nguoi_choi", None) or []
            before = len(ds)
            ds2 = [p for p in ds if str(getattr(p, "uid", "") or "").strip() != uid]
            if len(ds2) != before:
                st.nguoi_choi = ds2
                try:
                    st.so_nguoi_hien_tai = len(ds2)
                except Exception:
                    pass
                self._schedule_room_ui(pid)

    # ======================================================================
    # Room UI throttling helpers
    # ======================================================================

    def _room_ui_signature(self, st: TrangThaiPhong) -> Tuple[Any, ...]:
        room_key = self._make_room_key(st)
        players = []
        for p in (st.nguoi_choi or []):
            uid = str(getattr(p, "uid", "") or "")
            ten = str(getattr(p, "ten", "") or "")
            vang = getattr(p, "vang", None)
            try:
                vang_i = int(vang) if vang is not None else None
            except Exception:
                vang_i = None
            players.append((uid, ten, vang_i))
        return (room_key, tuple(players), int(getattr(st, "so_nguoi_hien_tai", 0) or 0))

    def _ensure_room_ui_timer(self, profile_id: str) -> QTimer:
        t = self._room_ui_timers.get(profile_id)
        if t is not None:
            return t
        t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(80)
        t.timeout.connect(lambda pid=profile_id: self._flush_room_ui(pid))
        self._room_ui_timers[profile_id] = t
        return t

    def _schedule_room_ui(self, profile_id: str) -> None:
        self._room_ui_dirty.add(profile_id)
        timer = self._ensure_room_ui_timer(profile_id)
        if not timer.isActive():
            timer.start()

    def _flush_room_ui(self, profile_id: str) -> None:
        try:
            if profile_id not in self._room_ui_dirty:
                return
            self._room_ui_dirty.discard(profile_id)

            st = self._last_snapshot.get(profile_id)
            if st is None:
                return

            sig = self._room_ui_signature(st)
            if sig == self._room_ui_last_sig.get(profile_id):
                return
            self._room_ui_last_sig[profile_id] = sig

            target_uid = self.target_hien_tai.get(profile_id)
            self.room_tab.cap_nhat_trang_thai_phong(profile_id, st, target_uid)

        except Exception:
            log.exception("RoomEngine _flush_room_ui failed (pid=%s)", profile_id)

    # ======================================================================
    # Snapshot: cmd=202 -> update UI + baseline + ARM toast realtime
    # ======================================================================

    def _accept_room_task_snapshot(self, profile_id: str, trang_thai: TrangThaiPhong) -> None:
        self._last_room_key[profile_id] = self._make_room_key(trang_thai)
        self._last_snapshot[profile_id] = trang_thai
        self._sync_room_monitor_snapshot(profile_id, trang_thai)
        self._schedule_room_ui(profile_id)

    def _handle_room_task_snapshot(self, profile_id: str, trang_thai: TrangThaiPhong) -> None:
        tv = self.tac_vu[profile_id]
        if tv.che_do is None:
            return

        if not tv.dang_cho_ket_qua:
            return

        tv.dang_cho_ket_qua = False

        if tv.che_do == "create":
            if trang_thai.so_nguoi_hien_tai == 1 and trang_thai.my_uid:
                self._accept_room_task_snapshot(profile_id, trang_thai)
                self.room_tab.dat_trang_thai_tao(
                    profile_id,
                    f"ĐÃ TẠO PHÒNG SOLO (Room {trang_thai.room_id}, Bet {trang_thai.bet}).",
                    dang_chay=False,
                )
                tv.che_do = None
                return

            self.room_tab.dat_trang_thai_tao(
                profile_id,
                "Phòng không còn solo. Đang thoát và tìm bàn khác...",
                dang_chay=True,
            )
            self._double_click_exit(profile_id)
            total_delay = int(getattr(self, "_exit_double_click_ms", 130) or 0) + max(tv.delay_ms, 100)
            QTimer.singleShot(total_delay, lambda pid=profile_id: self._click_bet_tao(pid))
            return

        if tv.che_do == "join":
            target_uid = tv.target_uid
            if target_uid and any(p.uid == target_uid for p in (trang_thai.nguoi_choi or [])):
                self._accept_room_task_snapshot(profile_id, trang_thai)
                self.room_tab.dat_trang_thai_join(
                    profile_id,
                    f"ĐÃ VÀO ĐÚNG PHÒNG có UID {target_uid} (Room {trang_thai.room_id}, Bet {trang_thai.bet}).",
                    dang_chay=False,
                )
                tv.che_do = None
                return

            self.room_tab.dat_trang_thai_join(
                profile_id,
                f"Phòng hiện tại không có UID {target_uid}. Đang thoát và tìm lại...",
                dang_chay=True,
            )
            self._double_click_exit(profile_id)
            total_delay = int(getattr(self, "_exit_double_click_ms", 130) or 0) + max(tv.delay_ms, 100)
            QTimer.singleShot(total_delay, lambda pid=profile_id: self._click_bet_join(pid))
            return

        if tv.che_do == "find_guest":
            my_uid = str(trang_thai.my_uid or "").strip()
            self_uids = getattr(self, "_self_uid_all", set()) or set()

            other_uid = None
            for p in (trang_thai.nguoi_choi or []):
                uid = str(getattr(p, "uid", "") or "").strip()
                if uid and uid != my_uid and uid not in self_uids:
                    other_uid = uid
                    break

            if trang_thai.so_nguoi_hien_tai == 2 and my_uid and other_uid:
                self._accept_room_task_snapshot(profile_id, trang_thai)
                if hasattr(self.room_tab, "dat_trang_thai_find"):
                    self.room_tab.dat_trang_thai_find(
                        profile_id,
                        f"ĐÃ TÌM ĐƯỢC KHÁCH (Room {trang_thai.room_id}, Bet {trang_thai.bet}).",
                        dang_chay=False,
                    )
                tv.che_do = None
                return

            if hasattr(self.room_tab, "dat_trang_thai_find"):
                self.room_tab.dat_trang_thai_find(
                    profile_id,
                    "Đang thoát và tìm bàn khác...",
                    dang_chay=True,
                )
            self._double_click_exit(profile_id)
            total_delay = int(getattr(self, "_exit_double_click_ms", 130) or 0) + max(tv.delay_ms, 100)
            QTimer.singleShot(total_delay, lambda pid=profile_id: self._click_bet_find_guest(pid))

    def on_trang_thai_phong(self, profile_id: str, trang_thai: TrangThaiPhong) -> None:
        try:
            tv = self.tac_vu[profile_id]
            if tv.che_do is not None:
                self._handle_room_task_snapshot(profile_id, trang_thai)
                return

            room_key = self._make_room_key(trang_thai)
            self._last_room_key[profile_id] = room_key
            self._last_snapshot[profile_id] = trang_thai
            self._sync_room_monitor_snapshot(profile_id, trang_thai)
            self._schedule_room_ui(profile_id)

            if self._refresh_waiting.get(profile_id):
                self._refresh_waiting[profile_id] = False

        except Exception as e:
            log.exception(
                "RoomEngine.on_trang_thai_phong crashed (pid=%s, room_id=%s): %s",
                profile_id,
                getattr(trang_thai, "room_id", None),
                e,
            )

    # ======================================================================
    # Realtime: cmd=200 (join/leave) -> cập nhật snapshot cache + push UI
    # ======================================================================

    def get_self_uid(self, profile_id: str) -> Optional[str]:
        """Return the authoritative profile UID learned from cmd=100."""
        return self._self_uid_by_profile.get(str(profile_id or ""))

    def _sync_room_monitor_snapshot(self, profile_id: str, st: TrangThaiPhong) -> None:
        room_uids: set[str] = set()
        for player in (st.nguoi_choi or []):
            uid = str(getattr(player, "uid", "") or "").strip()
            if not uid:
                continue
            room_uids.add(uid)
            gold = getattr(player, "vang", None)
            try:
                if gold is not None:
                    self._gold_by_uid[uid] = int(gold)
            except Exception:
                pass
        self._room_uids_by_profile[profile_id] = room_uids
        if room_uids:
            self._emit_gold_monitor_changed(profile_id)

    def _emit_gold_monitor_changed(self, profile_id: str) -> None:
        profiles = self.get_room_monitor_state(profile_id).get("profiles") or {}
        if profiles:
            self.sig_gold_monitor_changed.emit(profiles)

    def get_room_monitor_state(self, profile_id: str) -> Dict[str, Any]:
        """Return a read-only monitoring snapshot for UI/debug consumers."""
        pid = str(profile_id or "")
        room_uids = set(self._room_uids_by_profile.get(pid) or set())
        profiles: Dict[str, Dict[str, Any]] = {}
        for profile, uid in sorted(self._self_uid_by_profile.items()):
            profiles[profile] = {
                "uid": uid,
                "gold": self._gold_by_uid.get(uid),
                "in_room": uid in room_uids,
            }
        external_uids = sorted(uid for uid in room_uids if uid not in self._self_uid_all)
        return {
            "profile_id": pid,
            "room_uids": sorted(room_uids),
            "profiles": profiles,
            "external_uids": external_uids,
            "has_external_uid": bool(external_uids),
        }

    def on_room_roster(self, profile_id: str, uids: List[Any]) -> None:
        """Update lightweight room membership from a realtime roster."""
        if not isinstance(uids, list):
            return
        room_uids = {str(uid).strip() for uid in uids if str(uid or "").strip()}
        if room_uids:
            self._room_uids_by_profile[profile_id] = room_uids

    def on_room_balance_205(self, profile_id: str, payload: Dict[str, Any]) -> None:
        """
        Update realtime table balances without refreshing rooms or triggering gameplay.

        Expected payload: {"cmd":205,"ps":[{"uid":"...","m":123}]}.
        """
        try:
            if not isinstance(payload, dict):
                return
            try:
                if int(payload.get("cmd")) != 205:
                    return
            except Exception:
                return
            players = payload.get("ps")
            if not isinstance(players, list):
                return

            realtime_players: Dict[str, int] = {}
            changed_uids: set[str] = set()
            for player in players:
                if not isinstance(player, dict):
                    continue
                uid = str(player.get("uid") or "").strip()
                if not uid or "m" not in player:
                    continue
                try:
                    gold = int(player.get("m"))
                except Exception:
                    continue
                realtime_players[uid] = gold
                if self._gold_by_uid.get(uid) != gold:
                    self._gold_by_uid[uid] = gold
                    changed_uids.add(uid)

            if not realtime_players:
                return

            # cmd=205 is authoritative for the live table roster after a hand.
            # Keep monitoring state independent from UI and gameplay logic.
            realtime_uids = set(realtime_players)
            roster_changed = realtime_uids != self._room_uids_by_profile.get(profile_id, set())
            self._room_uids_by_profile[profile_id] = realtime_uids

            for pid, st in list(self._last_snapshot.items()):
                if st is None:
                    continue
                changed = False
                for player in (st.nguoi_choi or []):
                    uid = str(getattr(player, "uid", "") or "").strip()
                    if uid not in changed_uids:
                        continue
                    gold = self._gold_by_uid.get(uid)
                    if getattr(player, "vang", None) != gold:
                        player.vang = gold
                        changed = True

                # Only mutate roster for the profile that emitted cmd=205.
                # Other profiles may currently be sitting at different tables.
                if pid == profile_id:
                    current_players = {
                        str(getattr(player, "uid", "") or "").strip(): player
                        for player in (st.nguoi_choi or [])
                        if str(getattr(player, "uid", "") or "").strip()
                    }
                    synced_players = []
                    for uid in realtime_players:
                        player = current_players.get(uid)
                        if player is None:
                            player = NguoiChoiPhong(ghe=0, uid=uid, ten="Unknown", vang=realtime_players[uid])
                        synced_players.append(player)
                    if set(current_players) != realtime_uids:
                        st.nguoi_choi = synced_players
                        st.so_nguoi_hien_tai = len(synced_players)
                        changed = True
                if changed:
                    self._schedule_room_ui(pid)

            if roster_changed:
                log.debug("[ROOM_MONITOR] %s roster=%s", profile_id, sorted(realtime_uids))
            if changed_uids:
                self._emit_gold_monitor_changed(profile_id)
        except Exception:
            log.exception("RoomEngine.on_room_balance_205 failed: pid=%s payload=%s", profile_id, payload)

    def _parse_player_from_200(self, payload: Dict[str, Any]) -> Optional[NguoiChoiPhong]:
        try:
            p = (payload or {}).get("p") or {}
            if not isinstance(p, dict):
                return None

            uid = str(p.get("uid") or "").strip()
            if not uid:
                return None

            ten = str(p.get("dn") or p.get("a") or "Unknown").strip()

            vang: Optional[int] = None
            if "m" in p:
                try:
                    vang = int(p.get("m") or 0)
                except Exception:
                    vang = 0
            else:
                As = p.get("As") or {}
                if not isinstance(As, dict) or "gold" not in As:
                    As = {}
                try:
                    vang = int(As.get("gold") or 0) if As else None
                except Exception:
                    vang = 0

            return NguoiChoiPhong(ghe=0, uid=uid, ten=ten, vang=vang)

        except Exception:
            log.exception("RoomEngine._parse_player_from_200 failed: %s", payload)
            return None

    def _upsert_player_to_snapshot(self, st: TrangThaiPhong, player: NguoiChoiPhong) -> bool:
        ds = st.nguoi_choi or []

        idx = None
        for i, p in enumerate(ds):
            if getattr(p, "uid", None) == player.uid:
                idx = i
                break

        if idx is None:
            ds.append(player)
            st.nguoi_choi = ds
            st.so_nguoi_hien_tai = len(ds)
            return True

        old = ds[idx]
        old_ten = str(getattr(old, "ten", "") or "")
        old_vang = getattr(old, "vang", None)

        new_ten = player.ten or old_ten
        new_vang = player.vang if player.vang is not None else old_vang

        changed = (new_ten != old_ten) or (new_vang != old_vang)
        if changed:
            ds[idx] = NguoiChoiPhong(ghe=getattr(old, "ghe", 0), uid=player.uid, ten=new_ten, vang=new_vang)
            st.nguoi_choi = ds

        st.so_nguoi_hien_tai = len(ds)
        return changed

    def _get_player_info_from_snapshot(self, st: TrangThaiPhong, uid: str) -> Tuple[str, int]:
        """Lấy (tên, vàng) từ snapshot hiện tại theo uid. Không raise."""
        try:
            uid = str(uid or "").strip()
            if not uid:
                return ("Unknown", 0)
            for p in (st.nguoi_choi or []):
                if str(getattr(p, "uid", "") or "") == uid:
                    name = str(getattr(p, "ten", "") or "Unknown").strip() or "Unknown"
                    gold = getattr(p, "vang", None)
                    try:
                        gold_i = int(gold) if gold is not None else 0
                    except Exception:
                        gold_i = 0
                    return (name, gold_i)
        except Exception:
            pass
        return ("Unknown", 0)

    def _remove_player_from_snapshot(self, st: TrangThaiPhong, uid: str) -> bool:
        uid = str(uid or "").strip()
        if not uid:
            return False

        ds = st.nguoi_choi or []
        before = len(ds)
        ds2 = [p for p in ds if getattr(p, "uid", None) != uid]
        if len(ds2) == before:
            return False

        st.nguoi_choi = ds2
        try:
            st.so_nguoi_hien_tai = len(ds2)
        except Exception:
            pass
        return True

    def on_room_event_200(self, profile_id: str, payload: Dict[str, Any]) -> None:
        """
        payload ví dụ:
        {"cmd":200,"t":1,"p":{"uid":"...","dn":"...","As":{"gold":...}, ...}}

        - cmd=202: baseline snapshot
        - cmd=200 t=1: join/update
        - cmd=200 t in (2,0,-1): leave
        """
        try:
            if not isinstance(payload, dict):
                return
            if payload.get("cmd") != 200:
                return

            if self.is_room_task_active(profile_id):
                return

            t = payload.get("t")

            player = self._parse_player_from_200(payload)
            if player is None:
                return

            # Monitor membership even when cmd=200 races ahead of cmd=202.
            if t == 1 or t is None:
                self._room_uids_by_profile.setdefault(profile_id, set()).add(player.uid)
                if player.vang is not None:
                    self._gold_by_uid[player.uid] = int(player.vang)
            elif t in (2, 0, -1):
                self._room_uids_by_profile.setdefault(profile_id, set()).discard(player.uid)

            st = self._last_snapshot.get(profile_id)

            # Nếu chưa có snapshot thì vẫn cho phép ghi DB khi P1 có session,
            # còn UI thì bỏ qua.
            if st is None and profile_id != "P1":
                return

            changed = False
            if t == 1 or t is None:
                # update snapshot nếu có
                if st is not None:
                    changed = self._upsert_player_to_snapshot(st, player)

            elif t in (2, 0, -1):
                if st is None:
                    return                # capture info trước khi remove để toast leave
                old_name, old_gold = self._get_player_info_from_snapshot(st, player.uid)
                changed = self._remove_player_from_snapshot(st, player.uid)
                # cập nhật seen set để lần sau nếu uid vào lại thì vẫn toast join
                if profile_id == "P1":
                    try:
                        self._p1_seen_uids.discard(player.uid)
                    except Exception:
                        pass
                # toast leave (chỉ neo P1, sau ARM)
                if changed and profile_id == "P1" and self._p1_armed:
                    try:
                        # tránh toast chính mình
                        if getattr(st, 'my_uid', None) != player.uid:
                            self.sig_player_left.emit("P1", old_name or player.ten or "Unknown", int(old_gold or 0))
                    except Exception:
                        pass
            else:
                # không đoán bừa các t khác
                changed = False

            if changed:
                self._schedule_room_ui(profile_id)

            # Toast only for join, neo P1, sau khi ARM
            if t != 1:
                return
            if profile_id != "P1":
                return
            if not self._p1_armed:
                return

            uid = player.uid
            if uid in self._p1_seen_uids:
                return
            self._p1_seen_uids.add(uid)

            gold = int(player.vang or 0)
            self.sig_player_joined.emit("P1", player.ten, gold)

        except Exception:
            log.exception("RoomEngine.on_room_event_200 failed: %s", payload)
