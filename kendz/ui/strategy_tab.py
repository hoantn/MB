from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import tkinter as tk
from tkinter import ttk, messagebox

from kendz.engine.assistant import suggest_for_13_cards
from kendz.automation.mau_binh_click_plan import build_drag_plan_for_mau_binh
from kendz.browser.devtools_mouse import perform_drag_plan_via_devtools

if TYPE_CHECKING:
    from kendz.tools.mau_binh_control_panel import MainApp


class StrategyTab(ttk.Frame):
    def __init__(self, parent: ttk.Notebook, app: "MainApp") -> None:
        super().__init__(parent)
        self.app = app
        self.service = app.service

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=5)
        header.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            header,
            text="Chiến lược & Engine",
            font=("Arial", 14, "bold"),
        ).grid(row=0, column=0, sticky="w")

        body = ttk.Frame(self, padding=5)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)

        ttk.Label(body, text="Chế độ chiến lược toàn hệ thống:").grid(
            row=0, column=0, sticky="w"
        )

        self.mode_var = tk.StringVar(value=self.service.get_strategy_mode())

        modes = [
            ("An toàn (safe)", "safe"),
            ("Cân bằng (balance)", "balance"),
            ("Tấn công (aggressive)", "aggressive"),
        ]
        mode_frame = ttk.Frame(body)
        mode_frame.grid(row=1, column=0, sticky="w", pady=(2, 10))
        for label, val in modes:
            ttk.Radiobutton(
                mode_frame,
                text=label,
                variable=self.mode_var,
                value=val,
            ).pack(side="left", padx=(0, 10))

        ttk.Button(
            body,
            text="Áp dụng chiến lược",
            command=self.apply_strategy,
        ).grid(row=2, column=0, sticky="w")

        test_frame = ttk.LabelFrame(body, text="Thử xếp bài với 13 lá bất kỳ", padding=5)
        test_frame.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        test_frame.columnconfigure(0, weight=1)
        test_frame.rowconfigure(3, weight=1)

        ttk.Label(
            test_frame,
            text="Nhập 13 lá (cách nhau bởi khoảng trắng), ví dụ: AS KH QD JC TS 9H 8D 7C 6S 5H 4D 3C 2S",
        ).grid(row=0, column=0, sticky="w")
        self.cards_entry = ttk.Entry(test_frame)
        self.cards_entry.grid(row=1, column=0, sticky="ew", pady=(2, 5))

        ttk.Button(
            test_frame,
            text="Xếp bài",
            command=self.test_engine,
        ).grid(row=2, column=0, sticky="w")

        self.engine_result = tk.Text(
            test_frame,
            height=6,
            state="disabled",
            font=("Consolas", 9),
        )
        self.engine_result.grid(row=3, column=0, sticky="nsew", pady=(5, 0))

    def apply_strategy(self) -> None:
        mode = self.mode_var.get()
        self.service.set_strategy_mode(mode)
        self.app.set_status(f"Đã áp dụng chiến lược: {mode}")

    def test_engine(self) -> None:
        raw = self.cards_entry.get().strip()
        if not raw:
            messagebox.showinfo("Thông báo", "Hãy nhập 13 lá.")
            return
        codes = raw.split()
        if len(codes) != 13:
            messagebox.showinfo(
                "Thông báo", f"Cần đúng 13 lá, hiện có {len(codes)}."
            )
            return
        try:
            suggestion = suggest_for_13_cards(codes)
        except Exception as exc:
            self.app.report_error(exc)
            return

        chi1 = list(suggestion.chi1)
        chi2 = list(suggestion.chi2)
        chi3 = list(suggestion.chi3)

        chi1_str = " ".join(chi1)
        chi2_str = " ".join(chi2)
        chi3_str = " ".join(chi3)

        desc = (
            "Chi 1: " + chi1_str
            + " | Chi 2: " + chi2_str
            + " | Chi 3: " + chi3_str
        )

        text = (
            "Kết quả xếp bài:\n"
            f"Chi 1: {chi1_str}\n"
            f"Chi 2: {chi2_str}\n"
            f"Chi 3: {chi3_str}\n\n"
            f"Mô tả: {desc}\n"
        )
        self.engine_result.configure(state="normal")
        self.engine_result.delete("1.0", "end")
        self.engine_result.insert("end", text)
        self.engine_result.configure(state="disabled")


# ---------------------------------------------------------------------------
# Tab: Nhật ký & Lịch sử
# ---------------------------------------------------------------------------


