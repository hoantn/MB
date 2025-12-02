# coding: utf-8
"""
Mậu Binh Automation UI (đa tab, tiếng Việt, responsive).

Tab "Lá bài & Vision":
- Lưới 52 lá hiển thị dạng 2♣, 2♦, 2♥, 2♠ với màu đỏ/đen.
- Lá đang chọn có viền xanh trên lưới, mặc định chọn lá đầu tiên (AS).
- Panel bên phải hiển thị cả tên lá (đỏ/đen) và hình ảnh lá đang chọn.
"""

from __future__ import annotations

import io
import csv
from datetime import datetime
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import yaml
from mb_profiles.profiles_model import ProfilesStore, ProfileConfig, DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_PROXY_TYPE
from mb_profiles.browser_manager import BrowserManager

from kendz.core.app_context import AppContext
from kendz.automation.window_binding import bind_window_for_profile, BoundWindow
from kendz.vision.pipeline import capture_and_crop_self_cards, capture_and_save_runtime_self_cards
from kendz.ui import LivePlayTab
from kendz.tools.assist_profile1 import recognize_13_cards
from kendz.engine.assistant import suggest_for_13_cards
from kendz.automation.mau_binh_click_plan import build_drag_plan_for_mau_binh
from kendz.browser.devtools_mouse import perform_drag_plan_via_devtools
from kendz.vision.layout_manager import LayoutManager
from kendz.cards.templates import CARD_CODES, get_templates_dir
from kendz.database.models import SessionModel, RoundModel, HandModel

# ---------------------------------------------------------------------------
# Hỗ trợ Drag & Drop (nếu có thư viện tkinterdnd2)
# ---------------------------------------------------------------------------

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES  # type: ignore

    TkBase = TkinterDnD.Tk  # type: ignore
    DND_AVAILABLE = True
except Exception:
    TkBase = tk.Tk
    DND_AVAILABLE = False


# ---------------------------------------------------------------------------
# Service: dùng dữ liệu thật của hệ thống
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    codes: List[str]
    chi1: List[str]
    chi2: List[str]
    chi3: List[str]
    desc: str


