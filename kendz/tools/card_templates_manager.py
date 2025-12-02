# kendz/tools/card_templates_manager.py

import os
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

from kendz.cards.templates import (
    CARD_CODES,
    VariantInfo,
    get_templates_dir,
    list_variants,
    delete_variant,
    find_next_variant_index,
)

try:
    # Nếu AppContext đã tồn tại trong hệ thống hiện tại của bạn.
    from kendz.app.context import AppContext  # type: ignore
except Exception:  # fallback an toàn
    AppContext = None  # type: ignore


@dataclass
class ProfileCardsPanel:
    """
    Panel hiển thị danh sách lá bài hiện tại cho 3 profile.
    Mỗi profile 1 hàng, hiển thị dạng ảnh (không scale lệch tỷ lệ).
    """
    container: tk.Frame
    row_frames: Dict[int, tk.Frame]
    image_labels: Dict[int, List[tk.Label]]
    images: Dict[int, List[tk.PhotoImage]]


def _load_game_id_and_base_dir() -> Tuple[str, Path]:
    """
    Lấy game_id và base_dir theo cách ít phá vỡ hệ thống hiện tại.

    - Nếu có AppContext: dùng ctx.config.core.default_game_id
    - base_dir: 2 cấp trên file hiện tại (như các tool khác).
    """
    base_dir = Path(__file__).resolve().parents[2]
    game_id = "mau_binh_siteA"

    if AppContext is not None:
        try:
            ctx = AppContext.bootstrap()
            game_id = ctx.config.core.default_game_id
        except Exception:
            # Nếu vì lý do gì AppContext lỗi, vẫn fallback dùng default.
            pass

    return game_id, base_dir


def _load_icon_for_code(base_dir: Path, game_id: str, code: str) -> Optional[tk.PhotoImage]:
    """
    Load ảnh icon cho 1 lá bài:
    - Ưu tiên: data/card_templates/<game_id>/<CODE>.png
    - Nếu không có: lấy biến thể đầu tiên CODE_*.png
    - Cuối cùng (fallback): không trả gì (None)
    Không resize để giữ nguyên kích thước gốc (tránh vỡ bố cục).
    """
    code = code.upper()
    tpl_dir = get_templates_dir(base_dir, game_id)

    # 1) CODE.png / CODE.jpg / CODE.jpeg
    for ext in ("png", "jpg", "jpeg"):
        p = tpl_dir / f"{code}.{ext}"
        if p.exists():
            try:
                return tk.PhotoImage(file=str(p))
            except Exception:
                pass

    # 2) CODE_*.png / CODE_*.jpg / CODE_*.jpeg
    for ext in ("png", "jpg", "jpeg"):
        candidates = sorted(
            [f for f in os.listdir(tpl_dir) if f.upper().startswith(f"{code}_") and f.lower().endswith(ext)],
            key=lambda name: name.lower(),
        )
        if candidates:
            p = tpl_dir / candidates[0]
            try:
                return tk.PhotoImage(file=str(p))
            except Exception:
                pass

    return None


def _build_profile_cards_panel(parent: tk.Widget, base_dir: Path, game_id: str) -> ProfileCardsPanel:
    """
    Tạo panel (3 hàng) hiển thị ảnh 13 lá bài cho 3 profile.
    Responsive: container fill=both, mỗi row_frame fill=x, các label bám trái.
    """
    container = tk.Frame(parent)
    container.grid_columnconfigure(0, weight=1)

    row_frames: Dict[int, tk.Frame] = {}
    image_labels: Dict[int, List[tk.Label]] = {1: [], 2: [], 3: []}
    images: Dict[int, List[tk.PhotoImage]] = {1: [], 2: [], 3: []}

    for pid in (1, 2, 3):
        row_frame = tk.Frame(container)
        row_frame.grid(row=pid - 1, column=0, sticky="w", pady=4)
        row_frames[pid] = row_frame

        prefix = tk.Label(row_frame, text=f"Profile {pid}:", font=("Segoe UI", 9, "bold"))
        prefix.pack(side=tk.LEFT, padx=(0, 6))

    return ProfileCardsPanel(
        container=container,
        row_frames=row_frames,
        image_labels=image_labels,
        images=images,
    )


