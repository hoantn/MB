# ui2/phom/profile_column.py
import re

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt

from ui2.phom.real_hand_row import RealHandRow, build_real_hand_items
from ui2.phom.player_info_box import PlayerInfoBox
from ui2.phom.card_tile_lite import resolve_card_image_path


_LIST_RE = re.compile(r"\[([0-9,\s]+)\]")


def _cards_to_img_html(ws_list: list[int]) -> str:
    parts = []
    for ws in ws_list:
        p = resolve_card_image_path(int(ws))
        if not p:
            parts.append(f"<b>{ws}</b>")
            continue
        url = "file:///" + p.replace("\\", "/")
        parts.append(
            f'<img src="{url}" width="26" height="38" '
            f'style="margin-right:4px; vertical-align:middle;">'
        )
    return "".join(parts)


def coach_text_to_rich_html(txt: str) -> str:
    """
    Convert coach text:
      - Replace [29, 30] -> <img ...> icons
      - \n -> <br>
    """
    if not txt:
        return "<div></div>"

    def repl(m):
        raw = m.group(1)
        ws_list = []
        for x in raw.split(","):
            x = x.strip()
            if x.isdigit():
                ws_list.append(int(x))
        return _cards_to_img_html(ws_list) if ws_list else m.group(0)

    s = _LIST_RE.sub(repl, txt)
    s = s.replace("\n", "<br>")
    return f"<div>{s}</div>"


class ProfileColumn(QWidget):
    """
    1 hàng UI cho mỗi Profile (P1/P2/P3)
    - Bên trái: PID + info (cố định width)
    - Bên phải: phỏm (hand_row) + coach (responsive)
    """
    def __init__(self, pid, store=None):
        super().__init__()
        self.pid = pid
        self.store = store

        # KHUNG MỜ cho profile (áp trực tiếp - không dùng selector)
        self.setStyleSheet("""
        border: 1px dashed rgba(255,255,255,80);
        border-radius: 10px;
        """)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # =========================
        # LEFT (FIXED WIDTH)
        # =========================
        left_widget = QWidget()
        left_widget.setFixedWidth(280)  # <<< mấu chốt để phần phải responsive thật

        left_layout = QHBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.pid_label = QLabel(pid)
        self.pid_label.setStyleSheet("font-weight:700;")
        self.pid_label.setFixedWidth(28)
        left_layout.addWidget(self.pid_label, 0)

        self.info_box = PlayerInfoBox()
        left_layout.addWidget(self.info_box, 1)

        root.addWidget(left_widget, 0)

        # =========================
        # RIGHT (RESPONSIVE)
        # =========================
        right_wrap = QHBoxLayout()
        right_wrap.setSpacing(10)

        # hand_row: chỉ lấy tối thiểu cần thiết
        self.hand_row = RealHandRow()
        self.hand_row.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
        right_wrap.addWidget(self.hand_row, 0)

        # coach: nở theo khoảng trống còn lại
        self.lb_coach = QLabel("")
        self.lb_coach.setTextFormat(Qt.RichText)
        self.lb_coach.setWordWrap(True)
        self.lb_coach.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.lb_coach.setStyleSheet("""
            color: rgba(255,255,255,190);
            border: 1px solid rgba(255,255,255,50);
            border-radius: 8px;
            padding: 8px;
        """)
        self.lb_coach.setMinimumWidth(220)
        # self.lb_coach.setMaximumWidth(900)
        self.lb_coach.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_wrap.addWidget(self.lb_coach, 1)

        root.addLayout(right_wrap, 1)

    def update_state(self, st):
        # reset UI (để khi chưa có bài vẫn thấy khung)
        self.hand_row.set_hand([])  # rỗng -> hiện placeholder

        if not st or not getattr(st, "analysis", None):
            self.info_box.update_state(st)
            self.lb_coach.setText("")
            return

        an = st.analysis

        # ĐÚNG CONTRACT CỦA BẠN: build_real_hand_items + set_hand
        items = build_real_hand_items(an)
        self.hand_row.set_hand(items)

        self.info_box.update_state(st)

        # Coach text
        if self.store and getattr(self.store, "build_team_coach_text", None):
            try:
                raw = self.store.build_team_coach_text(self.pid)
                self.lb_coach.setText(coach_text_to_rich_html(raw))
            except Exception:
                self.lb_coach.setText("")
        else:
            self.lb_coach.setText("")
