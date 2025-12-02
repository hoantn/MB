from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import io

import tkinter as tk
from tkinter import ttk

from kendz.database.models import SessionModel, RoundModel, HandModel

if TYPE_CHECKING:
    from kendz.tools.mau_binh_control_panel import MainApp


class LogsHistoryTab(ttk.Frame):
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
            text="Nhật ký & Lịch sử",
            font=("Arial", 14, "bold"),
        ).grid(row=0, column=0, sticky="w")

        paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        log_frame = ttk.LabelFrame(paned, text="Log gần đây", padding=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_frame,
            height=10,
            state="disabled",
            font=("Consolas", 9),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        btn_reload_log = ttk.Button(
            log_frame,
            text="Tải lại log",
            command=self.reload_log,
        )
        btn_reload_log.grid(row=1, column=0, sticky="w", pady=(5, 0))
        paned.add(log_frame, weight=2)

        hist_frame = ttk.LabelFrame(paned, text="Lịch sử ván chơi gần đây", padding=5)
        hist_frame.columnconfigure(0, weight=1)
        hist_frame.rowconfigure(0, weight=1)
        self.hist_text = tk.Text(
            hist_frame,
            height=8,
            state="disabled",
            font=("Consolas", 9),
        )
        self.hist_text.grid(row=0, column=0, sticky="nsew")
        btn_reload_hist = ttk.Button(
            hist_frame,
            text="Tải lại lịch sử",
            command=self.reload_history,
        )
        btn_reload_hist.grid(row=1, column=0, sticky="w", pady=(5, 0))
        paned.add(hist_frame, weight=1)

        self.reload_log()
        self.reload_history()

    def reload_log(self) -> None:
        text = self.service.get_log_tail(200)
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", text)
        self.log_text.configure(state="disabled")

    def reload_history(self) -> None:
        rounds = self.service.get_recent_rounds(20)
        buf = io.StringIO()
        if not rounds:
            buf.write("Chưa có dữ liệu round trong DB.\n")
        else:
            for r, hands in rounds:
                buf.write(
                    f"- Round #{r.id} | game={r.game_id} | profile_session={r.session_id} "
                    f"| started_at={r.started_at} | status={r.result_status}\n"
                )
                for h in hands:
                    who = (
                        "Đối thủ"
                        if h.is_opponent
                        else f"Profile {h.profile_id or '?'}"
                    )
                    buf.write(
                        f"    + {who}: {h.raw_cards_str} | chi1={h.arranged_chi1} | "
                        f"chi2={h.arranged_chi2} | chi3={h.arranged_chi3}\n"
                    )
                buf.write("\n")

        text = buf.getvalue()
        self.hist_text.configure(state="normal")
        self.hist_text.delete("1.0", "end")
        self.hist_text.insert("end", text)
        self.hist_text.configure(state="disabled")


# ---------------------------------------------------------------------------
# Tab: Cài đặt & License
# ---------------------------------------------------------------------------


