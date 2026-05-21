from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Tuple

from PySide6.QtCore import Qt, QSize, QRect, QPoint, QTimer, Signal
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QFrame, QTextEdit, QSizePolicy
)


# =========================
# Data models (nhẹ, thuần UI)
# =========================

@dataclass
class PlayerInfo:
    uid: str
    ten: str
    ghe: int  # seat index 0..(seat_count-1)

@dataclass
class RolesInfo:
    dealer_uid: str
    sb_uid: str
    bb_uid: str
    lpi: List[str]  # vòng xoay UID theo thứ tự


# =========================
# Helpers
# =========================

def _uid_looks_like_game_uid(uid: str) -> bool:
    """
    UID game thường thấy dạng '1_5650...'
    Còn những chuỗi kiểu 'n9w1Eo8v' thường là id khác (web/session token).
    Ta ưu tiên UID dạng '1_' + số.
    """
    if not isinstance(uid, str):
        return False
    if uid.startswith("1_"):
        tail = uid[2:]
        return tail.isdigit()
    return False

def _short_uid(uid: str, max_len: int = 10) -> str:
    if not uid:
        return ""
    if len(uid) <= max_len:
        return uid
    return uid[:max_len - 3] + "..."


def _extract_room_id(payload: Dict[str, Any]) -> Optional[int]:
    if not isinstance(payload, dict):
        return None

    # 1) thử root
    for k in ("rid", "room_id", "roomId", "room", "r"):
        if k in payload:
            try:
                v = payload.get(k)
                if v is None or v == "":
                    continue
                return int(v)
            except Exception:
                pass

    # 2) thử payload["p"]
    p = payload.get("p")
    if isinstance(p, dict):
        for k in ("rid", "room_id", "roomId", "room", "r"):
            if k in p:
                try:
                    v = p.get(k)
                    if v is None or v == "":
                        continue
                    return int(v)
                except Exception:
                    pass

    return None

def _detect_seat_base_from_ps(ps: List[Dict[str, Any]]) -> int:
    """
    Tự nhận biết base của 'sit' trong snapshot:
    - Nếu thấy có sit=0 => 0-based
    - Ngược lại nếu tất cả sit>=1 => 1-based
    """
    try:
        sits = []
        for p in ps:
            if isinstance(p, dict) and "sit" in p:
                v = p.get("sit")
                if v is None:
                    continue
                sits.append(int(v))
        if not sits:
            return 0
        return 0 if min(sits) == 0 else 1
    except Exception:
        return 0


def _normalize_sit(raw_sit: Optional[int], base: int) -> Optional[int]:
    if raw_sit is None:
        return None
    try:
        return int(raw_sit) - int(base)
    except Exception:
        return None

def _extract_event_basic(payload: Dict[str, Any]) -> Tuple[str, str, str, Optional[int]]:
    """
    Trả về (action, uid, dn, sit)
    action: join / leave / code:<t>
    """
    if not isinstance(payload, dict):
        return ("unknown", "", "", None)

    p = payload.get("p")
    if not isinstance(p, dict):
        p = payload  # fallback root

    # action theo t
    action = "unknown"
    t = payload.get("t")
    if isinstance(t, (int, float)):
        it = int(t)
        if it == 1:
            action = "join"
        elif it == 2:
            action = "leave"
        else:
            action = f"code:{it}"

    uid = str(p.get("uid") or p.get("u") or "")
    dn = str(p.get("dn") or p.get("name") or p.get("nick") or "")
    sit = None
    if "sit" in p:
        try:
            sit = int(p.get("sit"))
        except Exception:
            sit = None

    return (action, uid, dn, sit)

# =========================
# Seat circle widget
# =========================