def _update_profile_cards_panel(
    panel: ProfileCardsPanel,
    base_dir: Path,
    game_id: str,
    cards_by_profile: Dict[int, List[str]],
) -> None:
    """
    Cập nhật panel hiển thị ảnh theo `cards_by_profile`.
    `cards_by_profile[pid]` là list mã lá bài ["2C", "3D", ...]
    """
    for pid in (1, 2, 3):
        # Xóa label & reference cũ
        for lbl in panel.image_labels[pid]:
            lbl.destroy()
        panel.image_labels[pid].clear()
        panel.images[pid].clear()

        row_frame = panel.row_frames[pid]
        cards = cards_by_profile.get(pid) or []

        for code in cards:
            icon = _load_icon_for_code(base_dir, game_id, code)
            if icon is None:
                # Nếu không có icon thì bỏ qua, hoặc có thể hiển thị text nhỏ.
                continue
            lbl = tk.Label(row_frame, image=icon, borderwidth=0)
            lbl.pack(side=tk.LEFT, padx=2)
            panel.image_labels[pid].append(lbl)
            panel.images[pid].append(icon)


def _open_templates_dir(base_dir: Path, game_id: str) -> None:
    tpl_dir = get_templates_dir(base_dir, game_id)
    tpl_dir.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(str(tpl_dir))  # type: ignore
        elif sys.platform == "darwin":
            os.system(f'open "{tpl_dir}"')
        else:
            os.system(f'xdg-open "{tpl_dir}"')
    except Exception:
        messagebox.showerror("Lỗi", f"Không mở được thư mục: {tpl_dir}")


def _show_variants_dialog(root: tk.Tk, base_dir: Path, game_id: str, code: str) -> None:
    """
    Dialog quản lý biến thể cho 1 lá: list + preview ảnh + nút xoá + mở folder.
    """
    code = code.upper()
    tpl_dir = get_templates_dir(base_dir, game_id)
    variants_map = list_variants(base_dir, game_id)
    variants = variants_map.get(code, [])

    win = tk.Toplevel(root)
    win.title(f"Quản lý template cho {code}")
    win.geometry("640x380")
    win.transient(root)
    win.grab_set()

    win.columnconfigure(0, weight=0)
    win.columnconfigure(1, weight=0)
    win.columnconfigure(2, weight=1)
    win.rowconfigure(0, weight=1)
    win.rowconfigure(1, weight=0)

    lb = tk.Listbox(win, exportselection=False)
    lb.grid(row=0, column=0, sticky="nsw", padx=8, pady=8)
    sb = tk.Scrollbar(win, orient=tk.VERTICAL, command=lb.yview)
    sb.grid(row=0, column=1, sticky="ns", pady=8)
    lb.configure(yscrollcommand=sb.set)

    preview_label = tk.Label(win, text="Preview", borderwidth=1, relief=tk.SOLID)
    preview_label.grid(row=0, column=2, sticky="nsew", padx=(0, 8), pady=8)

    preview_image: Optional[tk.PhotoImage] = None

    for v in variants:
        lb.insert(tk.END, f"{v.variant_index}: {v.filename}")

    def on_select(event=None) -> None:
        nonlocal preview_image
        sel = lb.curselection()
        if not sel:
            return
        idx = sel[0]
        v = variants[idx]
        if not v.path.exists():
            preview_label.configure(text="Không tìm thấy file", image="")
            preview_image = None
            return
        try:
            img = tk.PhotoImage(file=str(v.path))
            preview_label.configure(image=img, text="")
            preview_image = img
        except Exception:
            preview_label.configure(text="Không load được ảnh", image="")
            preview_image = None

    lb.bind("<<ListboxSelect>>", on_select)

    def do_delete() -> None:
        sel = lb.curselection()
        if not sel:
            messagebox.showinfo("Thông báo", "Chọn 1 biến thể để xoá.")
            return
        idx = sel[0]
        v = variants[idx]
        if not messagebox.askyesno(
            "Xác nhận",
            f"Xoá biến thể {v.filename}?",
        ):
            return
        ok = delete_variant(base_dir, game_id, v.code, v.variant_index)
        if not ok:
            messagebox.showerror("Lỗi", "Xoá thất bại.")
            return
        win.destroy()
        _show_variants_dialog(root, base_dir, game_id, code)

    btn_delete = tk.Button(win, text="Xoá biến thể", command=do_delete)
    btn_delete.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="w")

    def do_open_dir() -> None:
        _open_templates_dir(base_dir, game_id)

    btn_open_dir = tk.Button(win, text="Mở thư mục template", command=do_open_dir)
    btn_open_dir.grid(row=1, column=2, padx=(0, 8), pady=(0, 8), sticky="e")

    if variants:
        lb.selection_set(0)
        on_select()


