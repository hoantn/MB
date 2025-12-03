import tkinter as tk
from tkinter import ttk, messagebox
from typing import List, Optional
from PIL import Image, ImageTk

from browser.manager import BrowserManager
from capture.capture_manager import CaptureManager
from vision.cropper import crop_slots
from vision.recognizer import recognize_card
from vision.variants_manager import add_variant

class VisionTab(ttk.Frame):
    def __init__(self, parent, browser_manager: BrowserManager, capture_manager: CaptureManager):
        super().__init__(parent)
        self.browser_manager = browser_manager
        self.capture_manager = capture_manager

        self.profile_var = tk.StringVar(value="P1")
        self.auto_farm = tk.BooleanVar(value=False)
        self.auto_threshold = tk.DoubleVar(value=0.95)

        self.slot_images: List[Optional[Image.Image]] = [None] * 13
        self.tk_images: List[Optional[ImageTk.PhotoImage]] = [None] * 13
        self.codes: List[Optional[str]] = [None] * 13
        self.confidences: List[float] = [0.0] * 13

        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, pady=5)

        ttk.Label(top, text="Profile:").pack(side=tk.LEFT, padx=5)
        ttk.OptionMenu(top, self.profile_var, "P1", "P1", "P2", "P3").pack(side=tk.LEFT)

        ttk.Button(top, text="Scan + nhận diện", command=self.scan_once).pack(side=tk.LEFT, padx=5)

        ttk.Checkbutton(top, text="Auto-farm variant", variable=self.auto_farm).pack(side=tk.LEFT, padx=10)
        ttk.Label(top, text="Ngưỡng conf:").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.auto_threshold, width=5).pack(side=tk.LEFT)

        self.cards_frame = ttk.LabelFrame(self, text="13 lá bài (Vision)")
        self.cards_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.card_labels: List[ttk.Label] = []
        for i in range(13):
            frame = ttk.Frame(self.cards_frame, borderwidth=1, relief=tk.SOLID)
            frame.grid(row=i // 5, column=i % 5, padx=4, pady=4, sticky="nsew")
            lbl = ttk.Label(frame, text=f"Slot {i+1}")
            lbl.pack()
            lbl.bind("<Button-1>", lambda e, idx=i: self.open_popup(idx))
            self.card_labels.append(lbl)

        stats_frame = ttk.Frame(self)
        stats_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        self.status_var = tk.StringVar(value="Chưa scan")
        ttk.Label(stats_frame, textvariable=self.status_var).pack(side=tk.LEFT)

    def scan_once(self):
        profile_id = self.profile_var.get()
        img = self.capture_manager.capture_region(profile_id)
        if img is None:
            messagebox.showwarning("Scan", "Chưa có browser / vùng game cho profile này")
            return
        slots = crop_slots(profile_id, img)

        added_count = 0
        self.status_var.set("Đang nhận diện...")
        self.update_idletasks()

        for i in range(13):
            slot_img = slots[i] if i < len(slots) else None
            self.slot_images[i] = slot_img
            if slot_img is None:
                self.card_labels[i].config(text=f"Slot {i+1}\n(no cfg)", image="")
                self.tk_images[i] = None
                self.codes[i] = None
                self.confidences[i] = 0.0
                continue

            disp = slot_img.resize((60, 80))
            tk_img = ImageTk.PhotoImage(disp)
            self.tk_images[i] = tk_img
            code, conf, is_new = recognize_card(slot_img)
            self.codes[i] = code
            self.confidences[i] = conf
            txt = f"{code}\n({conf*100:.0f}%)"
            self.card_labels[i].config(image=tk_img, text=txt, compound=tk.BOTTOM)

            if self.auto_farm.get() and is_new and conf >= self.auto_threshold.get():
                if add_variant(code, slot_img):
                    added_count += 1

        if self.auto_farm.get():
            self.status_var.set(f"Scan xong. Auto-farm đã thêm {added_count} variant.")
        else:
            self.status_var.set("Scan xong. Click vào lá để thêm variant thủ công.")

    def open_popup(self, idx: int):
        img = self.slot_images[idx]
        code = self.codes[idx]
        conf = self.confidences[idx]
        if img is None:
            messagebox.showinfo("Slot", f"Slot {idx+1} chưa có ảnh / chưa config")
            return

        popup = tk.Toplevel(self)
        popup.title(f"Slot {idx+1} - Quản lý variant")

        big = img.resize((120, 160))
        tk_big = ImageTk.PhotoImage(big)
        lbl_img = ttk.Label(popup, image=tk_big)
        lbl_img.image = tk_big
        lbl_img.pack(side=tk.TOP, padx=10, pady=10)

        info_frame = ttk.Frame(popup)
        info_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        ttk.Label(info_frame, text="Card code (VD: 9C, AR):").grid(row=0, column=0, sticky="w")
        code_var = tk.StringVar(value=code or "")
        code_entry = ttk.Entry(info_frame, textvariable=code_var, width=10)
        code_entry.grid(row=0, column=1, sticky="w")

        ttk.Label(info_frame, text=f"Conf: {conf*100:.1f}%").grid(row=1, column=0, columnspan=2, sticky="w", pady=2)

        def on_add():
            c = code_var.get().strip().upper()
            if len(c) < 2:
                messagebox.showwarning("Variant", "Card code không hợp lệ")
                return
            ok = add_variant(c, img)
            if ok:
                messagebox.showinfo("Variant", f"Đã thêm variant cho {c}")
            else:
                messagebox.showinfo("Variant", f"Ảnh quá giống variant sẵn có, không thêm.")
            popup.destroy()

        ttk.Button(popup, text="Lưu làm variant", command=on_add).pack(side=tk.TOP, pady=5)
        ttk.Button(popup, text="Đóng", command=popup.destroy).pack(side=tk.TOP, pady=5)
