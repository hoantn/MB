import tkinter as tk
from tkinter import ttk
import os
from core.constants import LOG_DIR, APP_NAME

class LogsTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(side=tk.TOP, fill=tk.X, pady=5)

        ttk.Button(btn_frame, text="Reload log file", command=self.load_logs).pack(side=tk.LEFT, padx=5)

        self.text = tk.Text(self, wrap="none")
        self.text.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        x_scroll = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        y_scroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.text.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)

        self.load_logs()

    def load_logs(self):
        self.text.delete("1.0", tk.END)
        path = os.path.join(LOG_DIR, f"{APP_NAME}.log")
        if not os.path.exists(path):
            self.text.insert(tk.END, "Chưa có file log.")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-500:]  # last 500 lines
            self.text.insert(tk.END, "".join(lines))
        except Exception as e:
            self.text.insert(tk.END, f"Lỗi đọc log: {e}")
