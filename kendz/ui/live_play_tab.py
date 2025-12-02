from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

from kendz.ui.cards_widgets import CardSlot
from kendz.ui.card_layout_selector_overlay import CardLayoutSelectorOverlay
from kendz.vision.layout_manager import LayoutManager
from kendz.vision.layout_types import CardRegion

if TYPE_CHECKING:
    from kendz.tools.mau_binh_control_panel import MainApp
    from kendz.tools.mau_binh_control_panel import ScanResult


class LivePlayTab(ttk.Frame):
    """Tab chính: chơi trực tiếp.

    - 3 profile P1/P2/P3 hiển thị 13 lá bằng ảnh quét realtime (runtime/self_cards).
    - Hàng Đối thủ hiển thị lá bài template gốc.
    - Nút "Chọn tọa độ lá bài" cho từng profile -> overlay chọn khung 13 lá.
    """

    def __init__(self, parent: ttk.Notebook, app: "MainApp") -> None:
        super().__init__(parent)
        self.app = app
        self.service = app.service  # MBBrowserService

        # LayoutManager dùng chung, gắn lên app để các nơi khác tái sử dụng
        project_root = app.project_root
        if hasattr(app, "layout_manager"):
            self.layout_manager: LayoutManager = app.layout_manager
        else:
            self.layout_manager = LayoutManager(project_root)
            app.layout_manager = self.layout_manager

        self.profile_controls: Dict[int, ttk.Labelframe] = {}
        self.card_slots: Dict[str, List[CardSlot]] = {}
        self.result_vars: Dict[int, tk.StringVar] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=5)
        header.grid(row=0, column=0, sticky="nsew")
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=1)
        header.columnconfigure(2, weight=1)

        ttk.Label(
            header,
            text="Chơi trực tiếp – 3 profile + đối thủ",
            font=("Arial", 11, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        left = ttk.Frame(paned, padding=5)
        left.columnconfigure(0, weight=1)
        paned.add(left, weight=1)

        for idx, pid in enumerate([1, 2, 3], start=0):
            lf = ttk.Labelframe(left, text=f"Profile {pid}", padding=5)
            lf.grid(row=idx, column=0, sticky="nsew", pady=(0, 5))
            lf.columnconfigure(0, weight=1)
            self.profile_controls[pid] = lf

            btn_attach = ttk.Button(
                lf,
                text="Gắn cửa sổ",
                command=lambda p=pid: self._run_thread(self.attach_window, p),
            )
            btn_attach.grid(row=0, column=0, sticky="ew", padx=5, pady=2)

            btn_scan = ttk.Button(
                lf,
                text="Quét bài (không kéo)",
                command=lambda p=pid: self._run_thread(self.scan_profile, p),
            )
            btn_scan.grid(row=1, column=0, sticky="ew", padx=5, pady=2)

            btn_auto = ttk.Button(
                lf,
                text="Xếp & kéo tự động",
                command=lambda p=pid: self._run_thread(self.auto_drag_profile, p),
            )
            btn_auto.grid(row=2, column=0, sticky="ew", padx=5, pady=2)

            # Nút chọn tọa độ lá bài (overlay)
            btn_layout = ttk.Button(
                lf,
                text="Chọn tọa độ lá bài",
                command=lambda p=pid: self._open_layout_overlay(p),
            )
            btn_layout.grid(row=3, column=0, sticky="ew", padx=5, pady=2)

            status_var = tk.StringVar(value="Chưa gắn cửa sổ")
            lbl = ttk.Label(lf, textvariable=status_var, font=("Arial", 9))
            lbl.grid(row=4, column=0, sticky="w", padx=5, pady=(4, 2))
            lf._status_var = status_var  # type: ignore[attr-defined]

        right = ttk.Frame(paned, padding=5)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=3)
        right.rowconfigure(1, weight=1)
        paned.add(right, weight=3)

        board = ttk.LabelFrame(right, text="Bàn bài (13 lá)", padding=5)
        board.grid(row=0, column=0, sticky="nsew")
        for r in range(4):
            board.rowconfigure(r, weight=1)
        for c in range(14):
            board.columnconfigure(c, weight=1)

        row_names = ["Đối thủ", "P1", "P2", "P3"]
        row_keys = ["opponent", "p1", "p2", "p3"]

        for r, (name, key) in enumerate(zip(row_names, row_keys)):
            ttk.Label(
                board,
                text=name,
                font=("Arial", 10, "bold"),
            ).grid(row=r, column=0, sticky="w")

            slots_row: List[CardSlot] = []
            for c in range(13):
                profile_id: Optional[int] = None
                runtime_self_cards = False
                is_opponent = False

                if key == "p1":
                    profile_id = 1
                    runtime_self_cards = True
                elif key == "p2":
                    profile_id = 2
                    runtime_self_cards = True
                elif key == "p3":
                    profile_id = 3
                    runtime_self_cards = True
                elif key == "opponent":
                    is_opponent = True

                slot = CardSlot(
                    board,
                    master_widget=self,
                    service=self.service,
                    profile_id=profile_id,
                    slot_index=c + 1,
                    runtime_self_cards=runtime_self_cards,
                    is_opponent=is_opponent,
                )
                slot.grid(row=r, column=c + 1, sticky="nsew", padx=1, pady=1)
                slots_row.append(slot)

            self.card_slots[key] = slots_row

        result = ttk.LabelFrame(right, text="Kết quả xếp bài", padding=5)
        result.grid(row=1, column=0, sticky="nsew", pady=(5, 0))
        result.columnconfigure(0, weight=1)
        result.columnconfigure(1, weight=1)
        result.columnconfigure(2, weight=1)

        for idx, pid in enumerate([1, 2, 3], start=0):
            var = tk.StringVar(value=f"Profile {pid + 1}: chưa có dữ liệu.")
            self.result_vars[pid + 1] = var
            lbl = ttk.Label(
                result,
                textvariable=var,
                justify="left",
                wraplength=400,
            )
            lbl.grid(row=0, column=idx, sticky="nw", padx=5)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _run_thread(self, fn, profile_id: int) -> None:
        import threading

        t = threading.Thread(target=fn, args=(profile_id,), daemon=True)
        t.start()

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def attach_window(self, profile_id: int) -> None:
        lf = self.profile_controls[profile_id]
        status_var: tk.StringVar = lf._status_var  # type: ignore[attr-defined]
        self.app.set_status(f"Profile {profile_id}: đang gắn cửa sổ...")
        try:
            # Gắn cửa sổ game cho profile này thông qua MBBrowserService
            bound = self.service.bind_window(profile_id)
            ok = bound is not None

            if ok:
                status_var.set("Đã gắn cửa sổ")
                self.app.set_status(f"Profile {profile_id}: đã gắn cửa sổ.")
            else:
                status_var.set("Không tìm thấy cửa sổ game")
                self.app.set_status(f"Profile {profile_id}: không tìm thấy cửa sổ.")
        except Exception as exc:
            status_var.set("Lỗi gắn cửa sổ")
            self.app.set_status(f"Profile {profile_id}: lỗi gắn cửa sổ: {exc}")
            raise

    def scan_profile(self, profile_id: int) -> None:
        lf = self.profile_controls[profile_id]
        status_var: tk.StringVar = lf._status_var  # type: ignore[attr-defined]
        self.app.set_status(f"Profile {profile_id}: đang quét bài (không kéo)...")
        try:
            res = self.service.scan_profile(profile_id)
            self.update_profile_cards(profile_id, res)
            status_var.set("Quét bài thành công")
            self.app.set_status(f"Profile {profile_id}: quét bài xong.")
        except Exception as exc:
            status_var.set("Lỗi quét bài")
            self.app.set_status(f"Profile {profile_id}: lỗi quét bài: {exc}")

    def auto_drag_profile(self, profile_id: int) -> None:
        lf = self.profile_controls[profile_id]
        status_var: tk.StringVar = lf._status_var  # type: ignore[attr-defined]
        self.app.set_status(f"Profile {profile_id}: đang quét, xếp & kéo...")
        try:
            res = self.service.auto_drag_profile(profile_id, live=True)
            self.update_profile_cards(profile_id, res)
            status_var.set("Đã xếp & kéo xong")
            self.app.set_status(f"Profile {profile_id}: đã xếp & kéo xong.")
        except Exception as exc:
            status_var.set("Lỗi xếp & kéo")
            self.app.set_status(f"Profile {profile_id}: lỗi xếp & kéo: {exc}")

    def update_profile_cards(self, profile_id: int, result: "ScanResult") -> None:
        key = f"p{profile_id}"
        slots = self.card_slots.get(key, [])
        for idx in range(13):
            code = result.codes[idx] if idx < len(result.codes) else ""
            if idx < len(slots):
                slots[idx].set_card(code)

        var = self.result_vars.get(profile_id)
        if var is not None:
            var.set(result.pretty_summary)

    # ------------------------------------------------------------------ #
    # Overlay chọn tọa độ lá bài
    # ------------------------------------------------------------------ #
    def _open_layout_overlay(self, profile_id: int) -> None:
        # 1) Đảm bảo đã bind window cho profile này
        service = self.app.service
        bound = service._bound_windows.get(profile_id)
        if bound is None:
            bound = service.bind_window(profile_id)

        # 2) Lấy thông tin cửa sổ (left, top, width, height)
        left = getattr(bound, "left", None)
        top = getattr(bound, "top", None)
        right = getattr(bound, "right", None)
        bottom = getattr(bound, "bottom", None)
        rect = getattr(bound, "rect", None)

        if rect is not None and isinstance(rect, tuple) and len(rect) == 4:
            left, top, right, bottom = rect

        if None in (left, top, right, bottom):
            messagebox.showerror(
                "Lỗi",
                "Không lấy được toạ độ cửa sổ trình duyệt.\nHãy chắc chắn cửa sổ đang hiển thị.",
            )
            return

        width = int(right - left)
        height = int(bottom - top)

        window_info = {
            "left": int(left),
            "top": int(top),
            "width": width,
            "height": height,
        }

        # 3) Mở overlay 3-5-5
        overlay = CardLayoutSelectorOverlay(
            root=self.app.root,
            project_root=self.app.project_root,
            game_id=service.game_id,
            profile_id=profile_id,
            window_info=window_info,
            layout_manager_cls=LayoutManager,
        )
        overlay.show_modal()
