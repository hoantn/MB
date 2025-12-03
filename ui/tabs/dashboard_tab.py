import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional
from PIL import ImageTk

from browser.manager import BrowserManager
from capture.capture_manager import CaptureManager
from vision.cropper import crop_slots
from vision.recognizer import recognize_card
from engine.card import Card
from engine.arranger import arrange_13_cards
from engine.scorer import score_three_chi
from db.models import insert_round
from core.constants import RANK_ORDER, TEMPLATES_DIR
from engine.action import apply_arrangement

import os
from PIL import Image

SUITS = ["R", "C", "B", "T"]
FULL_DECK: List[str] = [r + s for s in SUITS for r in RANK_ORDER]


# ======================
# LOAD OPPONENT IMAGE
# ======================

def load_opp_image(card_code: str) -> Optional[Image.Image]:
    """
    Load ảnh lá bài đối thủ.

    Ưu tiên lần lượt:
      1) vision/templates/opp/<card_code>.png
      2) vision/opp/<card_code>.png   (như bạn đang dùng hiện tại)
    """
    candidate_folders: List[str] = []

    if TEMPLATES_DIR:
        # 1) vision/templates/opp
        candidate_folders.append(os.path.join(TEMPLATES_DIR, "opp"))

        # 2) vision/opp (folder anh hiện tại của bạn)
        vision_root = os.path.dirname(TEMPLATES_DIR)
        candidate_folders.append(os.path.join(vision_root, "opp"))

    for folder in candidate_folders:
        path = os.path.join(folder, f"{card_code}.png")
        if os.path.exists(path):
            try:
                return Image.open(path)
            except Exception:
                continue

    return None


