from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import tkinter as tk
from tkinter import ttk, messagebox
import yaml

from mb_profiles.profiles_model import ProfilesStore

if TYPE_CHECKING:
    from kendz.tools.mau_binh_control_panel import MainApp


class SettingsTab(ttk.Frame):
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
            text="Cài đặt & License",
            font=("Arial", 14, "bold"),
        ).grid(row=0, column=0, sticky="w")

        body = ttk.Frame(self, padding=5)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)

        core_frame = ttk.LabelFrame(body, text="Thông tin chung", padding=5)
        core_frame.grid(row=0, column=0, sticky="ew")
        core = self.service.ctx.config.core
        ttk.Label(
            core_frame,
            text=f"Ngôn ngữ: {core.language}",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            core_frame,
            text=f"Mã game mặc định: {core.default_game_id}",
        ).grid(row=1, column=0, sticky="w")
        ttk.Label(
            core_frame,
            text=f"Cấp log: {core.log_level}",
        ).grid(row=2, column=0, sticky="w")

        lic_frame = ttk.LabelFrame(body, text="Thông tin license (tạm thời)", padding=5)
        lic_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        session = self.service.get_latest_session()
        if session is None:
            ttk.Label(
                lic_frame,
                text="Chưa có session nào trong DB. Hãy chạy kendz.main trước.",
            ).grid(row=0, column=0, sticky="w")
        else:
            ttk.Label(
                lic_frame,
                text=f"Session id: {session.id}",
            ).grid(row=0, column=0, sticky="w")
            ttk.Label(
                lic_frame,
                text=f"Bắt đầu: {session.started_at}",
            ).grid(row=1, column=0, sticky="w")
            ttk.Label(
                lic_frame,
                text=f"License key (tạm): {session.license_key or '(chưa thiết lập)'}",
            ).grid(row=2, column=0, sticky="w")

        ttk.Label(
            body,
            text="Ghi chú: Tab này mới chỉ hiển thị thông tin. Hệ thống license đầy đủ sẽ được tích hợp sau.",
            foreground="gray",
            wraplength=800,
            justify="left",
        ).grid(row=2, column=0, sticky="w", pady=(10, 0))


# ---------------------------------------------------------------------------
# MainApp với Notebook nhiều tab
# ---------------------------------------------------------------------------


