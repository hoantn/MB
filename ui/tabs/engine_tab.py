import tkinter as tk
from tkinter import ttk, messagebox

from engine.card import Card
from engine.arranger import arrange_13_cards
from engine.scorer import score_three_chi
from db.models import get_rounds

class EngineTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        # Manual test
        manual_frame = ttk.LabelFrame(self, text="Test Engine (nhập 13 lá)")
        manual_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        ttk.Label(manual_frame, text="Danh sách lá (VD: AR,KB,QC,...):").grid(row=0, column=0, sticky="w")
        self.cards_entry = ttk.Entry(manual_frame, width=80)
        self.cards_entry.grid(row=1, column=0, columnspan=2, sticky="w", pady=2)

        ttk.Button(manual_frame, text="Run Engine", command=self.run_engine_manual).grid(row=2, column=0, sticky="w", pady=5)

        self.chi1_var = tk.StringVar(value="")
        self.chi2_var = tk.StringVar(value="")
        self.chi3_var = tk.StringVar(value="")
        self.score_var = tk.StringVar(value="")

        ttk.Label(manual_frame, text="Chi 1:").grid(row=3, column=0, sticky="w")
        ttk.Label(manual_frame, textvariable=self.chi1_var).grid(row=3, column=1, sticky="w")
        ttk.Label(manual_frame, text="Chi 2:").grid(row=4, column=0, sticky="w")
        ttk.Label(manual_frame, textvariable=self.chi2_var).grid(row=4, column=1, sticky="w")
        ttk.Label(manual_frame, text="Chi 3:").grid(row=5, column=0, sticky="w")
        ttk.Label(manual_frame, textvariable=self.chi3_var).grid(row=5, column=1, sticky="w")
        ttk.Label(manual_frame, text="Score:").grid(row=6, column=0, sticky="w")
        ttk.Label(manual_frame, textvariable=self.score_var).grid(row=6, column=1, sticky="w")

        # History
        history_frame = ttk.LabelFrame(self, text="Lịch sử rounds (DB)")
        history_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        columns = ("id", "profile", "timestamp", "total_score")
        self.tree = ttk.Treeview(history_frame, columns=columns, show="headings", height=8)
        for col in columns:
            self.tree.heading(col, text=col)
        self.tree.column("id", width=60)
        self.tree.column("profile", width=80)
        self.tree.column("timestamp", width=180)
        self.tree.column("total_score", width=100)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree.bind("<<TreeviewSelect>>", self.on_select_round)

        scrollbar = ttk.Scrollbar(history_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)

        detail_frame = ttk.Frame(history_frame)
        detail_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)

        ttk.Label(detail_frame, text="Chi tiết round:").pack(anchor="w")

        self.detail_text = tk.Text(detail_frame, width=50, height=15)
        self.detail_text.pack(fill=tk.BOTH, expand=True)

        ttk.Button(self, text="Reload lịch sử", command=self.load_rounds).pack(side=tk.TOP, anchor="w", padx=5, pady=5)

        self.load_rounds()

    def run_engine_manual(self):
        text = self.cards_entry.get().strip()
        if not text:
            return
        parts = [p.strip().upper() for p in text.replace(";", ",").split(",") if p.strip()]
        if len(parts) != 13:
            messagebox.showwarning("Engine", "Cần đúng 13 lá (VD: AR,KB,QC,...)")
            return
        try:
            cards = [Card.from_code(c) for c in parts]
        except Exception as e:
            messagebox.showerror("Engine", f"Lỗi parse card: {e}")
            return

        try:
            chi1, chi2, chi3 = arrange_13_cards(cards)
            total_score, detail = score_three_chi(chi1, chi2, chi3)
        except Exception as e:
            messagebox.showerror("Engine", f"Lỗi engine: {e}")
            return

        self.chi1_var.set(" ".join(c.display() for c in chi1))
        self.chi2_var.set(" ".join(c.display() for c in chi2))
        self.chi3_var.set(" ".join(c.display() for c in chi3))
        self.score_var.set(str(total_score))

    def load_rounds(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        rows = get_rounds(limit=100)
        for r in rows:
            self.tree.insert("", "end", values=(r["id"], r["profile"], r["timestamp"], r["total_score"]))

    def on_select_round(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        item_id = sel[0]
        values = self.tree.item(item_id, "values")
        round_id = values[0]

        rows = get_rounds(limit=200)
        row = next((r for r in rows if str(r["id"]) == str(round_id)), None)
        if not row:
            return

        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert(tk.END, f"ID: {row['id']}\n")
        self.detail_text.insert(tk.END, f"Profile: {row['profile']}\n")
        self.detail_text.insert(tk.END, f"Timestamp: {row['timestamp']}\n")
        self.detail_text.insert(tk.END, f"Cards: {row['cards_raw']}\n")
        self.detail_text.insert(tk.END, f"Chi1: {row['chi1']}\n")
        self.detail_text.insert(tk.END, f"Chi2: {row['chi2']}\n")
        self.detail_text.insert(tk.END, f"Chi3: {row['chi3']}\n")
        self.detail_text.insert(tk.END, f"Total score: {row['total_score']}\n")
        self.detail_text.insert(tk.END, f"Note: {row['note']}\n")
