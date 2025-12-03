import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, Any
from browser.manager import BrowserManager
from core.config import load_config, save_config

class ProfileTab(ttk.Frame):
    def __init__(self, parent, browser_manager: BrowserManager):
        super().__init__(parent)
        self.browser_manager = browser_manager

        self.profile_var = tk.StringVar(value="P1")

        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, pady=5)

        ttk.Label(top, text="Chọn profile:").pack(side=tk.LEFT, padx=5)
        ttk.OptionMenu(top, self.profile_var, "P1", "P1", "P2", "P3",
                       command=lambda _: self.load_profile()).pack(side=tk.LEFT)

        ttk.Button(top, text="Mở Browser", command=self.open_browser).pack(side=tk.LEFT, padx=5)
        ttk.Button(top, text="Đóng Browser", command=self.close_browser).pack(side=tk.LEFT, padx=5)

        form = ttk.Frame(self)
        form.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Name
        ttk.Label(form, text="Tên hiển thị:").grid(row=0, column=0, sticky="w", pady=2)
        self.name_entry = ttk.Entry(form, width=40)
        self.name_entry.grid(row=0, column=1, sticky="w", pady=2)

        # Chrome path
        ttk.Label(form, text="Chrome path:").grid(row=1, column=0, sticky="w", pady=2)
        self.chrome_entry = ttk.Entry(form, width=60)
        self.chrome_entry.grid(row=1, column=1, sticky="w", pady=2)

        # User data dir
        ttk.Label(form, text="User-data-dir:").grid(row=2, column=0, sticky="w", pady=2)
        self.userdir_entry = ttk.Entry(form, width=60)
        self.userdir_entry.grid(row=2, column=1, sticky="w", pady=2)

        # Proxy group
        proxy_frame = ttk.LabelFrame(form, text="Proxy")
        proxy_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=5)
        proxy_frame.columnconfigure(1, weight=1)

        ttk.Label(proxy_frame, text="Host:").grid(row=0, column=0, sticky="w", pady=2)
        self.proxy_host = ttk.Entry(proxy_frame, width=30)
        self.proxy_host.grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(proxy_frame, text="Port:").grid(row=1, column=0, sticky="w", pady=2)
        self.proxy_port = ttk.Entry(proxy_frame, width=10)
        self.proxy_port.grid(row=1, column=1, sticky="w", pady=2)

        ttk.Label(proxy_frame, text="Username:").grid(row=2, column=0, sticky="w", pady=2)
        self.proxy_user = ttk.Entry(proxy_frame, width=30)
        self.proxy_user.grid(row=2, column=1, sticky="w", pady=2)

        ttk.Label(proxy_frame, text="Password:").grid(row=3, column=0, sticky="w", pady=2)
        self.proxy_pass = ttk.Entry(proxy_frame, width=30, show="*")
        self.proxy_pass.grid(row=3, column=1, sticky="w", pady=2)

        # Window group
        win_frame = ttk.LabelFrame(form, text="Cửa sổ")
        win_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=5)

        ttk.Label(win_frame, text="Width:").grid(row=0, column=0, sticky="w", pady=2)
        self.win_width = ttk.Entry(win_frame, width=10)
        self.win_width.grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(win_frame, text="Height:").grid(row=1, column=0, sticky="w", pady=2)
        self.win_height = ttk.Entry(win_frame, width=10)
        self.win_height.grid(row=1, column=1, sticky="w", pady=2)

        ttk.Label(win_frame, text="Scale %:").grid(row=2, column=0, sticky="w", pady=2)
        self.win_scale = ttk.Entry(win_frame, width=10)
        self.win_scale.grid(row=2, column=1, sticky="w", pady=2)

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(side=tk.TOP, fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="Lưu cấu hình", command=self.save_profile).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Reload config", command=self.reload_config).pack(side=tk.LEFT, padx=5)

        self.load_profile()

    def _get_profile_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name_entry.get().strip(),
            "chrome_path": self.chrome_entry.get().strip(),
            "user_data_dir": self.userdir_entry.get().strip(),
            "proxy": {
                "host": self.proxy_host.get().strip(),
                "port": int(self.proxy_port.get() or 0),
                "username": self.proxy_user.get().strip(),
                "password": self.proxy_pass.get().strip(),
            },
            "window": {
                "width": int(self.win_width.get() or 1280),
                "height": int(self.win_height.get() or 720),
                "scale_percent": int(self.win_scale.get() or 100),
            },
        }

    def load_profile(self):
        cfg = load_config()
        pid = self.profile_var.get()
        p = cfg.get("profiles", {}).get(pid)
        if not p:
            return
        self.name_entry.delete(0, tk.END)
        self.name_entry.insert(0, p.get("name", ""))

        self.chrome_entry.delete(0, tk.END)
        self.chrome_entry.insert(0, p.get("chrome_path", ""))

        self.userdir_entry.delete(0, tk.END)
        self.userdir_entry.insert(0, p.get("user_data_dir", ""))

        proxy = p.get("proxy", {})
        self.proxy_host.delete(0, tk.END)
        self.proxy_host.insert(0, proxy.get("host", ""))

        self.proxy_port.delete(0, tk.END)
        self.proxy_port.insert(0, str(proxy.get("port", 0)))

        self.proxy_user.delete(0, tk.END)
        self.proxy_user.insert(0, proxy.get("username", ""))

        self.proxy_pass.delete(0, tk.END)
        self.proxy_pass.insert(0, proxy.get("password", ""))

        win = p.get("window", {})
        self.win_width.delete(0, tk.END)
        self.win_width.insert(0, str(win.get("width", 1280)))

        self.win_height.delete(0, tk.END)
        self.win_height.insert(0, str(win.get("height", 720)))

        self.win_scale.delete(0, tk.END)
        self.win_scale.insert(0, str(win.get("scale_percent", 100)))

    def save_profile(self):
        pid = self.profile_var.get()
        new_p = self._get_profile_dict()
        cfg = load_config()
        if "profiles" not in cfg:
            cfg["profiles"] = {}
        cfg["profiles"][pid] = new_p
        save_config(cfg)
        self.browser_manager.reload_config()
        messagebox.showinfo("Lưu cấu hình", f"Đã lưu cấu hình cho {pid}")

    def reload_config(self):
        self.browser_manager.reload_config()
        self.load_profile()
        messagebox.showinfo("Reload", "Đã reload config từ file")

    def open_browser(self):
        self.browser_manager.open_browser(self.profile_var.get())

    def close_browser(self):
        self.browser_manager.close_browser(self.profile_var.get())
