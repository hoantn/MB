from __future__ import annotations

import tkinter as tk
from typing import Callable, List, Optional, Any

from kendz.vision.layout_types import CardRegion


class CardLayoutSelectorOverlay(tk.Toplevel):
    """Overlay trong suốt phủ lên cửa sổ game để chọn khung 13 lá (3-5-5).

    - Hiển thị 1 bounding box (khung viền xanh) chứa 13 ô.
    - Có thể kéo toàn khung bằng chuột trái.
    - Có thể resize bằng cách kéo 4 góc.
    - Nút "Xác nhận": trả về 13 CardRegion normalized (0..1) qua callback on_save.
    """

    HANDLE_SIZE = 8

    def __init__(
        self,
        master: tk.Misc,
        profile_id: int,
        window_info: Any,
        on_save: Callable[[List[CardRegion]], None],
    ) -> None:
        super().__init__(master)
        self.profile_id = profile_id
        self.window_info = window_info
        self.on_save = on_save

        self.overrideredirect(True)
        self.attributes("-topmost", True)

        self.config(bg="#00FF00")
        try:
            self.attributes("-transparentcolor", "#00FF00")
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(self, bg="#00FF00", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.window_x = int(getattr(window_info, "x", 0))
        self.window_y = int(getattr(window_info, "y", 0))
        self.window_w = int(getattr(window_info, "width", 1280))
        self.window_h = int(getattr(window_info, "height", 720))

        self.geometry(f"{self.window_w}x{self.window_h}+{self.window_x}+{self.window_y}")

        bw = int(self.window_w * 0.6)
        bh = int(self.window_h * 0.3)
        bx = int(self.window_w * 0.2)
        by = int(self.window_h * 0.5)

        self.box_left = bx
        self.box_top = by
        self.box_right = bx + bw
        self.box_bottom = by + bh

        self._drag_mode: Optional[str] = None
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._orig_box = (self.box_left, self.box_top, self.box_right, self.box_bottom)

        self._draw_overlay()

        self.canvas.bind("<Button-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)

        self.bind("<Escape>", lambda e: self._on_cancel())

    def _draw_overlay(self) -> None:
        self.canvas.delete("all")

        self.canvas.create_rectangle(
            self.box_left,
            self.box_top,
            self.box_right,
            self.box_bottom,
            outline="#00FF00",
            width=2,
            tags=("bbox",),
        )

        for hx, hy, tag in self._iter_handles():
            self.canvas.create_rectangle(
                hx - self.HANDLE_SIZE // 2,
                hy - self.HANDLE_SIZE // 2,
                hx + self.HANDLE_SIZE // 2,
                hy + self.HANDLE_SIZE // 2,
                fill="#00FF00",
                outline="#FFFFFF",
                width=1,
                tags=(tag, "handle"),
            )

        self._draw_grid()

        btn_w = 110
        btn_h = 26
        margin = 8
        x0 = self.window_w - btn_w - margin
        y0 = margin

        self.canvas.create_rectangle(
            x0,
            y0,
            x0 + btn_w,
            y0 + btn_h * 2 + 4,
            fill="#000000",
            outline="#FFFFFF",
            width=1,
            tags=("btn_panel",),
        )
        self.canvas.create_text(
            x0 + btn_w // 2,
            y0 + btn_h // 2,
            text="Xác nhận",
            fill="#00FF00",
            font=("Segoe UI", 9, "bold"),
            tags=("btn_confirm",),
        )
        self.canvas.create_text(
            x0 + btn_w // 2,
            y0 + btn_h + 2 + btn_h // 2,
            text="Hủy",
            fill="#FF5555",
            font=("Segoe UI", 9),
            tags=("btn_cancel",),
        )

        self.canvas.tag_bind("btn_confirm", "<Button-1>", lambda e: self._on_confirm())
        self.canvas.tag_bind("btn_cancel", "<Button-1>", lambda e: self._on_cancel())

    def _draw_grid(self) -> None:
        box_w = self.box_right - self.box_left
        box_h = self.box_bottom - self.box_top

        row_heights = [box_h / 3.0] * 3
        cols_per_row = [3, 5, 5]

        idx = 1
        for row_idx, (row_h, num_cols) in enumerate(zip(row_heights, cols_per_row)):
            row_top = self.box_top + row_idx * row_heights[0]
            cell_w = box_w / float(num_cols)

            for col in range(num_cols):
                cell_left = self.box_left + col * cell_w
                cell_right = cell_left + cell_w
                cell_bottom = row_top + row_h

                self.canvas.create_rectangle(
                    int(cell_left),
                    int(row_top),
                    int(cell_right),
                    int(cell_bottom),
                    outline="#00FF00",
                    width=1,
                    tags=("card_cell", f"card_{idx}"),
                )
                self.canvas.create_text(
                    int(cell_left) + 8,
                    int(row_top) + 8,
                    text=str(idx),
                    fill="#FFFFFF",
                    font=("Segoe UI", 8),
                    anchor="nw",
                    tags=("card_label",),
                )
                idx += 1

    def _iter_handles(self):
        yield (self.box_left, self.box_top, "handle_tl")
        yield (self.box_right, self.box_top, "handle_tr")
        yield (self.box_left, self.box_bottom, "handle_bl")
        yield (self.box_right, self.box_bottom, "handle_br")

    def _on_mouse_down(self, event: tk.Event) -> None:
        x, y = event.x, event.y
        hit = self._hit_test_handle(x, y)
        if hit:
            self._drag_mode = hit
        elif self._point_in_box(x, y):
            self._drag_mode = "move"
        else:
            self._drag_mode = None

        self._drag_start_x = x
        self._drag_start_y = y
        self._orig_box = (self.box_left, self.box_top, self.box_right, self.box_bottom)

    def _on_mouse_move(self, event: tk.Event) -> None:
        if not self._drag_mode:
            return
        dx = event.x - self._drag_start_x
        dy = event.y - self._drag_start_y

        l, t, r, b = self._orig_box

        if self._drag_mode == "move":
            self.box_left = l + dx
            self.box_top = t + dy
            self.box_right = r + dx
            self.box_bottom = b + dy
        elif self._drag_mode == "tl":
            self.box_left = l + dx
            self.box_top = t + dy
        elif self._drag_mode == "tr":
            self.box_right = r + dx
            self.box_top = t + dy
        elif self._drag_mode == "bl":
            self.box_left = l + dx
            self.box_bottom = b + dy
        elif self._drag_mode == "br":
            self.box_right = r + dx
            self.box_bottom = b + dy

        self._clamp_box()
        self._draw_overlay()

    def _on_mouse_up(self, event: tk.Event) -> None:
        self._drag_mode = None

    def _hit_test_handle(self, x: int, y: int) -> Optional[str]:
        for hx, hy, tag in self._iter_handles():
            if abs(x - hx) <= self.HANDLE_SIZE and abs(y - hy) <= self.HANDLE_SIZE:
                return tag.replace("handle_", "")
        return None

    def _point_in_box(self, x: int, y: int) -> bool:
        return self.box_left <= x <= self.box_right and self.box_top <= y <= self.box_bottom

    def _clamp_box(self) -> None:
        min_w, min_h = 50, 50
        self.box_left = max(0, min(self.box_left, self.window_w - min_w))
        self.box_top = max(0, min(self.box_top, self.window_h - min_h))
        self.box_right = max(self.box_left + min_w, min(self.box_right, self.window_w))
        self.box_bottom = max(self.box_top + min_h, min(self.box_bottom, self.window_h))

    def _on_confirm(self) -> None:
        regions = self._compute_regions_normalized()
        self.on_save(regions)
        self.destroy()

    def _on_cancel(self) -> None:
        self.destroy()

    def _compute_regions_normalized(self) -> List[CardRegion]:
        regions: List[CardRegion] = []

        box_w = self.box_right - self.box_left
        box_h = self.box_bottom - self.box_top

        row_heights = [box_h / 3.0] * 3
        cols_per_row = [3, 5, 5]

        idx = 1
        for row_idx, (row_h, num_cols) in enumerate(zip(row_heights, cols_per_row)):
            row_top = self.box_top + row_idx * row_heights[0]
            cell_w = box_w / float(num_cols)

            for col in range(num_cols):
                cell_left = self.box_left + col * cell_w
                cell_top = row_top
                cell_right = cell_left + cell_w
                cell_bottom = cell_top + row_h

                x_norm = cell_left / float(self.window_w)
                y_norm = cell_top / float(self.window_h)
                w_norm = (cell_right - cell_left) / float(self.window_w)
                h_norm = (cell_bottom - cell_top) / float(self.window_h)

                regions.append(
                    CardRegion(
                        index=idx,
                        x=x_norm,
                        y=y_norm,
                        w=w_norm,
                        h=h_norm,
                    )
                )
                idx += 1

        return regions