class MBBrowserService:
    """
    Lớp trung gian giữa UI và hệ thống:
    - Bootstrap AppContext một lần.
    - Cung cấp API dùng Vision + Engine + Automation thật.
    """

    def __init__(self) -> None:
        self.ctx = AppContext.bootstrap()
        self.logger = self.ctx.logger
        self.project_root = Path(__file__).resolve().parents[2]
        self.game_id = self.ctx.config.core.default_game_id
        self._card_image_cache: Dict[str, tk.PhotoImage] = {}
        self._bound_windows: Dict[int, BoundWindow] = {}

    # ----------------------------
    # Window binding
    # ----------------------------
    def bind_window(self, profile_id: int) -> BoundWindow:
        bound = bind_window_for_profile(self.game_id, profile_id, self.project_root)
        self._bound_windows[profile_id] = bound
        self.logger.info(
            "UI: Đã gắn cửa sổ cho profile=%d: hwnd=%s, rect=%s",
            profile_id,
            getattr(bound, "hwnd", None),
            getattr(bound, "rect", None),
        )
        return bound

    # ----------------------------
    # Quét bài: Vision + Engine (không kéo)
    # ----------------------------
    def scan_profile(self, profile_id: int) -> ScanResult:
        logger = self.logger
        logger.info("UI: Bắt đầu QUÉT BÀI cho profile=%d", profile_id)

        # Đảm bảo đã gắn cửa sổ cho profile này
        bound = self._bound_windows.get(profile_id)
        if bound is None:
            bound = self.bind_window(profile_id)

        # Lấy toạ độ cửa sổ (left, top, right, bottom)
        left = getattr(bound, "left", None)
        top = getattr(bound, "top", None)
        right = getattr(bound, "right", None)
        bottom = getattr(bound, "bottom", None)
        rect = getattr(bound, "rect", None)

        if rect is not None and isinstance(rect, tuple) and len(rect) == 4:
            left, top, right, bottom = rect

        if None in (left, top, right, bottom):
            # fallback an toàn: chụp full screen
            window_rect = None
        else:
            width = int(right - left)
            height = int(bottom - top)
            window_rect = (int(left), int(top), width, height)

        # Gửi window_rect vào pipeline để crop đúng vùng trình duyệt
        capture_and_crop_self_cards(
            self.ctx,
            profile_id=profile_id,
            window_rect=window_rect,
        )

        codes = recognize_13_cards(
            self.project_root,
            self.game_id,
            profile_id,
            logger,
        )
        if len(codes) != 13:
            raise RuntimeError(f"Mong đợi 13 lá, hiện có {len(codes)}: {codes!r}")

        logger.info("UI: 13 lá profile=%d: %s", profile_id, " ".join(codes))

        suggestion = suggest_for_13_cards(codes)

        chi1 = list(suggestion.chi1)
        chi2 = list(suggestion.chi2)
        chi3 = list(suggestion.chi3)

        desc = (
            "Chi 1: " + " ".join(chi1)
            + " | Chi 2: " + " ".join(chi2)
            + " | Chi 3: " + " ".join(chi3)
        )

        logger.info(
            "UI: Gợi ý profile=%d | chi1=%s | chi2=%s | chi3=%s",
            profile_id,
            " ".join(chi1),
            " ".join(chi2),
            " ".join(chi3),
        )

        return ScanResult(codes=codes, chi1=chi1, chi2=chi2, chi3=chi3, desc=desc)

    # ----------------------------
    # Xếp & kéo bài (auto drag)
    # ----------------------------
    def auto_drag_profile(self, profile_id: int, live: bool) -> ScanResult:
        ctx = self.ctx
        logger = self.logger
        game_id = self.game_id
        mode = "LIVE" if live else "DRY-RUN"

        logger.info(
            "UI: Bắt đầu XẾP & KÉO cho profile=%d, mode=%s",
            profile_id,
            mode,
        )

        bound = self._bound_windows.get(profile_id)
        if bound is None:
            bound = self.bind_window(profile_id)

        logger.info(
            "UI: Dùng bound window profile=%d rect=%s",
            profile_id,
            getattr(bound, "rect", None),
        )

        capture_and_save_runtime_self_cards(ctx, profile_id=profile_id)

        codes = recognize_13_cards(
            self.project_root,
            game_id,
            profile_id,
            logger,
        )
        if len(codes) != 13:
            raise RuntimeError(
                f"Mong đợi 13 lá, hiện có {len(codes)}: {codes!r}"
            )

        logger.info(
            "UI: 13 lá (auto_drag) profile=%d: %s",
            profile_id,
            " ".join(codes),
        )

        suggestion = suggest_for_13_cards(codes)
        chi1 = list(suggestion.chi1)
        chi2 = list(suggestion.chi2)
        chi3 = list(suggestion.chi3)

        desc = (
            "Chi 1: " + " ".join(chi1)
            + " | Chi 2: " + " ".join(chi2)
            + " | Chi 3: " + " ".join(chi3)
        )

        logger.info(
            "UI: Gợi ý (auto_drag) profile=%d | chi1=%s | chi2=%s | chi3=%s",
            profile_id,
            " ".join(chi1),
            " ".join(chi2),
            " ".join(chi3),
        )

        layout_mgr = LayoutManager(self.project_root)
        self_layout = layout_mgr.get_self_layout(game_id, profile_id=profile_id)

        actions = build_drag_plan_for_mau_binh(
            cards_current=codes,
            suggestion=suggestion,
            self_layout=self_layout,
            bound_win=bound,
        )
        if not actions:
            logger.info(
                "UI: Không cần kéo, bài đã khớp gợi ý (profile=%d).",
                profile_id,
            )
        else:
            perform_drag_plan_via_devtools(
                profile_id=profile_id,
                rect=bound.rect,
                actions=actions,
                live=live,
                logger=logger,
            )

        return ScanResult(codes=codes, chi1=chi1, chi2=chi2, chi3=chi3, desc=desc)

    # ----------------------------
    # Ảnh lá bài
    # ----------------------------
    def get_card_image(self, master: tk.Widget, code: str) -> Optional[tk.PhotoImage]:
        """
        Trả về tk.PhotoImage cho mã bài.
        - Ưu tiên data/card_templates/<game_id>/<CODE>.png hoặc CODE_1.png,...
        - Nếu không có thì trả None (UI chỉ hiển thị text).
        """
        code = (code or "").upper().strip()
        if not code:
            return None

        img = self._card_image_cache.get(code)
        if img is not None:
            return img

        tdir = get_templates_dir(self.project_root, self.game_id)
        candidates = [
            tdir / f"{code}.png",
            tdir / f"{code}_1.png",
        ]
        path: Optional[Path] = None
        for p in candidates:
            if p.exists():
                path = p
                break

        if path is None:
            self.logger.debug("UI: chưa có ảnh cho mã bài %s", code)
            return None

        try:
            img = tk.PhotoImage(master=master, file=str(path))
        except Exception as exc:
            self.logger.error("UI: lỗi load ảnh %s: %s", path, exc)
            return None

        self._card_image_cache[code] = img
        return img

    def clear_card_image_cache(self) -> None:
        """Dùng khi import template mới để UI load lại ảnh."""
        self._card_image_cache.clear()
        self.logger.info("UI: Đã xóa cache ảnh lá bài.")


    def get_runtime_self_card_image(
        self,
        master: tk.Widget,
        profile_id: int,
        slot_index: int,
    ) -> Optional[tk.PhotoImage]:
        """Trả về tk.PhotoImage cho lá bài đã crop realtime của 1 profile.

        - Ảnh được đọc từ data/runtime/self_cards/profile_{id}/slot_{index:02d}.png
          (do capture_and_save_runtime_self_cards tạo ra).
        - Có cache theo (profile_id, slot_index) để tránh load file nhiều lần.
        - Nếu file chưa tồn tại thì trả None, UI sẽ fallback về template gốc.
        """
        key = (int(profile_id), int(slot_index))
        img = getattr(self, "_runtime_card_cache", {}).get(key) if hasattr(self, "_runtime_card_cache") else None
        if img is not None:
            return img

        # Đảm bảo có cache dict
        if not hasattr(self, "_runtime_card_cache"):
            self._runtime_card_cache: Dict[Tuple[int, int], tk.PhotoImage] = {}

        project_root = self.project_root
        path = (
            project_root
            / "data"
            / "runtime"
            / "self_cards"
            / f"profile_{profile_id}"
            / f"slot_{slot_index:02d}.png"
        )

        if not path.exists():
            return None

        try:
            img = tk.PhotoImage(master=master, file=str(path))
        except Exception as exc:
            self.logger.error("UI: lỗi load ảnh runtime %s: %s", path, exc)
            return None

        self._runtime_card_cache[key] = img
        return img

    # ----------------------------
    # Cấu hình & DB & log (cho các tab khác)
    # ----------------------------
    def load_profiles_config(self) -> Tuple[list, dict]:
        profiles_yaml = self.project_root / "config" / "profiles.yaml"
        auto_yaml = self.project_root / "config" / "automation.yaml"
        profiles_data = []
        window_keywords: dict[int, str] = {}

        if profiles_yaml.exists():
            with profiles_yaml.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                profiles_data = data.get("profiles", [])

        if auto_yaml.exists():
            with auto_yaml.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                game_data = data.get(self.game_id, {})
                profs = game_data.get("profiles", {}) or {}
                for k, v in profs.items():
                    try:
                        pid = int(k)
                    except Exception:
                        continue
                    window_keywords[pid] = v.get("window_title_keyword", "")

        return profiles_data, window_keywords

    def get_strategy_mode(self) -> str:
        strategy_yaml = self.project_root / "config" / "strategy.yaml"
        if not strategy_yaml.exists():
            return "balance"
        with strategy_yaml.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return (data.get("strategy", {}) or {}).get("global_mode", "balance")

    def set_strategy_mode(self, mode: str) -> None:
        strategy_yaml = self.project_root / "config" / "strategy.yaml"
        data = {}
        if strategy_yaml.exists():
            with strategy_yaml.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        if "strategy" not in data:
            data["strategy"] = {}
        data["strategy"]["global_mode"] = mode
        with strategy_yaml.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True)
        self.logger.info("UI: cập nhật strategy.global_mode = %s", mode)

    def get_log_tail(self, max_lines: int = 200) -> str:
        log_path = self.project_root / "logs" / "kendz.log"
        if not log_path.exists():
            return "Chưa tìm thấy file logs/kendz.log"
        try:
            with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            tail = lines[-max_lines:]
            return "".join(tail)
        except Exception as exc:
            return f"Lỗi đọc log: {exc}"

    def get_recent_rounds(self, limit: int = 20) -> List[Tuple[RoundModel, List[HandModel]]]:
        SessionLocal = self.ctx.db_session_factory
        db = SessionLocal()
        try:
            rounds = (
                db.query(RoundModel)
                .order_by(RoundModel.started_at.desc())
                .limit(limit)
                .all()
            )
            hand_by_round: Dict[int, List[HandModel]] = {r.id: [] for r in rounds}
            if not rounds:
                return []
            round_ids = [r.id for r in rounds]
            hands = (
                db.query(HandModel)
                .filter(HandModel.round_id.in_(round_ids))
                .all()
            )
            for h in hands:
                hand_by_round.setdefault(h.round_id, []).append(h)
            return [(r, hand_by_round.get(r.id, [])) for r in rounds]
        except Exception as exc:
            self.logger.error("UI: lỗi đọc lịch sử round: %s", exc)
            return []
        finally:
            db.close()

    def get_latest_session(self) -> Optional[SessionModel]:
        SessionLocal = self.ctx.db_session_factory
        db = SessionLocal()
        try:
            s = (
                db.query(SessionModel)
                .order_by(SessionModel.started_at.desc())
                .first()
            )
            return s
        except Exception as exc:
            self.logger.error("UI: lỗi đọc session mới nhất: %s", exc)
            return None
        finally:
            db.close()

    # ----------------------------
    # Quản lý template lá bài
    # ----------------------------
    def get_templates_stats(self) -> Dict[str, int]:
        """
        Thống kê số lượng ảnh template theo mã bài trong thư mục.
        """
        tdir = get_templates_dir(self.project_root, self.game_id)
        stats: Dict[str, int] = {code: 0 for code in CARD_CODES}
        if not tdir.exists():
            return stats
        for p in tdir.iterdir():
            if not p.is_file():
                continue
            name = p.name.upper()
            base = name.split(".")[0]
            base = base.split("_")[0]
            if base in stats:
                stats[base] += 1
        return stats

    def list_card_variants(self, code: str) -> List[Path]:
        """
        Liệt kê các file biến thể cho 1 lá bài (AS.png, AS_1.png, ...).
        """
        code = (code or "").upper().strip()
        tdir = get_templates_dir(self.project_root, self.game_id)
        if not tdir.exists():
            return []
        files: List[Path] = []
        for p in tdir.iterdir():
            if not p.is_file():
                continue
            name = p.name.upper()
            if not name.endswith(".PNG"):
                continue
            stem = name[:-4]
            if stem == code or stem.startswith(code + "_"):
                files.append(p)
        files.sort()
        return files

    def add_card_variant_from_file(self, code: str, src_path: Path) -> Path:
        """
        Thêm 1 biến thể mới cho lá `code` từ file PNG người dùng chọn.
        - Chỉ chấp nhận PNG.
        - Tự đặt tên CODE.png hoặc CODE_n.png.
        """
        code = (code or "").upper().strip()
        if not code:
            raise ValueError("Mã lá bài không hợp lệ.")
        if not src_path.exists():
            raise FileNotFoundError(str(src_path))
        if src_path.suffix.lower() != ".png":
            raise ValueError("Chỉ hỗ trợ file PNG.")

        tdir = get_templates_dir(self.project_root, self.game_id)
        tdir.mkdir(parents=True, exist_ok=True)

        existing = self.list_card_variants(code)
        if not existing:
            dest_name = f"{code}.png"
        else:
            max_index = 0
            for p in existing:
                stem = p.stem
                parts = stem.split("_")
                if len(parts) == 2 and parts[0].upper() == code:
                    try:
                        idx = int(parts[1])
                    except Exception:
                        continue
                    if idx > max_index:
                        max_index = idx
            dest_name = f"{code}_{max_index + 1}.png"

        dest = tdir / dest_name
        from shutil import copy2
        copy2(src_path, dest)

        self._card_image_cache.pop(code, None)
        self.logger.info(
            "UI: thêm biến thể mới cho %s từ %s → %s", code, src_path, dest
        )
        return dest