def _import_variants_for_code(root: tk.Tk, base_dir: Path, game_id: str, code: str) -> None:
    """
    Import 1 hoặc nhiều ảnh làm biến thể mới cho 1 lá bài.
    - Đặt tên CODE_index.png với index tăng dần (không ghi đè).
    """
    code = code.upper()
    tpl_dir = get_templates_dir(base_dir, game_id)
    tpl_dir.mkdir(parents=True, exist_ok=True)

    filepaths = filedialog.askopenfilenames(
        parent=root,
        title=f"Chọn ảnh cho {code}",
        filetypes=[
            ("Ảnh", "*.png;*.jpg;*.jpeg"),
            ("PNG", "*.png"),
            ("JPEG", "*.jpg;*.jpeg"),
        ],
    )
    if not filepaths:
        return

    from shutil import copy2

    for fp in filepaths:
        src = Path(fp)
        if not src.exists():
            continue
        next_idx = find_next_variant_index(base_dir, game_id, code)
        ext = src.suffix.lower() or ".png"
        if ext not in [".png", ".jpg", ".jpeg"]:
            ext = ".png"
        dest = tpl_dir / f"{code}_{next_idx}{ext}"
        try:
            copy2(src, dest)
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không copy được file {src} -> {dest}\n{e}")
            return

    messagebox.showinfo("Thành công", f"Đã import {len(filepaths)} biến thể cho {code}.")


def _build_cards_grid_tab(
    parent: tk.Widget,
    root: tk.Tk,
    base_dir: Path,
    game_id: str,
) -> tk.Frame:
    """
    Tạo tab 'Quản lý lá bài' với grid 52 lá.
    Mỗi ô: ảnh gốc (hoặc biến thể đầu tiên) + 2 nút: Import / Quản lý.
    """
    frame = tk.Frame(parent)
    frame.grid_rowconfigure(0, weight=1)
    frame.grid_columnconfigure(0, weight=1)

    # Canvas + scroll dọc để responsive hơn
    canvas = tk.Canvas(frame)
    canvas.grid(row=0, column=0, sticky="nsew")
    vsb = tk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
    vsb.grid(row=0, column=1, sticky="ns")
    canvas.configure(yscrollcommand=vsb.set)

    inner = tk.Frame(canvas)
    canvas.create_window((0, 0), window=inner, anchor="nw")

    inner.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
    )

    # Grid 4 hàng (C, D, H, S) x 13 cột (2..A)
    card_icons: Dict[str, tk.PhotoImage] = {}

    # Lấy số biến thể hiện tại
    variants_map = list_variants(base_dir, game_id)

    # Suit theo thứ tự C, D, H, S
    suits = ["C", "D", "H", "S"]
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"]

    for row, s in enumerate(suits):
        for col, r in enumerate(ranks):
            code = f"{r}{s}"
            cell = tk.Frame(inner, borderwidth=1, relief=tk.RIDGE, padx=4, pady=4)
            cell.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")

            inner.grid_columnconfigure(col, weight=1)

            # Ảnh gốc (hoặc biến thể đầu tiên)
            icon = _load_icon_for_code(base_dir, game_id, code)
            if icon is not None:
                icon_label = tk.Label(cell, image=icon)
                icon_label.pack()
                card_icons[code] = icon
            else:
                tk.Label(cell, text=code, font=("Segoe UI", 9, "bold")).pack()

            # Số biến thể
            vlist = variants_map.get(code, [])
            tk.Label(
                cell,
                text=f"{len(vlist)} biến thể",
                font=("Segoe UI", 8),
            ).pack()

            # Nút Import / Quản lý
            btn_row = tk.Frame(cell)
            btn_row.pack(pady=(2, 0))

            tk.Button(
                btn_row,
                text="Import",
                width=6,
                command=lambda c=code: _import_variants_for_code(root, base_dir, game_id, c),
            ).pack(side=tk.LEFT, padx=(0, 2))

            tk.Button(
                btn_row,
                text="Quản lý",
                width=6,
                command=lambda c=code: _show_variants_dialog(root, base_dir, game_id, c),
            ).pack(side=tk.LEFT)

    return frame


