# ui2/phom/player_info_box.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

def _style_tag(play_for: str) -> str:
    # P1/P2/P3 xanh dương, OPP đỏ
    if play_for in ("P1", "P2", "P3"):
        return "color: rgb(70,140,255); font-weight: 700;"
    return "color: rgb(235,80,80); font-weight: 700;"

class PlayerInfoBox(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setMinimumWidth(220)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(2)

        self.lb_name = QLabel("Tên : -")
        self.lb_gold = QLabel("Tiền: -")
        self.lb_uid  = QLabel("UID : -")
        self.lb_play = QLabel("Đánh: -")

        for lb in (self.lb_name, self.lb_gold, self.lb_uid, self.lb_play):
            lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
            root.addWidget(lb)

        # khung nhẹ, không phá layout
        self.setStyleSheet("""
            border: 1px solid rgba(255,255,255,60);
            border-radius: 8px;
        """)

    def update_state(self, st) -> None:
        dn = getattr(st, "my_dn", None) or "-"
        uid = getattr(st, "my_uid", None) or "-"
        gold = getattr(st, "my_gold", None)
        gold_txt = f"{gold:,}" if isinstance(gold, int) else "-"

        play_for = getattr(st, "play_for", "OPP") or "OPP"
        play_text = "Đánh cho đối thủ" if play_for == "OPP" else f"Đánh cho {play_for}"

        self.lb_name.setText(f"Tên : {dn}")
        self.lb_gold.setText(f"Tiền: {gold_txt}")
        self.lb_uid.setText(f"UID : {uid}")

        self.lb_play.setText(f"Đánh: {play_text}")
        self.lb_play.setStyleSheet(_style_tag(play_for))
