from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

# Hàm format mã lá bài sang dạng hiển thị 2♠/2♥ và màu chữ
def format_card_pretty(code: str) -> tuple[str, str]:
    """Trả về (display, color) cho mã lá bài.

    - code: dạng 'AS', 'TH', '2D', ...
    - display: dạng 'A♠', 'T♥', ...
    - color: 'red' cho H/D, 'black' cho S/C.
    Nếu code không hợp lệ, trả về (code_gốc, 'black').
    """
    code = (code or "").upper().strip()
    if len(code) != 2:
        return code, "black"
    rank, suit = code[0], code[1]
    sym_map = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
    symbol = sym_map.get(suit)
    if not symbol:
        return code, "black"
    display = f"{rank}{symbol}"
    color = "red" if suit in ("H", "D") else "black"
    return display, color


class CardSlot(tk.Frame):
    """
    Ô hiển thị 1 lá bài: ảnh + mã (2♣/2♦/2♥/2♠).
    Dùng cho cả tab "Chơi trực tiếp" và lưới 52 lá ở tab "Lá bài & Vision".
    Có thể bật/tắt trạng thái chọn để vẽ viền xanh.

    Với tab "Chơi trực tiếp":
    - Các ô của P1/P2/P3 sẽ ưu tiên hiển thị ảnh lá bài đã được crop realtime
      từ thư mục data/runtime/self_cards/profile_{id}/slot_{index}.png.
    - Các ô của Đối thủ và các tab khác vẫn dùng ảnh template gốc.
    """

    def __init__(
        self,
        parent: tk.Widget,
        *,
        master_widget: tk.Widget,
        service,
        profile_id: Optional[int] = None,
        slot_index: Optional[int] = None,
        runtime_self_cards: bool = False,
        is_opponent: bool = False,
    ) -> None:
        super().__init__(
            parent,
            borderwidth=0,
            highlightthickness=2,
            highlightbackground="#cccccc",
            highlightcolor="#cccccc",
            bg="#ffffff",
        )
        self.service = service
        self.master_widget = master_widget

        # metadata để quyết định dùng ảnh runtime hay template
        self.profile_id = profile_id
        self.slot_index = slot_index
        self.runtime_self_cards = runtime_self_cards
        self.is_opponent = is_opponent

        self.columnconfigure(0, weight=1)

        self.image_label = ttk.Label(self)
        self.image_label.grid(row=0, column=0, sticky="n", pady=(0, 2))

        self.text_label = ttk.Label(
            self,
            text="",
            font=("Arial", 9),
        )
        self.text_label.grid(row=1, column=0, sticky="s")

        self._img_ref: Optional[tk.PhotoImage] = None
        self._selected: bool = False

    def clear(self) -> None:
        self._img_ref = None
        self.image_label.configure(image="")
        self.text_label.configure(text="")

    def set_card(self, code: str, *, dim_if_missing: bool = False, has_templates: bool = True) -> None:
        """Cập nhật lá bài cho ô.

        - Với các ô P1/P2/P3 (runtime_self_cards=True):
          + Ưu tiên lấy ảnh từ data/runtime/self_cards/profile_{id}/slot_{index}.png
            thông qua service.get_runtime_self_card_image(...).
          + Nếu chưa có ảnh runtime thì fallback về template gốc theo mã lá.
        - Với các ô khác (Đối thủ, lưới 52 lá):
          + Dùng template gốc theo mã lá.
        """
        code = code or ""
        display, color = format_card_pretty(code)

        img: Optional[tk.PhotoImage] = None

        # P1/P2/P3: ưu tiên ảnh runtime
        if self.runtime_self_cards and self.profile_id is not None and self.slot_index is not None:
            if hasattr(self.service, "get_runtime_self_card_image"):
                img = self.service.get_runtime_self_card_image(
                    self.master_widget,
                    profile_id=self.profile_id,
                    slot_index=self.slot_index,
                )

        # Nếu chưa có ảnh runtime (hoặc không dùng runtime) -> template gốc
        if img is None:
            img = self.service.get_card_image(self.master_widget, code)

        if img is not None:
            self._img_ref = img
            self.image_label.configure(image=img)
        else:
            self._img_ref = None
            self.image_label.configure(image="")

        if dim_if_missing and not has_templates:
            self.text_label.configure(text=display, foreground="gray")
        else:
            self.text_label.configure(text=display, foreground=color)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        color = "#2ecc71" if selected else "#cccccc"
        self.configure(highlightbackground=color, highlightcolor=color)
