import tkinter as tk
from tkinter import ttk, messagebox
from PIL import ImageTk

from browser.manager import BrowserManager
from capture.capture_manager import CaptureManager
from capture.region import set_game_region, get_game_region, set_slot, get_slots


class CaptureTab(ttk.Frame):
    """
    - Vùng game: khoanh 1 lần (drag) trên full screenshot, lưu vào config.
    - Slot:
        + Dùng 1 khung chữ nhật (slot editor) có thể thay đổi W/H bằng input.
        + Click chuột để đặt vị trí, dùng nút mũi tên để fine-tune.
        + Lưu slot N: ghi tọa độ relative trong vùng game.
        + Có nút "Áp dụng size cho 13 slot": dùng chung W/H hiện tại cho mọi slot.
    """

    def __init__(self, parent, browser_manager: BrowserManager, capture_manager: CaptureManager):
        super().__init__(parent)
        self.browser_manager = browser_manager
        self.capture_manager = capture_manager

        self.profile_var = tk.StringVar(value="P1")
        self.current_image = None          # PIL.Image (full tab)
        self.tk_image = None               # ImageTk

        # canvas state
        self.mode = "idle"                 # 'idle' | 'region' | 'slot_place'
        self.drag_start = None             # (x, y) trên canvas khi drag vùng game
        self.region_rect_id = None         # id rect vùng game
        self.slot_rect_id = None           # id rect slot editor

        # vùng game (abs trong full image) trong phiên hiện tại
        self.selected_region_abs = None

        # slot editor (abs coords trong full image)
        self.slot_x = 0
        self.slot_y = 0
        self.slot_w_var = tk.IntVar(value=60)
        self.slot_h_var = tk.IntVar(value=80)

        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, pady=5)

        ttk.Label(top, text="Profile:").pack(side=tk.LEFT, padx=5)
        ttk.OptionMenu(top, self.profile_var, "P1", "P1", "P2", "P3",
                       command=lambda *_: self.load_region()).pack(side=tk.LEFT)

        ttk.Button(top, text="Chụp full tab", command=self.capture_full).pack(side=tk.LEFT, padx=5)
        ttk.Button(top, text="Bắt đầu chọn vùng game", command=self.start_select_region).pack(side=tk.LEFT, padx=5)
        ttk.Button(top, text="Lưu vùng game", command=self.save_region).pack(side=tk.LEFT, padx=5)

        # Canvas hiển thị screenshot
        self.canvas = tk.Canvas(self, bg="gray")
        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)

        # Panel cấu hình slot
        slot_frame = ttk.LabelFrame(self, text="Chỉnh slot bằng khung")
        slot_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        ttk.Label(slot_frame, text="Slot:").grid(row=0, column=0, sticky="w", padx=3, pady=2)
        self.slot_index_var = tk.IntVar(value=1)
        ttk.Spinbox(slot_frame, from_=1, to=13, width=4, textvariable=self.slot_index_var).grid(row=0, column=1, sticky="w")

        ttk.Label(slot_frame, text="W:").grid(row=0, column=2, sticky="e")
        ttk.Entry(slot_frame, textvariable=self.slot_w_var, width=6).grid(row=0, column=3, sticky="w")
        ttk.Label(slot_frame, text="H:").grid(row=0, column=4, sticky="e")
        ttk.Entry(slot_frame, textvariable=self.slot_h_var, width=6).grid(row=0, column=5, sticky="w")

        ttk.Button(slot_frame, text="Đặt vị trí bằng click",
                   command=self.start_place_slot).grid(row=0, column=6, padx=5)

        # Mũi tên fine-tune
        move_frame = ttk.Frame(slot_frame)
        move_frame.grid(row=1, column=0, columnspan=7, pady=3, sticky="w")

        ttk.Label(move_frame, text="Fine-tune:").grid(row=0, column=0, padx=3)

        ttk.Button(move_frame, text="↑", width=3,
                   command=lambda: self.move_slot(0, -1)).grid(row=0, column=1)
        ttk.Button(move_frame, text="↓", width=3,
                   command=lambda: self.move_slot(0, 1)).grid(row=1, column=1)
        ttk.Button(move_frame, text="←", width=3,
                   command=lambda: self.move_slot(-1, 0)).grid(row=1, column=0)
        ttk.Button(move_frame, text="→", width=3,
                   command=lambda: self.move_slot(1, 0)).grid(row=1, column=2)

        ttk.Button(move_frame, text="Cập nhật kích thước",
                   command=self.update_slot_size).grid(row=0, column=3, rowspan=2, padx=10)

        ttk.Button(move_frame, text="Lưu slot hiện tại",
                   command=self.save_current_slot).grid(row=0, column=4, rowspan=2, padx=10)

        ttk.Button(move_frame, text="Áp dụng size cho 13 slot",
                   command=self.apply_size_all_slots).grid(row=0, column=5, rowspan=2, padx=10)

        # nút xem cấu hình slot
        ttk.Button(self, text="Xem slot đã lưu", command=self.show_slots_info).pack(side=tk.TOP, anchor="w", padx=5, pady=3)

        self.region_label = ttk.Label(self, text="Vùng game: (chưa chọn)")
        self.region_label.pack(side=tk.TOP, anchor="w", padx=5)

        self.load_region()

    # ===================== vùng game ==========================

    def load_region(self):
        region = get_game_region(self.profile_var.get())
        if region:
            self.region_label.config(text=f"Vùng game: {region}")
            self.selected_region_abs = region
        else:
            self.region_label.config(text="Vùng game: (chưa chọn)")
            self.selected_region_abs = None
        self.redraw_overlays()

    def capture_full(self):
        img = self.capture_manager.capture_full(self.profile_var.get())
        if img is None:
            messagebox.showwarning("Capture", "Không có browser/tab để chụp")
            return
        self.current_image = img
        self.show_image_on_canvas(img)

    def show_image_on_canvas(self, img):
        w, h = img.size
        max_w, max_h = 900, 550
        scale = min(max_w / w, max_h / h, 1.0)
        disp_w, disp_h = int(w * scale), int(h * scale)
        resized = img.resize((disp_w, disp_h))
        self.tk_image = ImageTk.PhotoImage(resized)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image)
        self.canvas.config(scrollregion=(0, 0, disp_w, disp_h))
        self.canvas.image_scale = scale
        self.redraw_overlays()

    def start_select_region(self):
        if self.current_image is None:
            messagebox.showinfo("Vùng game", "Hãy chụp full tab trước")
            return
        self.mode = "region"
        self.drag_start = None

    # ===================== slot editor ========================

    def start_place_slot(self):
        if self.current_image is None:
            messagebox.showinfo("Slot", "Hãy chụp full tab trước")
            return
        if not get_game_region(self.profile_var.get()):
            messagebox.showwarning("Slot", "Cần chọn & lưu vùng game trước")
            return
        self.mode = "slot_place"
        messagebox.showinfo("Slot", "Click vào vị trí góc trên trái của lá bài để đặt khung slot.")

    def move_slot(self, dx: int, dy: int):
        if self.current_image is None:
            return
        self.slot_x += dx
        self.slot_y += dy
        self.redraw_overlays()

    def update_slot_size(self):
        # đã thay đổi self.slot_w_var / h_var → chỉ cần redraw
        self.redraw_overlays()

    def save_current_slot(self):
        region = get_game_region(self.profile_var.get())
        if not region:
            messagebox.showwarning("Slot", "Cần lưu vùng game trước")
            return
        if self.current_image is None:
            return

        w = max(5, int(self.slot_w_var.get() or 0))
        h = max(5, int(self.slot_h_var.get() or 0))

        # abs → relative trong vùng game
        rel = {
            "x": self.slot_x - region["x"],
            "y": self.slot_y - region["y"],
            "width": w,
            "height": h,
        }
        slot_index = int(self.slot_index_var.get())
        set_slot(self.profile_var.get(), slot_index, rel)
        messagebox.showinfo("Slot", f"Đã lưu slot {slot_index}: {rel}")

    def apply_size_all_slots(self):
        slots = get_slots(self.profile_var.get())
        if not slots:
            messagebox.showinfo("Slot", "Chưa có slot nào để áp dụng kích thước")
            return
        w = max(5, int(self.slot_w_var.get() or 0))
        h = max(5, int(self.slot_h_var.get() or 0))

        for i in range(1, 14):
            key = str(i)
            rect = slots.get(key)
            if not rect:
                continue
            new_rect = {
                "x": rect.get("x", 0),
                "y": rect.get("y", 0),
                "width": w,
                "height": h,
            }
            set_slot(self.profile_var.get(), i, new_rect)
        messagebox.showinfo("Slot", "Đã áp dụng kích thước hiện tại cho 13 slot (nếu tồn tại).")

    # ===================== canvas events ======================

    def on_mouse_down(self, event):
        if self.mode == "region":
            self.drag_start = (event.x, event.y)
        elif self.mode == "slot_place":
            # đặt top-left slot theo click
            if self.current_image is None:
                return
            scale = getattr(self.canvas, "image_scale", 1.0)
            img_x = int(event.x / scale)
            img_y = int(event.y / scale)
            self.slot_x = img_x
            self.slot_y = img_y
            self.redraw_overlays()

    def on_mouse_move(self, event):
        if self.mode == "region" and self.drag_start:
            x0, y0 = self.drag_start
            x1, y1 = event.x, event.y
            if self.region_rect_id:
                self.canvas.coords(self.region_rect_id, x0, y0, x1, y1)
            else:
                self.region_rect_id = self.canvas.create_rectangle(
                    x0, y0, x1, y1, outline="red", width=2, tags="overlay"
                )

    def on_mouse_up(self, event):
        if self.mode == "region" and self.drag_start and self.current_image is not None:
            x0, y0 = self.drag_start
            x1, y1 = event.x, event.y
            self.drag_start = None

            scale = getattr(self.canvas, "image_scale", 1.0)
            ix0, iy0 = int(min(x0, x1) / scale), int(min(y0, y1) / scale)
            ix1, iy1 = int(max(x0, x1) / scale), int(max(y0, y1) / scale)
            w, h = ix1 - ix0, iy1 - iy0
            if w <= 0 or h <= 0:
                return
            self.selected_region_abs = {"x": ix0, "y": iy0, "width": w, "height": h}
            self.region_label.config(text=f"Vùng game (chưa lưu): {self.selected_region_abs}")
            self.redraw_overlays()

    # ===================== lưu / hiển thị =====================

    def save_region(self):
        if not self.selected_region_abs:
            messagebox.showwarning("Vùng game", "Chưa chọn vùng nào")
            return
        set_game_region(self.profile_var.get(), self.selected_region_abs)
        self.load_region()
        messagebox.showinfo("Vùng game", f"Đã lưu vùng game: {self.selected_region_abs}")

    def show_slots_info(self):
        slots = get_slots(self.profile_var.get())
        if not slots:
            messagebox.showinfo("Slots", "Chưa có slot nào")
            return
        lines = [f"Slot {k}: {v}" for k, v in sorted(slots.items(), key=lambda x: int(x[0]))]
        messagebox.showinfo("Slots", "\n".join(lines))

    def redraw_overlays(self):
        self.canvas.delete("overlay")
        if self.current_image is None:
            return
        scale = getattr(self.canvas, "image_scale", 1.0)

        # vùng game
        region = get_game_region(self.profile_var.get())
        if region:
            x0 = int(region["x"] * scale)
            y0 = int(region["y"] * scale)
            x1 = int((region["x"] + region["width"]) * scale)
            y1 = int((region["y"] + region["height"]) * scale)
            self.canvas.create_rectangle(
                x0, y0, x1, y1, outline="green", width=2, tags="overlay"
            )

        # slot editor
        w = max(5, int(self.slot_w_var.get() or 0))
        h = max(5, int(self.slot_h_var.get() or 0))
        sx0 = int(self.slot_x * scale)
        sy0 = int(self.slot_y * scale)
        sx1 = int((self.slot_x + w) * scale)
        sy1 = int((self.slot_y + h) * scale)
        self.slot_rect_id = self.canvas.create_rectangle(
            sx0, sy0, sx1, sy1, outline="blue", width=2, tags="overlay"
        )
