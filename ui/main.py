import tkinter as tk
from tkinter import ttk
from core.logger import log
from db.database import init_db
from browser.manager import BrowserManager
from capture.capture_manager import CaptureManager

from ui.tabs.dashboard_tab import DashboardTab
from ui.tabs.profile_tab import ProfileTab
from ui.tabs.capture_tab import CaptureTab
from ui.tabs.vision_tab import VisionTab
from ui.tabs.engine_tab import EngineTab
from ui.tabs.logs_tab import LogsTab

class MainApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Mậu Binh Control Panel")
        self.geometry("1200x800")

        init_db()
        self.browser_manager = BrowserManager()
        self.capture_manager = CaptureManager(self.browser_manager)

        header_frame = ttk.Frame(self)
        header_frame.pack(side=tk.TOP, fill=tk.X)

        self.header_label = ttk.Label(header_frame, text="Mậu Binh Tool - Dashboard",
                                      font=("Segoe UI", 12, "bold"))
        self.header_label.pack(side=tk.LEFT, padx=10, pady=5)

        notebook = ttk.Notebook(self)
        notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.dashboard_tab = DashboardTab(
            notebook, self.browser_manager, self.capture_manager
        )
        self.profile_tab = ProfileTab(notebook, self.browser_manager)
        self.capture_tab = CaptureTab(notebook, self.browser_manager, self.capture_manager)
        self.vision_tab = VisionTab(
            notebook, self.browser_manager, self.capture_manager
        )
        self.engine_tab = EngineTab(notebook)
        self.logs_tab = LogsTab(notebook)

        notebook.add(self.dashboard_tab, text="Dashboard")
        notebook.add(self.profile_tab, text="Hồ sơ & Trình duyệt")
        notebook.add(self.capture_tab, text="Capture & Tọa độ")
        notebook.add(self.vision_tab, text="Vision & Variants")
        notebook.add(self.engine_tab, text="Engine & Lịch sử")
        notebook.add(self.logs_tab, text="Logs")

        status_frame = ttk.Frame(self)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var)
        self.status_label.pack(side=tk.LEFT, padx=5)

        log.info("UI initialized")

    def set_status(self, text: str):
        self.status_var.set(text)

def run_app():
    app = MainApp()
    app.mainloop()
