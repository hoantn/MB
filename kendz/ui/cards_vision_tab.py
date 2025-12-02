from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Hỗ trợ Drag & Drop (nếu có thư viện tkinterdnd2)
try:
    from tkinterdnd2 import DND_FILES  # type: ignore
    DND_AVAILABLE = True
except Exception:  # thư viện không có -> vẫn chạy nhưng tắt DnD
    DND_FILES = None  # type: ignore
    DND_AVAILABLE = False


from kendz.ui.cards_widgets import CardSlot, format_card_pretty
from kendz.vision.pipeline import capture_and_crop_self_cards
from kendz.tools.assist_profile1 import recognize_13_cards

if TYPE_CHECKING:
    from kendz.tools.mau_binh_control_panel import MainApp


class CardsVisionTab(ttk.Frame):
    RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K"]
    SUITS = [("S", "♠"), ("H", "♥"), ("D", "♦"), ("C", "♣")]

    def __init__(self, parent: ttk.Notebook, app: "MainApp") -> None:
        super().__init__(parent)
        self.app = app
        self.service = app.service

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.selected_code: Optional[str] = None
        self._selected_img_ref: Optional[tk.PhotoImage] = None

        header = ttk.Frame(self, padding=5)
        header.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            header,
            text="Lá bài & Vision",
            font=("Arial", 14, "bold"),
        ).grid(row=0, column=0, sticky="w")

        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        # Trái: lưới 52 lá
        left = ttk.Frame(paned, padding=5)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        paned.add(left, weight=2)

        ttk.Label(left, text="Danh sách 52 lá (dạng bài thật)", font=("Arial", 11, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        grid = ttk.Frame(left)
        grid.grid(row=1, column=0, sticky="nsew", pady=(5, 0))
        for r in range(1 + len(self.SUITS)):
            grid.rowconfigure(r, weight=1)
        for c in range(1 + len(self.RANKS)):
            grid.columnconfigure(c, weight=1)
        self.grid = grid

        ttk.Label(grid, text="").grid(row=0, column=0)
        for c, rank in enumerate(self.RANKS, start=1):
            ttk.Label(grid, text=rank, font=("Arial", 9, "bold")).grid(row=0, column=c)

        self.card_grid_slots: Dict[str, CardSlot] = {}

        for r, (suit_code, suit_symbol) in enumerate(self.SUITS, start=1):
            ttk.Label(
                grid,
                text=suit_symbol,
                font=("Arial", 10, "bold"),
            ).grid(row=r, column=0, sticky="w")
            for c, rank in enumerate(self.RANKS, start=1):
                code = f"{rank}{suit_code}"
                slot = CardSlot(
                    grid,
                    master_widget=self,
                    service=self.service,
                )
                slot.grid(row=r, column=c, sticky="nsew", padx=1, pady=1)
                self.card_grid_slots[code] = slot
                slot.bind("<Button-1>", lambda e, cd=code: self.on_card_clicked(cd))
                slot.image_label.bind("<Button-1>", lambda e, cd=code: self.on_card_clicked(cd))
                slot.text_label.bind("<Button-1>", lambda e, cd=code: self.on_card_clicked(cd))

        # Phải: info + import + vision
        right = ttk.Frame(paned, padding=5)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        paned.add(right, weight=3)

        info_frame = ttk.LabelFrame(right, text="Thông tin lá & biến thể", padding=5)
        info_frame.grid(row=0, column=0, sticky="ew")
        info_frame.columnconfigure(0, weight=1)

        self.selected_label_var = tk.StringVar(value="Chưa chọn lá nào.")
        self.selected_label = ttk.Label(
            info_frame,
            textvariable=self.selected_label_var,
        )
        self.selected_label.grid(row=0, column=0, sticky="w")

        self.selected_image_label = ttk.Label(info_frame)
        self.selected_image_label.grid(row=1, column=0, sticky="w", pady=(3, 3))

        self.variants_label_var = tk.StringVar(value="")
        ttk.Label(
            info_frame,
            textvariable=self.variants_label_var,
            foreground="gray",
            wraplength=500,
            justify="left",
        ).grid(row=2, column=0, sticky="w", pady=(3, 0))

        import_frame = ttk.LabelFrame(right, text="Nhập thêm biến thể", padding=5)
        import_frame.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        import_frame.columnconfigure(0, weight=1)

        ttk.Label(
            import_frame,
            text="Chọn lá bên trái, sau đó thêm ảnh PNG cho biến thể mới.",
        ).grid(row=0, column=0, sticky="w")

        btn_add = ttk.Button(
            import_frame,
            text="Thêm biến thể (chọn file PNG...)",
            command=self.add_variants_via_dialog,
        )
        btn_add.grid(row=1, column=0, sticky="w", pady=(3, 3))

        drop_text = (
            "Kéo & thả file PNG vào đây để thêm biến thể cho lá đang chọn."
            if DND_AVAILABLE
            else "Kéo & thả yêu cầu cài thư viện tkinterdnd2.\nHiện tại bạn vẫn có thể dùng nút 'Thêm biến thể'."
        )
        self.drop_frame = ttk.Frame(import_frame, relief="solid", padding=10)
        self.drop_frame.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        ttk.Label(
            self.drop_frame,
            text=drop_text,
            wraplength=450,
            justify="left",
        ).grid(row=0, column=0, sticky="w")
        if DND_AVAILABLE:
            self.drop_frame.drop_target_register(DND_FILES)  # type: ignore
            self.drop_frame.dnd_bind("<<Drop>>", self.on_drop_files)  # type: ignore

        vision_frame = ttk.LabelFrame(right, text="Công cụ Vision", padding=5)
        vision_frame.grid(row=2, column=0, sticky="nsew", pady=(5, 0))
        vision_frame.columnconfigure(0, weight=1)
        vision_frame.rowconfigure(2, weight=1)

        ttk.Label(vision_frame, text="Profile:").grid(row=0, column=0, sticky="w")
        self.vision_profile_var = tk.IntVar(value=1)
        profile_entry = ttk.Spinbox(
            vision_frame,
            from_=1,
            to=3,
            textvariable=self.vision_profile_var,
            width=5,
        )
        profile_entry.grid(row=0, column=1, sticky="w", padx=(5, 10))

        ttk.Button(
            vision_frame,
            text="Chụp & cắt 13 lá (lưu vào thư mục vision_cards)",
            command=self.capture_and_crop,
        ).grid(row=0, column=2, sticky="w")

        ttk.Button(
            vision_frame,
            text="Nhận diện 13 lá từ crop (log ra file)",
            command=self.recognize_from_crops,
        ).grid(row=0, column=3, sticky="w", padx=(5, 0))

        self.info_text = tk.Text(
            vision_frame,
            height=8,
            state="disabled",
            font=("Consolas", 9),
        )
        self.info_text.grid(row=2, column=0, columnspan=4, sticky="nsew", pady=(5, 0))

        # Khởi tạo lưới + mặc định chọn lá đầu tiên (AS)
        self.refresh_templates_and_grid()
        default_code = f"{self.RANKS[0]}{self.SUITS[0][0]}"  # AS
        self.selected_code = default_code
        self.update_selected_info()
        self._update_grid_selection()

    # ----- Helper hiển thị -----
    def append_info(self, text: str) -> None:
        self.info_text.configure(state="normal")
        self.info_text.insert("end", text + "\n")
        self.info_text.see("end")
        self.info_text.configure(state="disabled")

    def clear_info(self) -> None:
        self.info_text.configure(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.configure(state="disabled")

    def refresh_templates_and_grid(self) -> None:
        stats = self.service.get_templates_stats()
        for code, slot in self.card_grid_slots.items():
            has_templates = stats.get(code, 0) > 0
            slot.set_card(code, dim_if_missing=True, has_templates=has_templates)
        if self.selected_code:
            self.update_selected_info()
            self._update_grid_selection()

    def _update_grid_selection(self) -> None:
        for code, slot in self.card_grid_slots.items():
            slot.set_selected(code == self.selected_code)

    def on_card_clicked(self, code: str) -> None:
        self.selected_code = code
        self.update_selected_info()
        self._update_grid_selection()

    def update_selected_info(self) -> None:
        if not self.selected_code:
            self.selected_label_var.set("Chưa chọn lá nào.")
            self.selected_label.configure(foreground="black")
            self.variants_label_var.set("")
            self.selected_image_label.configure(image="")
            self._selected_img_ref = None
            return
        code = self.selected_code
        display, color = format_card_pretty(code)
        self.selected_label_var.set(f"Lá đang chọn: {display}")
        self.selected_label.configure(foreground=color)

        img = self.service.get_card_image(self, code)
        if img is not None:
            self._selected_img_ref = img
            self.selected_image_label.configure(image=img)
        else:
            self._selected_img_ref = None
            self.selected_image_label.configure(image="")

        variants = self.service.list_card_variants(code)
        count = len(variants)
        if count == 0:
            self.variants_label_var.set(
                "Chưa có biến thể nào. Nên thêm 2–3 ảnh với các điều kiện ánh sáng khác nhau."
            )
        else:
            names = ", ".join(sorted(p.name for p in variants))
            self.variants_label_var.set(
                f"Số biến thể: {count} | Danh sách: {names}"
            )

    # ----- Import biến thể -----
    def _ensure_card_selected(self) -> Optional[str]:
        if not self.selected_code:
            messagebox.showinfo("Thông báo", "Hãy bấm chọn một lá trong lưới 52 lá bên trái trước.")
            return None
        return self.selected_code

    def add_variants_via_dialog(self) -> None:
        code = self._ensure_card_selected()
        if not code:
            return
        paths = filedialog.askopenfilenames(
            title=f"Chọn file PNG cho lá {code}",
            filetypes=[("PNG images", "*.png")],
        )
        if not paths:
            return
        added = 0
        errors: List[str] = []
        for p in paths:
            try:
                self.service.add_card_variant_from_file(code, Path(p))
                added += 1
            except Exception as exc:
                errors.append(f"{p}: {exc}")
        self.service.clear_card_image_cache()
        self.refresh_templates_and_grid()
        self.app.set_status(f"Đã thêm {added} biến thể mới cho lá {code}.")
        if errors:
            self.app.append_event("Một số file không import được:")
            for line in errors:
                self.app.append_event("  " + line)

    def on_drop_files(self, event) -> None:
        code = self._ensure_card_selected()
        if not code:
            return
        raw = event.data
        if not raw:
            return
        paths: List[str] = []
        for part in raw.split():
            part = part.strip()
            if not part:
                continue
            if part.startswith("{") and part.endswith("}"):
                part = part[1:-1]
            paths.append(part)
        if not paths:
            return
        added = 0
        errors: List[str] = []
        for p in paths:
            try:
                self.service.add_card_variant_from_file(code, Path(p))
                added += 1
            except Exception as exc:
                errors.append(f"{p}: {exc}")
        self.service.clear_card_image_cache()
        self.refresh_templates_and_grid()
        self.app.set_status(f"[DnD] Đã thêm {added} biến thể mới cho lá {code}.")
        if errors:
            self.app.append_event("Một số file kéo thả không import được:")
            for line in errors:
                self.app.append_event("  " + line)

    # ----- Vision tools -----
    def capture_and_crop(self) -> None:
        profile_id = int(self.vision_profile_var.get())
        self.app.set_status(
            f"Vision: đang chụp & cắt 13 lá cho profile {profile_id}..."
        )

        def worker() -> None:
            try:
                capture_and_crop_self_cards(self.app.service.ctx, profile_id=profile_id)
                self.app.set_status(
                    f"Vision: chụp & cắt xong cho profile {profile_id}. "
                    "Kiểm tra thư mục data/vision_cards/..."
                )
            except Exception as exc:
                self.app.report_error(exc)

        threading.Thread(target=worker, daemon=True).start()

    def recognize_from_crops(self) -> None:
        profile_id = int(self.vision_profile_var.get())
        self.app.set_status(
            f"Vision: đang nhận diện 13 lá từ crop cho profile {profile_id}..."
        )

        def worker() -> None:
            try:
                codes = recognize_13_cards(
                    self.app.service.project_root,
                    self.app.service.game_id,
                    profile_id,
                    self.app.service.logger,
                )
                self.app.set_status(
                    f"Vision: profile {profile_id} → {', '.join(codes)}"
                )
                self.clear_info()
                self.append_info(f"Kết quả nhận diện cho profile {profile_id}:")
                self.append_info(" ".join(codes))
            except Exception as exc:
                self.app.report_error(exc)

        threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Tab: Chiến lược & Engine
# ---------------------------------------------------------------------------


