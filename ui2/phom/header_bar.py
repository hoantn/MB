from PySide6.QtWidgets import QLabel

class HeaderBar(QLabel):
    def update_from_store(self, store):
        """
        store: WSCardStore
        Không giả định store có last_discard
        """

        # Cách an toàn nhất: dựa vào state đã reset hay chưa
        state = getattr(store, "state", None)
        if not state:
            self.setText("🎴 ĐANG KHỞI TẠO…")
            return

        # Nếu tất cả profile đều chưa có bài → đang đầu ván
        is_new_round = True
        for st in state.profiles.values():
            if st.hand:
                is_new_round = False
                break

        if is_new_round:
            self.setText("🎴 VÁN MỚI – ĐANG CHIA BÀI…")
        else:
            self.setText("🎴 ĐANG CHƠI")