class SeatCircleWidget(QWidget):
    """
    Vẽ vòng tròn ghế (Seat#) + gán nhãn:
    - Ghế trống
    - Có người: tên rút gọn
    - Đánh dấu vai: D / SB / BB
    - Highlight: nếu là "mình" (my_uid) thì viền sáng
    """
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.seat_count: int = 5
        self.players_by_seat: Dict[int, PlayerInfo] = {}
        self.roles: Optional[RolesInfo] = None
        self.my_uid: Optional[str] = None

    def set_data(
        self,
        seat_count: int,
        players: List[PlayerInfo],
        roles: Optional[RolesInfo],
        my_uid: Optional[str],
    ) -> None:
        self.seat_count = max(2, int(seat_count or 5))
        self.players_by_seat = {p.ghe: p for p in players if 0 <= p.ghe < self.seat_count}
        self.roles = roles
        self.my_uid = my_uid
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(520, 240)

    def _seat_positions(self, rect: QRect) -> List[QPoint]:
        import math
        cx = rect.center().x()
        cy = rect.center().y()
        r = min(rect.width(), rect.height()) * 0.33
        pts: List[QPoint] = []
        for i in range(self.seat_count):
            ang = (-math.pi / 2) + (2 * math.pi * i / self.seat_count)
            x = cx + r * math.cos(ang)
            y = cy + r * math.sin(ang)
            pts.append(QPoint(int(x), int(y)))
        return pts

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect().adjusted(10, 10, -10, -10)

        p.fillRect(self.rect(), QColor(0, 0, 0, 0))

        center = rect.center()
        p.setPen(QPen(QColor(70, 70, 70), 2))
        p.setBrush(QBrush(QColor(30, 30, 30)))
        p.drawEllipse(center, int(min(rect.width(), rect.height()) * 0.18), int(min(rect.width(), rect.height()) * 0.18))

        pts = self._seat_positions(rect)

        seat_w, seat_h = 72, 44
        font = QFont()
        font.setPointSize(9)
        p.setFont(font)

        for seat_idx, pos in enumerate(pts):
            seat_rect = QRect(pos.x() - seat_w // 2, pos.y() - seat_h // 2, seat_w, seat_h)

            player = self.players_by_seat.get(seat_idx)
            is_me = bool(self.my_uid and player and player.uid == self.my_uid)

            p.setPen(QPen(QColor(90, 90, 90), 1))
            p.setBrush(QBrush(QColor(40, 40, 40)))
            p.drawRoundedRect(seat_rect, 10, 10)

            if is_me:
                p.setPen(QPen(QColor(180, 220, 255), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(seat_rect.adjusted(-2, -2, 2, 2), 12, 12)

            if player:
                ten = player.ten or "Người chơi"
                line1 = f"Ghế {seat_idx + 1}"
                line2 = (ten[:8] + "…") if len(ten) > 9 else ten
            else:
                line1 = f"Ghế {seat_idx + 1}"
                line2 = "trống"

            p.setPen(QPen(QColor(210, 210, 210), 1))
            p.drawText(seat_rect.adjusted(0, 2, 0, -2), Qt.AlignCenter, f"{line1}\n{line2}")

            if player and self.roles:
                badge = None
                color = None
                if player.uid == self.roles.dealer_uid:
                    badge, color = "D", QColor(80, 160, 255)
                elif player.uid == self.roles.sb_uid:
                    badge, color = "SB", QColor(255, 200, 60)
                elif player.uid == self.roles.bb_uid:
                    badge, color = "BB", QColor(255, 90, 90)

                if badge and color:
                    brect = QRect(seat_rect.right() - 34, seat_rect.top() - 10, 34, 20)
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(color))
                    p.drawRoundedRect(brect, 8, 8)
                    p.setPen(QPen(QColor(0, 0, 0), 1))
                    p.drawText(brect, Qt.AlignCenter, badge)


# =========================
# Radar panel (1 profile)
# =========================

class RadarPanel(QFrame):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("RadarPanel")
        self.setFrameShape(QFrame.StyledPanel)

        self.pid = title
        self.lbl_live = QLabel("• LIVE")
        self.lbl_live.setStyleSheet("color:#6CFFA6; font-weight:600;")

        self.lbl_table = QLabel("Bàn: —")
        self.lbl_me = QLabel("Mình: —")

        self.seat = SeatCircleWidget()

        self.lbl_next = QLabel("PHÂN VAI VÁN SẮP CHẠY (MẤT GÀ?)")
        self.lbl_next.setStyleSheet("font-weight:700;")

        self.txt_next = QLabel("—")
        self.txt_next.setWordWrap(True)

        self.lbl_hint = QLabel("KHUYẾN NGHỊ (THUẦN VIỆT)")
        self.lbl_hint.setStyleSheet("font-weight:700;")
        self.txt_hint = QLabel("—")
        self.txt_hint.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(self.lbl_live)
        top.addStretch(1)
        lay.addLayout(top)

        lay.addWidget(self.lbl_table)
        lay.addWidget(self.lbl_me)
        lay.addWidget(self.seat)

        lay.addWidget(self.lbl_next)
        lay.addWidget(self.txt_next)
        lay.addWidget(self.lbl_hint)
        lay.addWidget(self.txt_hint)

        self.setStyleSheet("""
            QFrame#RadarPanel{
                background:#1b1b1b;
                border:1px solid #2c2c2c;
                border-radius:10px;
            }
            QLabel{ color:#e6e6e6; }
        """)

    def update_view(
        self,
        seat_count: int,
        room_id: Optional[int],
        players: List[PlayerInfo],
        roles: Optional[RolesInfo],
        my_uid: Optional[str],
        my_name: Optional[str],
        next_roles: Optional[RolesInfo],
        confidence: str,
    ) -> None:
        total = len(players)
        self.lbl_table.setText(f"Bàn: Đang chơi: {total}/{seat_count}  |  Số ghế: {seat_count}  |  rid: {room_id}")
        if my_uid:
            dn = my_name or "—"
            self.lbl_me.setText(f"Mình: {dn} ({_short_uid(my_uid)})")
        else:
            self.lbl_me.setText("Mình: — (chưa xác định UID)")

        self.seat.set_data(seat_count, players, roles, my_uid)

        if next_roles and my_uid:
            will_pay = []
            if my_uid == next_roles.sb_uid:
                will_pay.append("SB (cược nhỏ)")
            if my_uid == next_roles.bb_uid:
                will_pay.append("BB (cược lớn)")
            if will_pay:
                msg = f"✅ Ván tới bạn sẽ **MẤT GÀ**: {', '.join(will_pay)}"
                hint = "Nếu muốn né mất gà: thoát bàn/đổi ghế/đợi vòng xoay qua."
            else:
                msg = "✅ Ván tới bạn **KHÔNG MẤT GÀ** (không phải SB/BB)."
                hint = "Có thể tiếp tục ngồi nếu mục tiêu là né SB/BB."
        else:
            msg = "— Chưa đủ dữ liệu để dự đoán ván tới."
            hint = "Hãy chờ snapshot (cmd=202) + phân vai (cmd=750) ổn định."

        self.txt_next.setText(f"{msg}\nĐộ tin cậy: {confidence}")
        self.txt_hint.setText(hint)


# =========================
# PokerTab (main)
# =========================

class PokerTab(QWidget):
    """
    TAB Poker (Decision Engine thuần Việt):
    - Realtime danh sách người chơi theo snapshot (cmd=202)
    - Realtime phân vai hiện tại (cmd=750)
    - Dự đoán phân vai ván tới -> mục tiêu: mình có mất gà (SB/BB) không
    - FIX: my_uid chỉ được set khi UID đó nằm trong players snapshot của bàn

    ✅ BỔ SUNG REALTIME:
    - cmd=200 (ai vào/ra phòng) -> emit yêu cầu refresh snapshot (cmd=202) để UI cập nhật ngay.
    """
    yeu_cau_lam_moi_snapshot = Signal(str)  # profile_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._state: Dict[str, Dict[str, Any]] = {
            "P1": {},
            "P2": {},
            "P3": {},
        }

        # Debounce timers per profile for cmd=200 refresh
        self._refresh_timers: Dict[str, QTimer] = {}
        self._pending_refresh: Dict[str, bool] = {"P1": False, "P2": False, "P3": False}

        # UI
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        bar = QHBoxLayout()

        self.btn_clear = QPushButton("Xóa nhật ký")
        self.btn_refresh = QPushButton("Làm mới")

        # NEW — nút đóng/mở log
        self.btn_toggle_log = QPushButton("Ẩn log")

        bar.addWidget(self.btn_clear)
        bar.addWidget(self.btn_refresh)
        bar.addWidget(self.btn_toggle_log)   # thêm dòng này
        bar.addStretch(1)

        bar.addWidget(self.btn_clear)
        bar.addWidget(self.btn_refresh)
        bar.addStretch(1)
        root.addLayout(bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.container = QWidget()
        self.hpanels = QHBoxLayout(self.container)
        self.hpanels.setContentsMargins(0, 0, 0, 0)
        self.hpanels.setSpacing(10)

        self.radar_p1 = RadarPanel("Radar P1")
        self.radar_p2 = RadarPanel("Radar P2")
        self.radar_p3 = RadarPanel("Radar P3")

        self.hpanels.addWidget(self.radar_p1)
        self.hpanels.addWidget(self.radar_p2)
        self.hpanels.addWidget(self.radar_p3)
        self.hpanels.addStretch(1)

        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        root.addWidget(self.log)

        self.btn_clear.clicked.connect(self._clear_log)
        self.btn_refresh.clicked.connect(self._manual_refresh_clicked)
        self.btn_toggle_log.clicked.connect(self._toggle_log)

        self.setStyleSheet("""
            QPushButton{
                height:28px;
                padding:0 10px;
                border-radius:6px;
                border:1px solid #2b2b2b;
                background:#222;
                color:#eee;
            }
            QPushButton:hover{ background:#2a2a2a; }
            QTextEdit{
                background:#141414;
                border:1px solid #2b2b2b;
                border-radius:8px;
                color:#ddd;
                font-family:Consolas;
                font-size:11px;
            }
        """)

    # =========================
    # cmd=200: vào/ra phòng -> trigger snapshot refresh
    # =========================

    def on_room_event_200(self, profile_id: str, payload: Dict[str, Any]) -> None:
        """
        cmd=200: biết ai vào/ra phòng.
        Mục tiêu: khi có biến động, yêu cầu engine lấy snapshot cmd=202 mới nhất để UI cập nhật realtime.
        """
        pid = str(profile_id or "P1")
        st = self._state.setdefault(pid, {})

        rid = _extract_room_id(payload)
        if rid is not None:
            st["room_id"] = rid  # update rid sớm (best-effort)

        action, uid, dn, sit = _extract_event_basic(payload)
        self._log(pid, f"[{pid}] cmd=200: {action} uid={_short_uid(uid)} dn={dn or '-'} sit={sit} rid={rid}")

        # --- NEW: cập nhật players realtime theo cmd=200 (delta) ---
        self._apply_room_delta_from_cmd200(pid, action, uid, dn, sit)

        # vẫn giữ đồng bộ snapshot (ground truth)
        self._schedule_snapshot_refresh(pid)
        
    def _apply_room_delta_from_cmd200(self, pid: str, action: str, uid: str, dn: str, sit: Optional[int]) -> None:
        """
        Apply delta seat-map:
        - join: có sit => set player vào ghế
        - leave: remove theo uid
        An toàn: nếu chưa có snapshot thì chỉ log và chờ cmd=202.
        """
        st = self._state.setdefault(pid, {})
        players: List[PlayerInfo] = st.get("players") or []
        seat_count = int(st.get("seat_count") or 0)

        # nếu chưa có snapshot (seat_count=0), không đủ dữ liệu để vẽ seat chuẩn
        if seat_count <= 0:
            return

        changed = False
        # NEW: normalize sit theo base đã detect từ snapshot
        base = int(st.get("sit_base", 0) or 0)

        if sit is not None:
            sit = _normalize_sit(sit, base)

        if action == "join" and uid and sit is not None and 0 <= sit < seat_count:
            # 1) xóa uid cũ nếu đang ở ghế khác
            new_players = [p for p in players if p.uid != uid]
            # 2) xóa ai đang ngồi ghế sit (trường hợp server đổi người)
            new_players = [p for p in new_players if p.ghe != sit]
            # 3) add người mới
            new_players.append(PlayerInfo(uid=uid, ten=dn, ghe=int(sit)))
            players = new_players
            changed = True

        elif action == "leave" and uid:
            new_players = [p for p in players if p.uid != uid]
            if len(new_players) != len(players):
                players = new_players
                changed = True

        if changed:
            st["players"] = players
            st["uids_in_room"] = set([p.uid for p in players])
            self.refresh_ui()

    def _schedule_snapshot_refresh(self, pid: str) -> None:
        """
        Debounce để tránh spam refresh khi cmd=200 bắn nhiều lần.
        """
        pid = str(pid or "P1")
        if pid not in self._pending_refresh:
            self._pending_refresh[pid] = False

        self._pending_refresh[pid] = True

        t = self._refresh_timers.get(pid)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda _pid=pid: self._emit_snapshot_refresh(_pid))
            self._refresh_timers[pid] = t

        # Reset timer mỗi lần nhận cmd200 (gom nhiều event thành 1 refresh)
        t.start(250)

    def _emit_snapshot_refresh(self, pid: str) -> None:
        pid = str(pid or "P1")
        if not self._pending_refresh.get(pid):
            return
        self._pending_refresh[pid] = False
        self._log(pid, f"[{pid}] 🔄 Yêu cầu refresh snapshot (cmd=202) do biến động cmd=200")
        self.yeu_cau_lam_moi_snapshot.emit(pid)

    def _manual_refresh_clicked(self) -> None:
        """
        Nút 'Làm mới' trên PokerTab: yêu cầu refresh snapshot cho cả 3 profile.
        """
        for pid in ("P1", "P2", "P3"):
            self._schedule_snapshot_refresh(pid)

    # =========================
    # Public API called by main.py
    # =========================

    def on_room_snapshot(self, profile_id: str, payload: Dict[str, Any]) -> None:
        """
        cmd=202: snapshot phòng, có ps: [{uid,dn,sit,...}]
        """
        pid = str(profile_id or "P1")
        st = self._state.setdefault(pid, {})

        ps = payload.get("ps") or []
        if not isinstance(ps, list):
            return

        seat_count = int(payload.get("Mu", 5) or 5)
        room_id = _extract_room_id(payload)

        players: List[PlayerInfo] = []
        uids_in_room: List[str] = []

        for p in ps:
            if not isinstance(p, dict):
                continue
            uid = str(p.get("uid", "") or "")
            dn = str(p.get("dn", "") or "")
            # NEW: tự detect base của sit từ snapshot
            base = _detect_seat_base_from_ps(ps)
            st["sit_base"] = base

            raw_sit = p.get("sit", None)
            sit = _normalize_sit(raw_sit, base)

            if uid and sit is not None and 0 <= sit < seat_count:
                players.append(PlayerInfo(uid=uid, ten=dn, ghe=sit))
                uids_in_room.append(uid)

        st["room_id"] = room_id
        st["seat_count"] = seat_count
        st["players"] = players
        st["uids_in_room"] = set(uids_in_room)

        my_uid = st.get("my_uid")
        if my_uid and my_uid not in st["uids_in_room"]:
            st["my_uid_confirmed"] = False
        elif my_uid and my_uid in st["uids_in_room"]:
            st["my_uid_confirmed"] = True

        self._log(pid, f"[{pid}] Snapshot phòng: rid={room_id} ghế={seat_count} người={len(players)}")
        self.refresh_ui()

    def on_poker_roles(self, profile_id: str, payload: Dict[str, Any]) -> None:
        """
        cmd=750: phân vai hiện tại
        payload ví dụ: {"cmd":750,"D":"1_..","sb":{"uid":"1_.."},"bb":{"uid":"1_.."},"lpi":[...]}
        """
        pid = str(profile_id or "P1")
        st = self._state.setdefault(pid, {})

        dealer_uid = str(payload.get("D", "") or "")
        sb = payload.get("sb") or {}
        bb = payload.get("bb") or {}
        sb_uid = str((sb.get("uid") if isinstance(sb, dict) else "") or "")
        bb_uid = str((bb.get("uid") if isinstance(bb, dict) else "") or "")
        lpi = payload.get("lpi") or []
        if not isinstance(lpi, list):
            lpi = []

        st["roles"] = RolesInfo(dealer_uid=dealer_uid, sb_uid=sb_uid, bb_uid=bb_uid, lpi=[str(x) for x in lpi])

        self._log(pid, f"[{pid}] Nhận phân vai: D={_short_uid(dealer_uid)} SB={_short_uid(sb_uid)} BB={_short_uid(bb_uid)} (lpi={len(lpi)})")
        self.refresh_ui()

    def on_self_info(self, profile_id: str, payload: Dict[str, Any]) -> None:
        """
        cmd=100: self info
        FIX: chỉ chấp nhận my_uid nếu uid này thực sự nằm trong snapshot của bàn (uids_in_room).
        Nếu chưa có snapshot, tạm lưu candidate nhưng KHÔNG overwrite "my_uid ổn định".
        """
        pid = str(profile_id or "P1")
        st = self._state.setdefault(pid, {})

        uid = str(payload.get("uid", "") or "")
        dn = str(payload.get("dn", "") or "")

        if not uid:
            return

        st["my_name"] = dn or st.get("my_name")

        uids_in_room = st.get("uids_in_room")
        if isinstance(uids_in_room, set) and len(uids_in_room) > 0:
            if uid in uids_in_room:
                old = st.get("my_uid")
                st["my_uid"] = uid
                st["my_uid_confirmed"] = True
                if old != uid:
                    self._log(pid, f"[{pid}] ✅ Self UID CONFIRM trong bàn: my_uid={uid}")
            else:
                st["my_uid_candidate"] = uid
                st["my_uid_confirmed"] = bool(st.get("my_uid") in uids_in_room)
                self._log(pid, f"[{pid}] ⛔ Bỏ qua self uid ngoài bàn: {uid} (candidate)")
                return
        else:
            if _uid_looks_like_game_uid(uid) and not st.get("my_uid"):
                st["my_uid"] = uid
                st["my_uid_confirmed"] = False
                self._log(pid, f"[{pid}] (tạm) Self UID dạng game: my_uid={uid} (chưa confirm snapshot)")
            else:
                st["my_uid_candidate"] = uid
                self._log(pid, f"[{pid}] (candidate) Self uid={uid}")

        self.refresh_ui()

    # =========================
    # Decision Engine (ván tới)
    # =========================

    def _predict_next_roles(self, roles: Optional[RolesInfo]) -> Optional[RolesInfo]:
        """
        cmd=750: phân vai của ván hiện tại/đang chạy.
        Dự đoán ván KẾ TIẾP: dealer dịch 1 người theo vòng lpi.
        next_dealer = next(lpi, dealer)
        next_sb = next(lpi, next_dealer)
        next_bb = next(lpi, next_sb)
        """
        if not roles:
            return None

        lpi = roles.lpi or []
        if not lpi or roles.dealer_uid not in lpi:
            # Không đủ dữ liệu để rotate -> fallback (độ tin cậy sẽ thấp)
            return roles

        n = len(lpi)
        try:
            di = lpi.index(roles.dealer_uid)
        except ValueError:
            return roles

        next_dealer = lpi[(di + 1) % n]
        next_sb = lpi[(di + 2) % n]
        next_bb = lpi[(di + 3) % n]

        return RolesInfo(
            dealer_uid=next_dealer,
            sb_uid=next_sb,
            bb_uid=next_bb,
            lpi=lpi,
        )

    def _confidence(self, st: Dict[str, Any]) -> str:
        roles: Optional[RolesInfo] = st.get("roles")
        players: List[PlayerInfo] = st.get("players") or []
        if not roles:
            return "THẤP"
        if players and roles.lpi and roles.dealer_uid in roles.lpi:
            return "CAO"
        return "TRUNG BÌNH"

    # =========================
    # UI update
    # =========================

    def refresh_ui(self) -> None:
        for pid, radar in (("P1", self.radar_p1), ("P2", self.radar_p2), ("P3", self.radar_p3)):
            st = self._state.get(pid) or {}
            seat_count = int(st.get("seat_count") or 5)
            room_id = st.get("room_id")
            players: List[PlayerInfo] = st.get("players") or []
            roles: Optional[RolesInfo] = st.get("roles")
            my_uid = st.get("my_uid")
            my_name = st.get("my_name")
            next_roles = self._predict_next_roles_from_seats(st) or self._predict_next_roles(roles)
            conf = self._confidence(st)

            radar.update_view(
                seat_count=seat_count,
                room_id=room_id,
                players=players,
                roles=roles,
                my_uid=my_uid,
                my_name=my_name,
                next_roles=next_roles,
                confidence=conf
            )

    # =========================
    # Logging
    # =========================

    def _log(self, pid: str, msg: str) -> None:
        try:
            self.log.append(msg)
        except Exception:
            pass

    def _clear_log(self) -> None:
        try:
            self.log.clear()
        except Exception:
            pass
    def _toggle_log(self) -> None:
        """
        Toggle hiển thị log panel.
        Không destroy widget để tránh repaint lag.
        """
        visible = self.log.isVisible()
        self.log.setVisible(not visible)

        if visible:
            self.btn_toggle_log.setText("Hiện log")
        else:
            self.btn_toggle_log.setText("Ẩn log")
            
    def _predict_next_roles_from_seats(self, st: Dict[str, Any]) -> Optional[RolesInfo]:
        roles: Optional[RolesInfo] = st.get("roles")
        players: List[PlayerInfo] = st.get("players") or []
        seat_count = int(st.get("seat_count") or 0)

        if not roles or not players or seat_count <= 0:
            return None

        # map uid -> seat
        uid2seat = {p.uid: p.ghe for p in players}
        if roles.dealer_uid not in uid2seat:
            return None

        occupied = sorted({p.ghe for p in players})
        if len(occupied) < 2:
            return None

        def next_occupied(after_seat: int) -> int:
            # tìm ghế có người kế tiếp theo vòng
            for step in range(1, seat_count + 1):
                s = (after_seat + step) % seat_count
                if s in occupied:
                    return s
            return after_seat

        dealer_seat = uid2seat[roles.dealer_uid]
        next_dealer_seat = next_occupied(dealer_seat)

        # heads-up (2 người)
        if len(occupied) == 2:
            sb_seat = next_dealer_seat  # dealer = SB
            bb_seat = next_occupied(sb_seat)
        else:
            sb_seat = next_occupied(next_dealer_seat)
            bb_seat = next_occupied(sb_seat)

        # seat -> uid
        seat2uid = {p.ghe: p.uid for p in players}
        return RolesInfo(
            dealer_uid=seat2uid.get(next_dealer_seat, ""),
            sb_uid=seat2uid.get(sb_seat, ""),
            bb_uid=seat2uid.get(bb_seat, ""),
            lpi=roles.lpi or [],
        )
