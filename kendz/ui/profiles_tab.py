from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

import threading

import tkinter as tk
from tkinter import ttk, messagebox

from mb_profiles.profiles_model import (
    ProfilesStore,
    ProfileConfig,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
    DEFAULT_PROXY_TYPE,
)
from mb_profiles.browser_manager import BrowserManager

if TYPE_CHECKING:
    from kendz.tools.mau_binh_control_panel import MainApp


class ProfilesTab(ttk.Frame):
    """Tab "Hồ sơ & trình duyệt" tích hợp hệ thống profiles.json + BrowserManager.

    - Mỗi hồ sơ tương ứng với một profile key: P1, P2, P3.
    - Cấu hình lưu tại config/profiles.json (ProfilesStore).
    - user-data-dir mặc định đồng bộ với project: <project_root>/user_data/P1..P3.
    - Proxy có 3 loại: none / http / socks5.
    - Zoom (%) điều khiển kích thước cửa sổ vật lý (width/height) theo tỉ lệ 1280x720.
    - start_url (trang web mặc định) được cấu hình riêng cho từng hồ sơ.
    - Lưu lịch sử gắn proxy + mở trình duyệt vào logs/proxy_history.csv và hiển thị trong UI.
    """

    PROFILE_KEYS = ("P1", "P2", "P3")

    def __init__(self, parent: ttk.Notebook, app: "MainApp") -> None:
        super().__init__(parent)
        self.app = app
        self.service = app.service  # MBBrowserService

        self.project_root = self.service.project_root
        profiles_path = self.project_root / "config" / "profiles.json"

        self.store = ProfilesStore(profiles_path)
        self.browser_manager = BrowserManager()

        # Load profiles from JSON, đảm bảo luôn có P1, P2, P3
        self.profiles: Dict[str, ProfileConfig] = self.store.load()
        for key in self.PROFILE_KEYS:
            if key not in self.profiles:
                self.profiles[key] = ProfileConfig(
                    key=key,
                    name=f"Profile {key[-1]}",
                )

        self.current_key = "P1"

        # Tk variables
        self.profile_choice = tk.StringVar(value="P1")
        self.name_var = tk.StringVar()
        self.path_var = tk.StringVar()
        self.start_url_var = tk.StringVar()
        self.proxy_type_var = tk.StringVar(value=DEFAULT_PROXY_TYPE)
        self.proxy_host_var = tk.StringVar()
        self.proxy_port_var = tk.StringVar()
        self.proxy_user_var = tk.StringVar()
        self.proxy_pass_var = tk.StringVar()
        self.zoom_var = tk.IntVar(value=100)

        self.history_text: tk.Text | None = None

        self._build_ui()
        self._load_to_form("P1")
        self._load_proxy_history_to_widget()

    # ------------------------ UI layout ------------------------
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=5)
        header.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            header,
            text="Hồ sơ & trình duyệt",
            font=("Arial", 14, "bold"),
        ).grid(row=0, column=0, sticky="w")

        main = ttk.Frame(self, padding=5)
        main.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        main.rowconfigure(3, weight=1)

        # Dòng chọn hồ sơ
        top = ttk.Frame(main)
        top.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
        ttk.Label(top, text="Chọn hồ sơ:", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="w")
        cb = ttk.Combobox(
            top,
            textvariable=self.profile_choice,
            values=list(self.PROFILE_KEYS),
            state="readonly",
            width=8,
        )
        cb.grid(row=0, column=1, sticky="w", padx=(5, 20))
        cb.bind("<<ComboboxSelected>>", self._on_profile_changed)

        self.current_name_label = ttk.Label(top, text="", foreground="gray")
        self.current_name_label.grid(row=0, column=2, sticky="w")

        # Khung form cấu hình
        form = ttk.Frame(main)
        form.grid(row=1, column=0, sticky="nsew")
        form.columnconfigure(1, weight=1)

        r = 0
        ttk.Label(form, text="Tên hồ sơ:").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.name_var).grid(row=r, column=1, sticky="ew", pady=2)
        r += 1

        ttk.Label(form, text="Profile path / user-data-dir:").grid(row=r, column=0, sticky="w", pady=2)
        path_frame = ttk.Frame(form)
        path_frame.grid(row=r, column=1, sticky="ew", pady=2)
        path_frame.columnconfigure(0, weight=1)
        ttk.Entry(path_frame, textvariable=self.path_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(path_frame, text="Chọn...", command=self._browse_profile_path).grid(row=0, column=1, padx=2)
        ttk.Button(path_frame, text="Dùng mặc định", command=self._set_default_profile_path).grid(row=0, column=2, padx=2)
        ttk.Button(path_frame, text="Mở thư mục", command=self._open_profile_path_in_explorer).grid(row=0, column=3, padx=2)
        r += 1

        ttk.Label(form, text="Trang web mặc định:").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.start_url_var).grid(row=r, column=1, sticky="ew", pady=2)
        r += 1

        ttk.Label(form, text="Loại proxy:").grid(row=r, column=0, sticky="w", pady=2)
        proxy_type_cb = ttk.Combobox(
            form,
            textvariable=self.proxy_type_var,
            values=["none", "http", "socks5"],
            state="readonly",
            width=10,
        )
        proxy_type_cb.grid(row=r, column=1, sticky="w", pady=2)
        r += 1

        ttk.Label(form, text="Proxy host:").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.proxy_host_var).grid(row=r, column=1, sticky="ew", pady=2)
        r += 1

        ttk.Label(form, text="Proxy port:").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.proxy_port_var, width=10).grid(row=r, column=1, sticky="w", pady=2)
        r += 1

        ttk.Label(form, text="Proxy username:").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.proxy_user_var).grid(row=r, column=1, sticky="ew", pady=2)
        r += 1

        ttk.Label(form, text="Proxy password:").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.proxy_pass_var, show="*").grid(row=r, column=1, sticky="ew", pady=2)
        r += 1

        ttk.Label(
            form,
            text=f"Kích thước chuẩn: {DEFAULT_WIDTH} x {DEFAULT_HEIGHT} (tỉ lệ gốc)",
            foreground="#555",
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 2))
        r += 1

        ttk.Label(form, text="Zoom (% cửa sổ):").grid(row=r, column=0, sticky="w", pady=2)
        zoom_spin = ttk.Spinbox(
            form,
            from_=50,
            to=200,
            increment=10,
            textvariable=self.zoom_var,
            width=8,
        )
        zoom_spin.grid(row=r, column=1, sticky="w", pady=2)
        r += 1

        # Khung nút hành động
        actions = ttk.Frame(main)
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=0)
        actions.columnconfigure(1, weight=0)
        actions.columnconfigure(2, weight=0)
        actions.columnconfigure(3, weight=1)

        ttk.Button(actions, text="Lưu cấu hình", command=self._on_save_clicked).grid(row=0, column=0, padx=3)
        ttk.Button(actions, text="Test proxy", command=self._on_test_proxy_clicked).grid(row=0, column=1, padx=3)
        ttk.Button(actions, text="Mở trình duyệt", command=self._on_open_clicked).grid(row=0, column=2, padx=3)
        ttk.Button(actions, text="Đóng trình duyệt", command=self._on_close_clicked).grid(row=0, column=3, padx=3, sticky="w")

        # Khung lịch sử proxy
        history_frame = ttk.LabelFrame(main, text="Lịch sử proxy & mở trình duyệt (gần đây)")
        history_frame.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        history_frame.columnconfigure(0, weight=1)
        history_frame.rowconfigure(0, weight=1)

        txt = tk.Text(history_frame, height=6, wrap="none")
        scroll = ttk.Scrollbar(history_frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        txt.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        txt.configure(state="disabled")
        self.history_text = txt

    # ------------------------ Helpers ------------------------

    def _proxy_history_path(self) -> Path:
        path = self.project_root / "logs" / "proxy_history.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _append_proxy_history_to_file(self, cfg: ProfileConfig, status: str, message: str) -> None:
        path = self._proxy_history_path()
        is_new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(
                    [
                        "timestamp",
                        "profile",
                        "start_url",
                        "proxy_type",
                        "proxy_host",
                        "proxy_port",
                        "proxy_username",
                        "status",
                        "message",
                    ]
                )
            writer.writerow(
                [
                    datetime.now().isoformat(timespec="seconds"),
                    cfg.key,
                    (cfg.start_url or ""),
                    (cfg.proxy_type or ""),
                    (cfg.proxy_host or ""),
                    (cfg.proxy_port or ""),
                    (cfg.proxy_username or ""),
                    status,
                    message,
                ]
            )

    def _append_proxy_history_to_widget(self, cfg: ProfileConfig, status: str, message: str) -> None:
        if not self.history_text:
            return
        line = (
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"{cfg.key} {cfg.proxy_type or 'none'} "
            f"{cfg.proxy_host}:{cfg.proxy_port} "
            f"start={cfg.start_url or ''} -> {status} ({message})"
        )
        txt = self.history_text
        txt.configure(state="normal")
        txt.insert("end", line + "\n")
        txt.see("end")
        txt.configure(state="disabled")

    def _load_proxy_history_to_widget(self) -> None:
        path = self._proxy_history_path()
        if not path.exists() or not self.history_text:
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return
        if len(lines) <= 1:
            return
        entries = lines[1:][-50:]  # bỏ header, chỉ lấy 50 dòng gần nhất

        txt = self.history_text
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        for line in entries:
            parts = line.split(",")
            # đơn giản hóa hiển thị
            ts = parts[0] if len(parts) > 0 else ""
            profile = parts[1] if len(parts) > 1 else ""
            start_url = parts[2] if len(parts) > 2 else ""
            proxy_type = parts[3] if len(parts) > 3 else ""
            host = parts[4] if len(parts) > 4 else ""
            port = parts[5] if len(parts) > 5 else ""
            status = parts[7] if len(parts) > 7 else ""
            msg = parts[8] if len(parts) > 8 else ""
            display = (
                f"[{ts}] {profile} {proxy_type} {host}:{port} "
                f"start={start_url} -> {status} ({msg})"
            )
            txt.insert("end", display + "\n")
        txt.see("end")
        txt.configure(state="disabled")

    def _on_profile_changed(self, event=None) -> None:
        key = self.profile_choice.get() or "P1"
        if key not in self.PROFILE_KEYS:
            key = "P1"
            self.profile_choice.set(key)
        self._save_current_to_memory()
        self.current_key = key
        self._load_to_form(key)

    def _load_to_form(self, key: str) -> None:
        cfg = self.profiles[key]
        self.name_var.set(cfg.name)
        self.path_var.set(cfg.chrome_profile_path)
        self.start_url_var.set(cfg.start_url or "")
        self.proxy_type_var.set((cfg.proxy_type or DEFAULT_PROXY_TYPE).lower())
        self.proxy_host_var.set(cfg.proxy_host)
        self.proxy_port_var.set(cfg.proxy_port)
        self.proxy_user_var.set(cfg.proxy_username)
        self.proxy_pass_var.set(cfg.proxy_password)
        self.zoom_var.set(int(cfg.zoom_percent or 100))
        self.current_name_label.config(text=f"Tên: {cfg.name}")

    def _save_current_to_memory(self) -> None:
        key = self.current_key
        if key not in self.PROFILE_KEYS:
            return
        cfg = self.profiles.get(key)
        if cfg is None:
            cfg = ProfileConfig(key=key, name=f"Profile {key[-1]}")
        proxy_type = (self.proxy_type_var.get() or DEFAULT_PROXY_TYPE).lower()
        if proxy_type not in ("none", "http", "socks5"):
            proxy_type = DEFAULT_PROXY_TYPE
        updated = ProfileConfig(
            key=key,
            name=self.name_var.get().strip() or cfg.name,
            chrome_profile_path=self.path_var.get().strip(),
            proxy_type=proxy_type,
            proxy_host=self.proxy_host_var.get().strip(),
            proxy_port=self.proxy_port_var.get().strip(),
            proxy_username=self.proxy_user_var.get().strip(),
            proxy_password=self.proxy_pass_var.get(),
            start_url=self.start_url_var.get().strip() or DEFAULT_START_URL,
            window_width=DEFAULT_WIDTH,
            window_height=DEFAULT_HEIGHT,
            zoom_percent=int(self.zoom_var.get() or 100),
        )
        self.profiles[key] = updated

    def _default_profile_dir_for_key(self, key: str) -> Path:
        base = self.project_root
        target = base / "user_data" / key
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return target

    def _set_default_profile_path(self) -> None:
        key = self.current_key
        target = self._default_profile_dir_for_key(key)
        self.path_var.set(str(target))

    def _open_profile_path_in_explorer(self) -> None:
        import subprocess
        import sys
        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning("Mở thư mục", "Chưa có đường dẫn user-data-dir.")
            return
        if not Path(path).is_dir():
            messagebox.showwarning("Mở thư mục", f"Thư mục không tồn tại:\n{path}")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showwarning("Mở thư mục", f"Không mở được thư mục:\n{path}\n\nLỗi: {exc}")

    def _browse_profile_path(self) -> None:
        path = filedialog.askdirectory(
            title="Chọn thư mục user-data-dir cho profile",
            mustexist=False,
        )
        if path:
            self.path_var.set(path)

    def _on_save_clicked(self) -> None:
        self._save_current_to_memory()
        self.store.save(self.profiles)
        self.app.set_status("Đã lưu cấu hình hồ sơ vào config/profiles.json.")
        messagebox.showinfo("Lưu cấu hình", "Đã lưu cấu hình hồ sơ.")

    def _on_test_proxy_clicked(self) -> None:
        self._save_current_to_memory()
        cfg = self.profiles[self.current_key]
        if (cfg.proxy_type or "none").lower() == "none":
            messagebox.showinfo("Proxy", "Đang chọn 'none' (không dùng proxy), không cần test.")
            return

        ok, msg = self.browser_manager.test_proxy(cfg)
        # Ghi lịch sử test proxy
        status = "proxy_test_ok" if ok else "proxy_test_failed"
        self._append_proxy_history_to_file(cfg, status, msg)
        self.after(0, self._append_proxy_history_to_widget, cfg, status, msg)

        if ok:
            messagebox.showinfo("Proxy OK", msg)
        else:
            messagebox.showwarning("Proxy lỗi", msg)

    def _on_open_clicked(self) -> None:
        self._save_current_to_memory()
        cfg = self.profiles[self.current_key]

        def worker() -> None:
            try:
                if (cfg.proxy_type or "none").lower() != "none":
                    ok, msg = self.browser_manager.test_proxy(cfg)
                    status = "proxy_test_ok" if ok else "proxy_test_failed"
                    self._append_proxy_history_to_file(cfg, status, msg)
                    self.after(0, self._append_proxy_history_to_widget, cfg, status, msg)
                    if not ok:
                        self.app.append_event(f"Proxy lỗi cho {self.current_key}: {msg}")
                        messagebox.showwarning("Proxy lỗi", msg)
                        return

                self.browser_manager.open_browser(self.current_key, cfg)
                self.app.append_event(f"Đã mở trình duyệt cho {self.current_key}.")
                self._append_proxy_history_to_file(cfg, "open_ok", "Đã mở trình duyệt")
                self.after(0, self._append_proxy_history_to_widget, cfg, "open_ok", "Đã mở trình duyệt")
            except Exception as exc:
                self._append_proxy_history_to_file(cfg, "open_failed", str(exc))
                self.after(0, self._append_proxy_history_to_widget, cfg, "open_failed", str(exc))
                self.app.report_error(exc)

        threading.Thread(target=worker, daemon=True).start()

    def _on_close_clicked(self) -> None:
        cfg = self.profiles[self.current_key]

        def worker() -> None:
            try:
                self.browser_manager.close_browser(self.current_key)
                self.app.append_event(f"Đã đóng trình duyệt cho {self.current_key}.")
                self._append_proxy_history_to_file(cfg, "close_ok", "Đã đóng trình duyệt")
                self.after(0, self._append_proxy_history_to_widget, cfg, "close_ok", "Đã đóng trình duyệt")
            except Exception as exc:
                self._append_proxy_history_to_file(cfg, "close_failed", str(exc))
                self.after(0, self._append_proxy_history_to_widget, cfg, "close_failed", str(exc))
                self.app.report_error(exc)

        threading.Thread(target=worker, daemon=True).start()


