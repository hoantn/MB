# ui2/phom/main_view.py
from PySide6.QtWidgets import QWidget, QVBoxLayout

from ui2.phom.header_bar import HeaderBar
from ui2.phom.profile_column import ProfileColumn
from ui2.phom.unseen_row import UnseenRow


class PhomMainView(QWidget):
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.rows = {}  # <-- FIX: thiếu self.rows sẽ gây lỗi khi refresh()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(1)

        # Header (chỉ add 1 lần)
        self.header = HeaderBar()
        root.addWidget(self.header, 0)

        # Unseen row: slider là chính (ăn nhiều height hơn)
        self.unseen_row = UnseenRow(self.store)
        root.addWidget(self.unseen_row, 2)

        # 3 profile rows
        for pid in ("P1", "P2", "P3"):
            row = ProfileColumn(pid, store=self.store)
            self.rows[pid] = row
            root.addWidget(row, 1)

        # spacer cuối: để layout co giãn ổn định
        root.addStretch(1)

    def refresh(self):
        self.header.update_from_store(self.store)

        if self.unseen_row:
            self.unseen_row.update_from_store()

        for pid, row in self.rows.items():
            st = self.store.state.get_profile(pid)
            row.update_state(st)