# ---------------------------------------------------------------------------
# Widget phụ
# ---------------------------------------------------------------------------


def format_card_pretty(code: str) -> Tuple[str, str]:
    """
    Trả về (text_hiển_thị, màu_chữ) theo dạng 2♣/2♦/2♥/2♠.
    Nếu code không hợp lệ, trả lại code gốc và màu đen.
    """
    code = (code or "").upper().strip()
    if len(code) != 2:
        return code, "black"
    rank, suit = code[0], code[1]
    sym_map = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
    symbol = sym_map.get(suit)
    if not symbol:
        return code, "black"
    display = f"{rank}{symbol}"
    color = "red" if suit in ("H", "D") else "black"
    return display, color

# ---------------------------------------------------------------------------
# Main Tkinter App
# ---------------------------------------------------------------------------


class MainApp:
    """Tkinter main window cho Mậu Binh Control Panel (đa tab)."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Mậu Binh Automation")
        self.root.geometry("1400x900")
        self.root.minsize(1024, 600)

        # Service trung gian (bootstrap AppContext, Vision, Engine, Automation...)
        self.service = MBBrowserService()
        self.ctx = self.service.ctx
        self.project_root = self.service.project_root

        # Layout manager dùng chung cho LivePlayTab & VisionTab nếu cần
        self.layout_manager = None  # sẽ được LivePlayTab gán khi khởi tạo

        # Biến trạng thái "live" (chơi trực tiếp hay chỉ test)
        self.live_var = tk.BooleanVar(value=False)

        # Root layout: top (title + live toggle), center (notebook), bottom (status + events)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=0)
        self.root.rowconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=0)

        # Top bar
        top = ttk.Frame(self.root, padding=5)
        top.grid(row=0, column=0, sticky="nsew")
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=1)

        ttk.Label(
            top,
            text="Mậu Binh Automation",
            font=("Arial", 16, "bold"),
        ).grid(row=0, column=0, sticky="w")

        live_chk = ttk.Checkbutton(
            top,
            text="Chế độ LIVE (kéo bài thật)",
            variable=self.live_var,
        )
        live_chk.grid(row=0, column=1, sticky="e")

        # Notebook chứa các tab
        notebook = ttk.Notebook(self.root)
        notebook.grid(row=1, column=0, sticky="nsew")

        # Import các tab UI
        from kendz.ui import (
            LivePlayTab,
            ProfilesTab,
            CardsVisionTab,
            StrategyTab,
            LogsHistoryTab,
            SettingsTab,
        )

        # Tab chơi trực tiếp
        live_tab = LivePlayTab(notebook, self)
        notebook.add(live_tab, text="Chơi trực tiếp")

        # Tab hồ sơ & trình duyệt
        profiles_tab = ProfilesTab(notebook, self)
        notebook.add(profiles_tab, text="Hồ sơ & trình duyệt")

        # Tab 52 lá & Vision
        cards_tab = CardsVisionTab(notebook, self)
        notebook.add(cards_tab, text="Lá bài & Vision")

        # Tab chiến lược & Engine
        strategy_tab = StrategyTab(notebook, self)
        notebook.add(strategy_tab, text="Chiến lược & Engine")

        # Tab nhật ký & lịch sử
        logs_tab = LogsHistoryTab(notebook, self)
        notebook.add(logs_tab, text="Nhật ký & Lịch sử")

        # Tab cài đặt
        settings_tab = SettingsTab(notebook, self)
        notebook.add(settings_tab, text="Cài đặt & License")

        # Thanh trạng thái + event log ở dưới cùng
        bottom = ttk.Frame(self.root, padding=3)
        bottom.grid(row=2, column=0, sticky="nsew")
        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(0, weight=0)
        bottom.rowconfigure(1, weight=1)

        self._status_var = tk.StringVar(value="Sẵn sàng.")
        status_bar = ttk.Label(
            bottom,
            textvariable=self._status_var,
            relief="sunken",
            anchor="w",
            padding=(4, 2),
        )
        status_bar.grid(row=0, column=0, sticky="ew")

        self._events_text = tk.Text(
            bottom,
            height=3,
            state="disabled",
            font=("Consolas", 9),
        )
        self._events_text.grid(row=1, column=0, sticky="nsew")

    # API cho các tab gọi để hiển thị trạng thái
    def set_status(self, text: str) -> None:
        self._status_var.set(text)
        self.append_event(text)
        self.root.update_idletasks()

    def append_event(self, text: str) -> None:
        self._events_text.configure(state="normal")
        self._events_text.insert("end", f"- {text}\n")
        self._events_text.see("end")
        self._events_text.configure(state="disabled")

    def report_error(self, exc: Exception) -> None:
        msg = f"Lỗi: {exc}"
        self.append_event(msg)
        messagebox.showerror("Lỗi", msg)


def main() -> None:
    """Entry point chạy UI Control Panel."""
    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()