class DashboardTab(ttk.Frame):
    """
    Bố cục:
    - Trái: panel điều khiển (Browser, Scan, Engine).
    - Phải: lưới hiển thị bài OPP + P1 + P2 + P3, và khung Engine.
    - Xếp bài: có nút riêng cho P1, P2, P3 và nút cho cả 3.
    """

    def __init__(self, parent, browser_manager: BrowserManager,
                 capture_manager: CaptureManager):
        super().__init__(parent)
        self.browser_manager = browser_manager
        self.capture_manager = capture_manager

        self.profiles = ["P1", "P2", "P3"]
        self.rows = ["OPP"] + self.profiles  # OPP, P1, P2, P3

        # state
        self.card_codes: Dict[str, List[Optional[str]]] = {
            row: [None] * 13 for row in self.rows
        }
        self.card_conf: Dict[str, List[float]] = {
            row: [0.0] * 13 for row in self.rows
        }
        self.card_imgs: Dict[str, List[Optional[ImageTk.PhotoImage]]] = {
            row: [None] * 13 for row in self.rows
        }

        # layout 2 cột
        main = ttk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main, width=220)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        left.pack_propagate(False)

        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ===== LEFT: control panels =====

        # Panel Browser
        browser_group = ttk.LabelFrame(left, text="Browser & Profile")
        browser_group.pack(fill=tk.X, pady=5)

        for pid in self.profiles:
            row = ttk.Frame(browser_group)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=pid, width=4).pack(side=tk.LEFT)
            ttk.Button(row, text="Mở", width=6,
                       command=lambda p=pid: self.open_browser(p)).pack(side=tk.LEFT, padx=2)
            ttk.Button(row, text="Đóng", width=6,
                       command=lambda p=pid: self.close_browser(p)).pack(side=tk.LEFT, padx=2)

        # Panel Scan
        scan_group = ttk.LabelFrame(left, text="Scan bài")
        scan_group.pack(fill=tk.X, pady=5)

        ttk.Button(scan_group, text="Scan P1",
                   command=lambda: self.scan_profile("P1")).pack(fill=tk.X, pady=2)
        ttk.Button(scan_group, text="Scan P2",
                   command=lambda: self.scan_profile("P2")).pack(fill=tk.X, pady=2)
        ttk.Button(scan_group, text="Scan P3",
                   command=lambda: self.scan_profile("P3")).pack(fill=tk.X, pady=2)
        ttk.Separator(scan_group, orient="horizontal").pack(fill=tk.X, pady=3)
        ttk.Button(scan_group, text="Scan 3P + đối thủ",
                   command=self.scan_all).pack(fill=tk.X, pady=2)

        # Panel Engine
        engine_ctrl = ttk.LabelFrame(left, text="Engine")
        engine_ctrl.pack(fill=tk.X, pady=5)

        ttk.Button(engine_ctrl, text="Xếp P1",
                   command=lambda: self.run_engine_for("P1")).pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(engine_ctrl, text="Xếp P2",
                   command=lambda: self.run_engine_for("P2")).pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(engine_ctrl, text="Xếp P3",
                   command=lambda: self.run_engine_for("P3")).pack(fill=tk.X, padx=5, pady=2)
        ttk.Separator(engine_ctrl, orient="horizontal").pack(fill=tk.X, pady=3)
        ttk.Button(engine_ctrl, text="Xếp 3P (log cả 3)",
                   command=self.run_engine_all).pack(fill=tk.X, padx=5, pady=2)

        # ===== RIGHT: cards grid + engine output =====

        cards_frame = ttk.LabelFrame(right, text="Realtime P1 / P2 / P3 và Đối thủ")
        cards_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.card_labels: Dict[str, List[ttk.Label]] = {row: [] for row in self.rows}

        # header cột 1..13
        header = ttk.Frame(cards_frame)
        header.grid(row=0, column=1, columnspan=13, pady=(0, 5))
        for i in range(13):
            ttk.Label(header, text=f"{i + 1}", width=6, anchor="center").grid(row=0, column=i)

        for r_idx, rowname in enumerate(self.rows):
            ttk.Label(cards_frame, text=rowname, width=6).grid(row=r_idx + 1, column=0, sticky="w")
            for c in range(13):
                cell = ttk.Frame(cards_frame, borderwidth=1, relief=tk.SOLID)
                cell.grid(row=r_idx + 1, column=c + 1, padx=2, pady=2)
                lbl = ttk.Label(cell, text="-", width=6)
                lbl.pack()
                self.card_labels[rowname].append(lbl)

        # Engine result
        engine_frame = ttk.LabelFrame(right, text="Gợi ý xếp bài")
        engine_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        self.engine_target_var = tk.StringVar(value="(chưa xếp)")
        self.chi1_var = tk.StringVar(value="")
        self.chi2_var = tk.StringVar(value="")
        self.chi3_var = tk.StringVar(value="")
        self.score_var = tk.StringVar(value="")

        ttk.Label(engine_frame, text="Profile:").grid(row=0, column=0, sticky="w")
        ttk.Label(engine_frame, textvariable=self.engine_target_var).grid(row=0, column=1, sticky="w")

        ttk.Label(engine_frame, text="Chi 1:").grid(row=1, column=0, sticky="w")
        ttk.Label(engine_frame, textvariable=self.chi1_var).grid(row=1, column=1, sticky="w")

        ttk.Label(engine_frame, text="Chi 2:").grid(row=2, column=0, sticky="w")
        ttk.Label(engine_frame, textvariable=self.chi2_var).grid(row=2, column=1, sticky="w")

        ttk.Label(engine_frame, text="Chi 3:").grid(row=3, column=0, sticky="w")
        ttk.Label(engine_frame, textvariable=self.chi3_var).grid(row=3, column=1, sticky="w")

        ttk.Label(engine_frame, text="Score:").grid(row=4, column=0, sticky="w")
        ttk.Label(engine_frame, textvariable=self.score_var).grid(row=4, column=1, sticky="w")

    # ==================== Browser ===========================

    def open_browser(self, profile_id: str):
        self.browser_manager.open_browser(profile_id)

    def close_browser(self, profile_id: str):
        self.browser_manager.close_browser(profile_id)

    # ==================== Scan ==============================

    def scan_profile(self, profile_id: str):
        img = self.capture_manager.capture_region(profile_id)
        if img is None:
            return
        slots = crop_slots(profile_id, img)
        row = profile_id

        for i in range(13):
            slot_img = slots[i] if i < len(slots) else None
            if slot_img is None:
                self.card_labels[row][i].config(text="-", image="", compound=tk.NONE)
                self.card_imgs[row][i] = None
                self.card_codes[row][i] = None
                self.card_conf[row][i] = 0.0
                continue

            disp = slot_img.resize((60, 80))
            tk_img = ImageTk.PhotoImage(disp)
            self.card_imgs[row][i] = tk_img
            code, conf, _ = recognize_card(slot_img)
            self.card_codes[row][i] = code
            self.card_conf[row][i] = conf
            text = f"{code}\n({conf * 100:.0f}%)"
            self.card_labels[row][i].config(image=tk_img, text=text, compound=tk.BOTTOM)

        # sau khi quét 1 profile, cập nhật lại đối thủ
        self.update_opponent()

    def scan_all(self):
        for pid in self.profiles:
            self.scan_profile(pid)

    # ==================== Opponent ==========================

    def update_opponent(self):
        """
        Hiển thị bài đối thủ dựa trên:
          FULL_DECK - (P1 union P2 union P3)
        Và nếu có ảnh trong vision/templates/opp hoặc vision/opp
        thì hiển thị thêm ảnh.
        """

        # 1) Lấy toàn bộ lá đã biết (P1, P2, P3)
        known = set()
        for pid in self.profiles:
            for c in self.card_codes[pid]:
                if c and c != "??":
                    known.add(c)

        # 2) Tính 13 lá còn lại của đối thủ
        remaining = [c for c in FULL_DECK if c not in known]

        opp_codes = ["??"] * 13
        for i in range(min(13, len(remaining))):
            opp_codes[i] = remaining[i]

        self.card_codes["OPP"] = opp_codes

        # 3) Hiển thị lên UI Dashboard
        for i, c in enumerate(opp_codes):

            # Không đủ lá → hiển thị "??"
            if c == "??":
                self.card_labels["OPP"][i].config(
                    text="??",
                    image="",
                    compound=tk.BOTTOM,
                )
                self.card_imgs["OPP"][i] = None
                self.card_conf["OPP"][i] = 0.0
                continue

            # Load ảnh đối thủ (nếu có)
            img = load_opp_image(c)
            if img is not None:
                disp = img.resize((60, 80))
                tk_img = ImageTk.PhotoImage(disp)
                self.card_labels["OPP"][i].config(
                    image=tk_img,
                    text=c,
                    compound=tk.BOTTOM,
                )
                self.card_imgs["OPP"][i] = tk_img
            else:
                # Không có ảnh → chỉ hiện text như trước
                self.card_labels["OPP"][i].config(
                    text=c,
                    image="",
                    compound=tk.BOTTOM,
                )
                self.card_imgs["OPP"][i] = None

            # Confidence = 100% vì bài OPP là suy luận, không phải quét
            self.card_conf["OPP"][i] = 1.0

    # ==================== Engine ============================

    def run_engine_for(self, pid: str):
        codes = self.card_codes.get(pid, [])
        if len(codes) != 13:
            return
        # phải đủ 13 lá hợp lệ
        if any(c is None or c == "??" for c in codes):
            return

        cards = [Card.from_code(c) for c in codes]
        chi1, chi2, chi3 = arrange_13_cards(cards)
        total_score, _ = score_three_chi(chi1, chi2, chi3)

        # Cập nhật UI engine summary
        self.engine_target_var.set(pid)
        self.chi1_var.set(" ".join(c.display() for c in chi1))
        self.chi2_var.set(" ".join(c.display() for c in chi2))
        self.chi3_var.set(" ".join(c.display() for c in chi3))
        self.score_var.set(str(total_score))

        # Ghi log DB
        insert_round(pid, cards, chi1, chi2, chi3, total_score, note="dashboard_multi")

        # QUAN TRỌNG: gọi auto xếp bài thật trên trình duyệt
        try:
            apply_arrangement(
                profile_id=pid,
                browser_manager=self.browser_manager,
                current_codes=list(codes),
                chi1=chi1,
                chi2=chi2,
                chi3=chi3,
            )
        except Exception as e:
            from core.logger import log
            log.error("run_engine_for[%s]: apply_arrangement bị lỗi: %s", pid, e)

    def run_engine_all(self):
        for pid in self.profiles:
            self.run_engine_for(pid)