def run_panel() -> None:
    game_id, base_dir = _load_game_id_and_base_dir()

    root = tk.Tk()
    root.title(f"Kendz Card Templates Manager - {game_id}")

    # Responsive root
    root.rowconfigure(0, weight=0)  # header + menu
    root.rowconfigure(1, weight=1)  # nội dung
    root.rowconfigure(2, weight=0)  # hướng dẫn
    root.columnconfigure(0, weight=1)

    # ===== MENU CHÍNH (3 NÚT) + CHECKBOX PROFILE =====
    top_bar = tk.Frame(root)
    top_bar.grid(row=0, column=0, sticky="ew", padx=8, pady=4)
    top_bar.columnconfigure(0, weight=1)
    top_bar.columnconfigure(1, weight=1)
    top_bar.columnconfigure(2, weight=1)
    top_bar.columnconfigure(3, weight=1)

    tk.Label(
        top_bar,
        text=f"Game: {game_id}    (Thư mục template: data/card_templates/{game_id}/)",
        font=("Segoe UI", 9, "bold"),
    ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))

    # Check chọn profile
    profile_vars: Dict[int, tk.IntVar] = {
        1: tk.IntVar(value=1),
        2: tk.IntVar(value=1),
        3: tk.IntVar(value=1),
    }

    chk_frame = tk.Frame(top_bar)
    chk_frame.grid(row=1, column=0, sticky="w", pady=2)
    tk.Label(chk_frame, text="Profiles:", font=("Segoe UI", 9)).pack(side=tk.LEFT)
    for pid in (1, 2, 3):
        tk.Checkbutton(
            chk_frame,
            text=str(pid),
            variable=profile_vars[pid],
        ).pack(side=tk.LEFT, padx=(4 if pid == 1 else 2, 2))

    # Khu vực nội dung (2 tab: Quét/Xếp và Quản lý lá bài)
    main_area = tk.Frame(root)
    main_area.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))
    main_area.rowconfigure(0, weight=1)
    main_area.columnconfigure(0, weight=1)

    # Hai "tab" thủ công: scan_frame và manage_frame
    scan_frame = tk.Frame(main_area)
    manage_frame = tk.Frame(main_area)

    for f in (scan_frame, manage_frame):
        f.grid(row=0, column=0, sticky="nsew")

    # Panel hiển thị bài cho scan_frame & manage_frame (dùng chung state)
    last_cards_by_profile: Dict[int, List[str]] = {1: [], 2: [], 3: []}

    scan_panel = _build_profile_cards_panel(scan_frame, base_dir, game_id)
    scan_panel.container.pack(fill="both", expand=True, padx=4, pady=4)

    manage_cards_grid = _build_cards_grid_tab(manage_frame, root, base_dir, game_id)
    manage_cards_grid.pack(fill="both", expand=True, padx=4, pady=(4, 0))

    manage_panel = _build_profile_cards_panel(manage_frame, base_dir, game_id)
    manage_panel.container.pack(fill="x", expand=False, padx=4, pady=4)

    def show_scan_tab() -> None:
        scan_frame.tkraise()

    def show_manage_tab() -> None:
        manage_frame.tkraise()

    # Nút Quét Bài / Xếp Bài / Quản lý lá bài
    def get_selected_profiles() -> List[int]:
        return [pid for pid in (1, 2, 3) if profile_vars[pid].get() == 1]

    def do_scan() -> None:
        sel = get_selected_profiles()
        if not sel:
            messagebox.showinfo("Thông báo", "Chọn ít nhất 1 profile để Quét Bài.")
            return

        # TODO: Gắn vào pipeline thực tế của bạn.
        # Hiện tại, để tránh phá hệ thống, tôi không giả định module nào,
        # nên tạm thời chỉ hiển thị thông báo.
        messagebox.showinfo(
            "Thông báo",
            "Quét Bài: UI đã sẵn sàng.\n\n"
            "Để gắn vào hệ thống thực tế, hãy implement đoạn code quét bài\n"
            "trong hàm do_scan() theo pipeline hiện tại (capture + recognize)\n"
            "và cập nhật last_cards_by_profile rồi gọi _update_profile_cards_panel().",
        )

        # Ví dụ minh hoạ (dummy) – bạn xoá đi khi gắn thật:
        # last_cards_by_profile[1] = ["2C", "2D", "2H", "2S"]
        # last_cards_by_profile[2] = ["3C", "3D", "3H", "3S"]
        # last_cards_by_profile[3] = ["4C", "4D", "4H", "4S"]
        _update_profile_cards_panel(scan_panel, base_dir, game_id, last_cards_by_profile)
        _update_profile_cards_panel(manage_panel, base_dir, game_id, last_cards_by_profile)

    def do_arrange() -> None:
        sel = get_selected_profiles()
        if not sel:
            messagebox.showinfo("Thông báo", "Chọn ít nhất 1 profile để Xếp Bài.")
            return

        # TODO: Gắn vào engine Mậu Binh của bạn.
        messagebox.showinfo(
            "Thông báo",
            "Xếp Bài: UI đã sẵn sàng.\n\n"
            "Để gắn vào hệ thống thực tế, hãy implement logic gọi engine\n"
            "Mậu Binh cho từng profile trong hàm do_arrange().",
        )

    btn_scan = tk.Button(
        top_bar,
        text="Quét Bài",
        command=do_scan,
        width=12,
    )
    btn_scan.grid(row=1, column=1, sticky="e", padx=4)

    btn_arrange = tk.Button(
        top_bar,
        text="Xếp Bài",
        command=do_arrange,
        width=12,
    )
    btn_arrange.grid(row=1, column=2, sticky="w", padx=4)

    btn_manage_cards = tk.Button(
        top_bar,
        text="Quản lý lá bài",
        command=show_manage_tab,
        width=16,
    )
    btn_manage_cards.grid(row=1, column=3, sticky="e", padx=4)

    # Mặc định hiển thị tab Quét/Xếp
    show_scan_tab()

    # ===== HƯỚNG DẪN NGẮN =====
    hint = tk.Label(
        root,
        text=(
            "- 3 nút trên cùng: Quét Bài / Xếp Bài / Quản lý lá bài.\n"
            "- Tab Quản lý lá bài: grid 52 lá, mỗi ô có ảnh gốc + import + quản lý biến thể.\n"
            "- Bên dưới mỗi tab có panel hiển thị bài hiện tại của Profile 1/2/3 (ở dạng ảnh).\n"
            "- TODO: Gắn do_scan() & do_arrange() vào pipeline nhận diện + engine Mậu Binh thực tế."
        ),
        justify="left",
        font=("Segoe UI", 8),
    )
    hint.grid(row=2, column=0, sticky="we", padx=8, pady=(0, 6))

    root.minsize(900, 600)
    root.mainloop()


def main() -> None:
    run_panel()


if __name__ == "__main__":
    main()
