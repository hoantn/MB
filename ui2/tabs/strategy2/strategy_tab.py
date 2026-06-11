from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import hashlib
import threading
import queue
import re
import random
import time

from PySide6.QtCore import Qt, QTimer, QThread, Signal, Slot
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget, QVBoxLayout

from .modules.ngu_derive import NGUDeriver
from .modules.suggest_pipeline import SuggestPipeline

# UI perf guards
MAX_UI_P_ITEMS = 12
MAX_UI_NGU_ITEMS = 12

from core.logger import log
from core.apply_trace import apply_trace
from ui2.bridge.ws_card_store import ws_card_store
from ui2.bridge.ws_layout_store import ws_layout_store
from ui2.tabs.dashboard.dashboard_constants import FULL_DECK

from .strategy_view import StrategyView
from .strategy_suggest_worker import build_suggestions_for_codes
from .strategy_suggest import pick_default_suggestion
from .strategy_anti_sap import build_anti_sap_suggestions
from .strategy_combo_sap_lang import find_sap_lang_combo, SapLangCombo
from .strategy_special13 import detect_special_13  # FIX: use separated module

from .modules.ws_ingest import WSIngest, WSUpdate  # NEW: WS ingest module
from .modules.labeling import Labeling, LabelingContext
from .modules.special_row import (
    inject_special_row as _inject_special_row,
    is_special_row as _is_special_row,
)
from .modules.render_controller import RenderController
from .modules.staged_scheduler import StagedScheduler
from .modules.apply_controller import ApplyController
from .modules.auto_play_controller import (
    build_auto_play_plan,
    build_internal_balance_plan,
    build_internal_sap_ham_plan,
    build_money_fallback_plan,
    classify_auto_room_context,
)

from engine.card import Card

# ===================== SPECIAL 13-CARD HANDS (bài đặc biệt) =====================
# (ưu tiên special_name,key phải là lowercase; chỉ cần xuất hiện trong label_html.lower())
SPECIAL_ROW_KEYWORDS: List[Tuple[str, str]] = [
    # Sảnh rồng đồng hoa (ưu tiên đặt trước, vì chứa "sảnh rồng")
    ("sảnh rồng đồng hoa", "Sảnh rồng đồng hoa"),
    ("sanh rong dong hoa", "Sảnh rồng đồng hoa"),
    ("sr đồng hoa", "Sảnh rồng đồng hoa"),
    ("sr dong hoa", "Sảnh rồng đồng hoa"),

    # Sảnh rồng
    ("sảnh rồng", "Sảnh rồng"),
    ("sanh rong", "Sảnh rồng"),
    ("dragon", "Sảnh rồng"),

    # Đồng hoa (13 lá đồng màu)
    ("đồng hoa", "Đồng hoa"),
    ("dong hoa", "Đồng hoa"),

    # 6 đôi
    ("6 đôi", "6 Đôi"),
    ("6 doi", "6 Đôi"),
    ("6doi", "6 Đôi"),

    # 3 thùng
    ("3 thùng", "3 Thùng"),
    ("3 thung", "3 Thùng"),
    ("3thung", "3 Thùng"),

    # 3 sảnh
    ("3 sảnh", "3 Sảnh"),
    ("3 sanh", "3 Sảnh"),
    ("3sanh", "3 Sảnh"),

    # 5 đôi 1 xám
    ("5 đôi 1 xám", "5 Đôi 1 Xám"),
    ("5 doi 1 xam", "5 Đôi 1 Xám"),
    ("5doi1xam", "5 Đôi 1 Xám"),
]

# ===================== HIGH 5-CARD HANDS (bài cao trên từng chi) =====================
CHI_HIGH_KEYWORDS: List[Tuple[str, str]] = [
    # Thùng phá sảnh lớn (nếu Labeling dùng text này)
    ("thùng phá sảnh lớn", "TPS Lớn"),
    ("thung pha sanh lon", "TPS Lớn"),

    # Thùng phá sảnh
    ("thùng phá sảnh", "TPS"),
    ("thung pha sanh", "TPS"),

    # Tứ quý
    ("tứ quý", "Tứ Quý"),
    ("tu quy", "Tứ Quý"),
]

class StrategyTab(QWidget):
    # Thread-safe UI dispatcher: emit(callable) from ANY thread; will execute on UI thread.
    ui_call = Signal(object)

    @Slot(object)
    def _on_ui_call(self, fn) -> None:
        try:
            if callable(fn):
                fn()
        except Exception:
            log.exception('[Strategy2] ui_call handler error')

    def __init__(
        self,
        browser_manager,
        parent=None,
        card_store=None,
        room_engine=None,
        layout_store=None,
        game_controller=None,
        auto_play_log_sink=None,
        auto_settings_notifier=None,
    ):
        super().__init__(parent)

        # Ensure ui_call is connected on the owning (UI) thread.
        try:
            self.ui_call.connect(self._on_ui_call)
        except Exception:
            pass

        self.browser_manager = browser_manager
        # card_store=None → dùng global singleton (Tool 1 / backward compat)
        # card_store=<instance> → dùng per-tool store (Tool 2-4)
        self._card_store = card_store if card_store is not None else ws_card_store
        self._room_engine = room_engine
        self._layout_store = layout_store if layout_store is not None else ws_layout_store
        self._game_controller = game_controller

        self.capture_manager = (
            getattr(parent, "capture_manager", None)
            or getattr(browser_manager, "capture_manager", None)
            or getattr(browser_manager, "capture", None)
        )
        if self.capture_manager is None:
            try:
                from capture.capture_manager import CaptureManager

                self.capture_manager = CaptureManager(browser_manager)
            except Exception:
                log.exception("[Strategy2] cannot create CaptureManager fallback")

        self.MAX_UI_P_ITEMS = MAX_UI_P_ITEMS
        self.MAX_UI_NGU_ITEMS = MAX_UI_NGU_ITEMS

        self.profiles = ["P1", "P2", "P3"]
        self._ngu_deriver = NGUDeriver(self.profiles)
        self._pipeline = SuggestPipeline(self.profiles, FULL_DECK)
        self.active_profile = "P1"

        lay = QVBoxLayout(self)
        self.view = StrategyView(self.profiles, self)
        # Preserve card and action sizes on compact windows. Strategy remains
        # fully usable through scrollbars instead of shrinking card rows.
        self.view_scroll = QScrollArea()
        self.view_scroll.setWidgetResizable(True)
        self.view_scroll.setFrameShape(QFrame.NoFrame)
        self.view_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.view_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.view_scroll.setWidget(self.view)
        lay.addWidget(self.view_scroll)

        # UI events
        self.view.profile_changed.connect(self._on_profile_switch)
        self.view.p_label_clicked.connect(self._on_p_label_clicked)
        self.view.ngu_label_clicked.connect(self._on_ngu_label_clicked)
        self.view.btn_hup.clicked.connect(lambda: self._on_apply(self.active_profile))
        self.view.apply_all_clicked.connect(self._on_apply_all)
        self.view.break_sap_lang_clicked.connect(self._on_break_sap_lang)
        
        # retry gợi ý P ACTIVE khi không có gợi ý
        if hasattr(self.view, "p_retry_clicked"):
            self.view.p_retry_clicked.connect(self._on_p_retry_clicked)

        # WS -> slot order codes (reverse y hệt dashboard)
        self._codes_slot_order: Dict[str, List[str]] = {pid: [] for pid in self.profiles}
        self._ws_snapshot: Dict[str, Optional[List[str]]] = {pid: None for pid in self.profiles}
        self._last_hand_hash: Dict[str, Optional[str]] = {pid: None for pid in self.profiles}
        # Tăng đúng một lần khi nhận bộ bài mới của từng P. Auto dùng generation
        # để không nhầm hai ván khác nhau vô tình có cùng bộ 13 lá.
        self._hand_generation: Dict[str, int] = {pid: 0 for pid in self.profiles}

        self._layout_codes: Dict[str, List[str]] = {}

        self._suggestions: Dict[str, List[dict]] = {pid: [] for pid in self.profiles}
        self._suggestions_render: Dict[str, List[dict]] = {pid: [] for pid in self.profiles}
        self._selected_index: Dict[str, int] = {pid: 0 for pid in self.profiles}

        self._ngu_base_codes: List[str] = []
        self._ngu_suggestions: List[dict] = []
        self._ngu_selected_index: int = 0
        self._ngu_key: Optional[str] = None
        self._sap_lang_combo: Optional[SapLangCombo] = None
        self._auto_play_enabled: bool = False
        self._auto_play_remaining: int = 0
        self._auto_play_delay_min_ms: int = 8000
        self._auto_play_delay_max_ms: int = 18000
        self._auto_play_hand_key: Optional[str] = None
        self._auto_play_pending_key: Optional[str] = None
        self._auto_play_applied_profile_keys = set()
        self._auto_play_reservations: Dict[str, str] = {}
        self._auto_apply_unsafe_retry_counts: Dict[str, int] = {}
        self._auto_play_counted_round_keys = set()
        # Internal cycle: N no-sweep rounds, one sap-ham round, then one
        # independent Money round before allowing internal balance again.
        self._auto_play_internal_cycle_limit: int = 4
        self._auto_play_internal_streak: int = 0
        self._auto_play_internal_sap_ham_done: bool = False
        self._auto_play_round_modes: Dict[str, str] = {}
        self._auto_play_session: int = 0
        self._auto_play_log_sink = auto_play_log_sink
        self._auto_settings_notifier = auto_settings_notifier
        self._missing_3p_alert_timer = QTimer(self)
        self._missing_3p_alert_timer.setSingleShot(True)
        self._missing_3p_alert_timer.setInterval(100)
        self._missing_3p_alert_timer.timeout.connect(self._check_missing_3p_alert)
        # Đánh dấu đã từng click chọn 1 gợi ý OPP/NGU hay chưa
        self._ngu_clicked_once: bool = False

        # Anti-sap uses bounded smart permutations for P hands only.
        # NGU stays fixed as the reference hand.
        self._anti_sap_enabled: bool = True

        # gen + result queue (extended tuple)
        self._gen: Dict[str, int] = {pid: 0 for pid in (self.profiles + ["NGU"])}
        self._q: "queue.Queue[tuple]" = queue.Queue()

        # =================== NEW: staged scheduler (sequential) ===================
        self._scheduler = StagedScheduler()

        self._batch_debounce = QTimer(self)
        self._batch_debounce.setSingleShot(True)
        self._batch_debounce.setInterval(140)
        self._batch_debounce.timeout.connect(self._enqueue_batch_jobs)

        self._scheduled_hash: Dict[str, Optional[str]] = {pid: None for pid in (self.profiles + ["NGU"])}
        # ========================================================================

        self._poll_suggest_timer = QTimer(self)
        self._poll_suggest_timer.setInterval(50)
        self._poll_suggest_timer.timeout.connect(self._poll_suggest_results)
        self._poll_suggest_timer.start()

        # NEW: ws ingest module
        self._ws_ingest = WSIngest(self.profiles, reverse_like_dashboard=True)

        self._ws_timer = QTimer(self)
        self._ws_timer.setInterval(200)
        self._ws_timer.timeout.connect(self._poll_ws)
        self._ws_timer.start()

        self._apply_threads: Dict[str, threading.Thread] = {}
        self._scan_threads: Dict[str, QThread] = {}
        # WS freeze window: chặn same-hand update trong lúc kéo
        self._ws_freeze: Dict[str, bool] = {}

        # Pending same-hand snapshot (khi ws_freeze hoặc busy)
        self._pending_ws_samehand: Dict[str, List[str]] = {}

        self._labeling = Labeling()
        self._labeling.set_cache_limits(chi_type_cache_limit=5000, cmp_cache_limit=8000)

        self._renderer = RenderController(MAX_UI_P_ITEMS, MAX_UI_NGU_ITEMS)
        self._apply_controller = ApplyController()
        self._on_profile_switch(self.active_profile)

    def set_runtime_services(
        self,
        *,
        room_engine=None,
        layout_store=None,
        game_controller=None,
        auto_play_log_sink=None,
        auto_settings_notifier=None,
    ) -> None:
        """Attach per-tool runtime services; fallback globals remain for the main Strategy tab."""
        if room_engine is not None:
            self._room_engine = room_engine
        if layout_store is not None:
            self._layout_store = layout_store
        if game_controller is not None:
            self._game_controller = game_controller
        if auto_play_log_sink is not None:
            self._auto_play_log_sink = auto_play_log_sink
        if auto_settings_notifier is not None:
            self._auto_settings_notifier = auto_settings_notifier

    def _get_room_engine(self):
        room_engine = getattr(self, "_room_engine", None)
        if room_engine is not None:
            return room_engine
        try:
            return getattr(self.window(), "room_engine", None)
        except Exception:
            return None

    def _get_game_controller(self):
        controller = getattr(self, "_game_controller", None)
        if controller is not None:
            return controller
        try:
            return getattr(self.window(), "game_controller", None)
        except Exception:
            return None

    @property
    def log(self):
        return log

    @property
    def build_anti_sap_suggestions(self):
        return build_anti_sap_suggestions

    # =================== helpers ===================
    def _hand_hash(self, codes: List[str]) -> str:
        """Nhận diện bộ 13 lá, không phụ thuộc thứ tự slot/layout."""
        m = hashlib.md5()
        for c in sorted(map(str, codes)):
            m.update(str(c).encode("utf-8"))
            m.update(b"|")
        return m.hexdigest()

    # =================== SPECIAL 13 (Bài đặc biệt) ===================
    _SPECIAL_MODE = "__special13__"

    def _is_special_row(self, s: Optional[dict]) -> bool:
        return _is_special_row(s, special_mode=self._SPECIAL_MODE)

    def _inject_special_row_for_profile(self, pid: str, ws13: List[str], render_suggs: List[dict]) -> List[dict]:
        return _inject_special_row(
            pid,
            ws13,
            render_suggs,
            special_mode=self._SPECIAL_MODE,
            detect_special_13_fn=detect_special_13,
        )

    # =================== per-chi name ===================
    def _rebuild_ngu_labels_html(self) -> None:
        if not self._ngu_suggestions:
            return

        # ÁP DỤNG BỘ LỌC ÁP CHẾ CHO OPP/NGU
        try:
            self._ngu_suggestions = self._renderer._filter_dominated_suggestions(
                self,
                list(self._ngu_suggestions),
            )
        except Exception:
            self._ngu_suggestions = list(self._ngu_suggestions)

        # Sau khi lọc, build lại label cho tối đa MAX_UI_NGU_ITEMS item
        for s in self._ngu_suggestions[:MAX_UI_NGU_ITEMS]:
            if self._is_special_row(s):
                continue
            ctx = LabelingContext(
                profiles=self.profiles,
                active_profile=self.active_profile,
                suggestions=self._suggestions,
                suggestions_render=self._suggestions_render,
                selected_index=self._selected_index,
                max_ui_ngu_items=MAX_UI_NGU_ITEMS,
            )
            s["label_html"] = self._labeling.build_label_html_ngu_vs_3p(
                s, ctx, self._is_special_row
            )
    def _normalize_special_label_text(self, raw_html: str) -> str:
        """
        Chuẩn hóa text bài đặc biệt (special row) để hiển thị cạnh Chi 3:
        - Bỏ tag HTML, emoji, mã màu, mã type (#9, #10...)
        - Dò SPECIAL_ROW_KEYWORDS để map về label đẹp: 'Sảnh rồng đồng hoa', '6 Đôi', ...
        """
        # 1) bóc text thuần
        text = re.sub(r"<[^>]+>", "", str(raw_html))
        text = text.replace("🏆", "")  # bỏ icon cúp nếu có
        text = text.strip()

        # 2) xóa mã màu dạng #RRGGBB / #RGB / #RRGGBBAA
        text = re.sub(r"#([0-9a-fA-F]{3,8})", "", text)

        # 3) xóa mã số kiểu "#9", "#10" đứng độc lập
        text = re.sub(r"(?:^|\s)#\d+\b", " ", text)

        # 4) chuẩn hóa khoảng trắng
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return ""

        lower = text.lower()

        # 5) ưu tiên map đúng các bài đặc biệt đã định nghĩa
        for key, label in SPECIAL_ROW_KEYWORDS:
            if key in lower:
                return label

        # 6) fallback: không map được thì trả về text đã làm sạch
        return text
    # =================== Special label (bài đặc biệt 13 lá + bài cao chi 1/2) ===================
    def _build_special_label_for_suggestion(self, sug: Optional[dict]) -> Tuple[str, Optional[str]]:
        """
        Trả về (text, color) cho label cạnh Chi 3:
        - text:
            + Bài đặc biệt 13 lá: 'Sảnh rồng đồng hoa', 'Đồng hoa', '6 Đôi', '3 Sảnh', '3 Thùng', '5 Đôi 1 Xám'...
            + Bài cao trên chi: 'TPS Lớn', 'TPS', 'Tứ Quý'
            → Ghép dạng: 'Sảnh rồng đồng hoa | TPS | Tứ Quý' tùy bài.
        - color:
            + Nếu có chi cao (TPS / Tứ Quý / TPS Lớn) → dùng màu chi tương ứng.
            + Nếu chỉ có bài đặc biệt 13 lá → màu vàng nổi bật.
        """
        if not sug:
            return ("", None)

        tokens: List[str] = []
        color: Optional[str] = None

        # 1) Nếu là dòng bài đặc biệt (special row 13 lá) -> lấy tên đã gán sẵn (special_name)
        try:
            if self._is_special_row(sug):
                # Ưu tiên tuyệt đối: dùng special_name để tránh parse HTML (&nbsp;, span màu, ...)
                plain = str(sug.get("special_name") or "").strip()

                # Fallback an toàn (giữ lại): nếu vì lý do nào đó thiếu special_name thì mới parse HTML như cũ
                if not plain:
                    html = sug.get("label_html") or sug.get("label") or ""
                    plain = self._normalize_special_label_text(html)

                if plain:
                    tokens.append(plain)
                    # màu vàng nổi bật cho bài đặc biệt 13 lá
                    color = "#fbbf24"
        except Exception:
            pass

        # 2) Đọc type của 3 chi để tìm bài cao (Tứ Quý / TPS / TPS Lớn)
        names_colors: List[Tuple[str, str]] = []
        for chi_idx, key in enumerate(["chi1_codes", "chi2_codes", "chi3_codes"], start=1):
            chi = list(sug.get(key) or [])
            if not chi:
                names_colors.append(("", "#9ca3af"))
                continue
            try:
                _, name, col = self._labeling.chi_type(chi, chi_idx)
                names_colors.append((name or "", col or "#9ca3af"))
            except Exception:
                names_colors.append(("", "#9ca3af"))

        # 3) Scan các chi, dò CHI_HIGH_KEYWORDS
        for name, col in names_colors:
            lower = (name or "").lower().strip()
            if not lower:
                continue

            for key, token in CHI_HIGH_KEYWORDS:
                if key in lower:
                    if token not in tokens:
                        tokens.append(token)
                    if color is None:
                        color = col
                    break  # sang chi tiếp theo

        text = " | ".join(tokens)
        if not text:
            return ("", None)

        if color is None:
            # không có chi cao, chỉ có bài đặc biệt 13 lá → giữ màu vàng
            color = "#facc15"

        return (text, color)
        
    def _update_special_labels(self) -> None:
        """
        Đồng bộ label đặc biệt cạnh Chi 3 cho:
        - P (active_profile): gộp info từ gợi ý đang chọn + dòng special (nếu có)
        - NGU: gộp info từ gợi ý OPP đang chọn + dòng special (nếu có)
        """
        try:
            # ================== P ACTIVE ==================
            pid = self.active_profile
            p_tokens: List[str] = []
            p_color: Optional[str] = None

            # 1) gợi ý đang chọn của P
            p_sug: Optional[dict] = None
            lst_p = self._suggestions_render.get(pid) or []
            idx = int(self._selected_index.get(pid, 0) or 0)
            if lst_p:
                if idx < 0 or idx >= len(lst_p):
                    idx = 0
                p_sug = lst_p[idx]

            text_sel, color_sel = self._build_special_label_for_suggestion(p_sug)
            if text_sel:
                for tok in text_sel.split(" | "):
                    tok = tok.strip()
                    if tok and tok not in p_tokens:
                        p_tokens.append(tok)
                p_color = color_sel or p_color

            # 2) dòng special row (bài đặc biệt) nếu có trong list P
            p_special: Optional[dict] = None
            for s in lst_p:
                if self._is_special_row(s):
                    p_special = s
                    break

            if p_special is not None:
                text_sp, color_sp = self._build_special_label_for_suggestion(p_special)
                if text_sp:
                    for tok in text_sp.split(" | "):
                        tok = tok.strip()
                        if tok and tok not in p_tokens:
                            p_tokens.append(tok)
                    if p_color is None:
                        p_color = color_sp or p_color

            p_text = " | ".join(p_tokens)
            if not p_text:
                self.view.set_p_special_text("", None)
            else:
                # fallback màu vàng nếu vẫn chưa có
                if p_color is None:
                    p_color = "#facc15"
                self.view.set_p_special_text(p_text, p_color)

            # ================== NGU ==================
            ngu_tokens: List[str] = []
            ngu_color: Optional[str] = None

            ngu_sug: Optional[dict] = None
            lst_ngu = self._ngu_suggestions or []

            if lst_ngu:
                j = self._ngu_selected_index
                if j < 0 or j >= len(lst_ngu):
                    j = 0
                # vẫn giữ rule bỏ qua special khi chọn OPP để so sánh chi,
                # nhưng label vẫn sẽ gộp info từ special row ở bước sau
                if (
                    lst_ngu
                    and self._is_special_row(lst_ngu[0])
                    and j <= 0
                    and len(lst_ngu) > 1
                ):
                    j = 1
                if 0 <= j < len(lst_ngu):
                    ngu_sug = lst_ngu[j]

            text_sel_ngu, color_sel_ngu = self._build_special_label_for_suggestion(ngu_sug)
            if text_sel_ngu:
                for tok in text_sel_ngu.split(" | "):
                    tok = tok.strip()
                    if tok and tok not in ngu_tokens:
                        ngu_tokens.append(tok)
                ngu_color = color_sel_ngu or ngu_color

            # special row NGU (thường ở index 0 nếu có)
            ngu_special: Optional[dict] = None
            for s in lst_ngu:
                if self._is_special_row(s):
                    ngu_special = s
                    break

            if ngu_special is not None:
                text_sp_ngu, color_sp_ngu = self._build_special_label_for_suggestion(ngu_special)
                if text_sp_ngu:
                    for tok in text_sp_ngu.split(" | "):
                        tok = tok.strip()
                        if tok and tok not in ngu_tokens:
                            ngu_tokens.append(tok)
                    if ngu_color is None:
                        ngu_color = color_sp_ngu or ngu_color

            ngu_text = " | ".join(ngu_tokens)
            if not ngu_text:
                self.view.set_ngu_special_text("", None)
            else:
                if ngu_color is None:
                    ngu_color = "#facc15"
                self.view.set_ngu_special_text(ngu_text, ngu_color)

        except Exception:
            self.log.exception("[Strategy2] _update_special_labels failed")

    def _find_money_base(self, suggs: List[dict]) -> Optional[dict]:
        return self._renderer.find_money_base(suggs)

    def _build_render_suggestions(self, base_suggs: List[dict], opp: Optional[dict]) -> List[dict]:
        return self._renderer.build_render_suggestions(self, base_suggs, opp)
        
    def _pre_render_profile(self, pid: str) -> None:
        """
        Pre-render (compute-only) for a profile WITHOUT touching UI.
        - Prepares: self._suggestions_render[pid] (with label_html computed)
        - Also ensures self._selected_index[pid] is a valid default when new hand starts.
        """
        base_suggs = self._suggestions.get(pid) or []
        if not base_suggs:
            self._suggestions_render[pid] = []
            return

        # Determine NGU selection (opp) similar to active render
        opp = None
        if self._ngu_suggestions:
            j = self._ngu_selected_index
            if j < 0 or j >= len(self._ngu_suggestions):
                j = 0
            if self._ngu_suggestions and self._is_special_row(self._ngu_suggestions[0]) and j <= 0 and len(self._ngu_suggestions) > 1:
                j = 1
            cand = self._ngu_suggestions[j] if 0 <= j < len(self._ngu_suggestions) else None
            if cand and (not self._is_special_row(cand)):
                opp = cand

        render_suggs = self._build_render_suggestions(base_suggs, opp)

        # Ensure selected index is valid (key point: remove "must active to pick")
        idx = int(self._selected_index.get(pid, 0))
        if idx < 0 or idx >= len(render_suggs):
            idx = self.pick_default_suggestion(render_suggs)
            if idx < 0:
                idx = 0
        # if render_suggs and self._is_special_row(render_suggs[0]) and idx <= 0 and len(render_suggs) > 1:
            # idx = 1
        self._selected_index[pid] = idx

        # Compute label_html for top items only (CPU guard)
        for s in render_suggs[:self.MAX_UI_P_ITEMS]:
            if self._is_special_row(s):
                continue
            if not s.get("_split_key"):
                s["_split_key"] = self._make_split_key(s)

            # keep same sap-lang flags logic as active
            try:
                lang_win, lang_lose = self._compute_sap_lang_flags_for_active_suggestion(pid, s)
                s["_sap_lang_win"] = bool(lang_win)
                s["_sap_lang_lose"] = bool(lang_lose)
            except Exception:
                pass

            # IMPORTANT: build label_html (thắng/thua) now, so switching tab is instant
            try:
                s["label_html"] = self._labeling.build_label_html_vs(s, opp)
            except Exception:
                s["label_html"] = s.get("label_html", "")

        self._suggestions_render[pid] = list(render_suggs[:self.MAX_UI_P_ITEMS])

    # =================== WS / dedup (now delegated to WSIngest) ===================
    def _force_reset_pid_state(self, pid: str) -> None:
        """HƯỚNG A: WS snapshot 13 lá mới => invalidate toàn bộ state cũ của pid."""
        # 1) suggestions + render + selection
        self._suggestions[pid] = []
        self._suggestions_render[pid] = []
        self._selected_index[pid] = -1
        try:
            self._confirmed_apply_tokens.pop(pid, None)
        except Exception:
            pass

        # 2) last_hand_hash không còn ý nghĩa theo Hướng A (vẫn có thể giữ để debug)
        self._last_hand_hash[pid] = None
        # Thu hồi state Auto cũ của riêng P này; không chạm P khác đang chạy.
        prefix = f"{pid}:"
        self._auto_play_applied_profile_keys = {
            key for key in self._auto_play_applied_profile_keys
            if not str(key).startswith(prefix)
        }
        self._auto_play_reservations = {
            key: value for key, value in self._auto_play_reservations.items()
            if not str(key).startswith(prefix)
        }
        self._auto_apply_unsafe_retry_counts = {
            key: value for key, value in self._auto_apply_unsafe_retry_counts.items()
            if not str(key).startswith(prefix)
        }
        # Khi bất kỳ P nào reset bài, coi như NGU key cũ không còn giá trị
        self._ngu_key = None
        self._sap_lang_combo = None
        try:
            self.view.set_break_sap_lang_available(False)
        except Exception:
            pass
        # 3) clear UI list ngay nếu pid đang active
        if pid == self.active_profile:
            try:
                self.view.set_p_labels([], 0)
            except Exception:
                pass
            try:
                self.view.btn_hup.setEnabled(False)
            except Exception:
                pass
            try:
                self.view.set_p_status("Đang đồng bộ bài…")
            except Exception:
                pass
            try:
                self.view.set_p_special_text("", None)
            except Exception:
                pass

        # 4) clear worker cache theo pid (sẽ thêm hàm này ở strategy_suggest_worker.py)
        try:
            from .strategy_suggest_worker import clear_cache_for_pid  # local import tránh vòng import
            clear_cache_for_pid(pid)
        except Exception:
            pass


    def _apply_pending_ws_reset_if_any(self, pid: str) -> None:
        """Nếu WS đến đúng lúc đang apply (busy), hoãn reset và apply sau khi apply xong."""
        pend = getattr(self, "_pending_ws_reset", None)
        if not isinstance(pend, dict):
            return
        codes = pend.pop(pid, None)

        if codes and isinstance(codes, list) and len(codes) == 13:
            # áp dụng lại như một WS update "force"
            self._force_reset_pid_state(pid)
            self._hand_generation[pid] = int(self._hand_generation.get(pid, 0) or 0) + 1
            self._last_hand_hash[pid] = self._hand_hash(codes)
            self._codes_slot_order[pid] = list(codes)
            self._layout_codes[pid] = list(codes)
            if pid == self.active_profile:
                self.view.set_cards_p_normalized(list(codes))
                self.view.set_p_status("Đang tính gợi ý…")
            # trigger staged scheduler
            self._batch_debounce.stop()
            self._batch_debounce.start()
            self._schedule_missing_3p_alert()
    def _apply_pending_ws_samehand_if_any(self, pid: str) -> None:
        try:
            codes = (getattr(self, "_pending_ws_samehand", {}) or {}).pop(pid, None)
        except Exception:
            codes = None

        if not (codes and isinstance(codes, list) and len(codes) == 13):
            return

        # SAME HAND: cmd=606/layout snapshot syncs only the real game layout.
        # Do not mutate _codes_slot_order; it is the cmd=600 hand base used by
        # suggestions, NGU derivation and Auto strategy.
        self._layout_codes[pid] = list(codes)

        if pid == self.active_profile:
            try:
                if self._suggestions_render.get(pid) or self._suggestions.get(pid):
                    self._render_p_active()
                else:
                    self.view.set_cards_p_normalized(list(codes))
            except Exception:
                pass
        log.debug("[WS SAME HAND] layout synced pid=%s first3=%s", pid, list(codes)[:3])

    def _poll_ws(self) -> None:
        updates, waiting = self._ws_ingest.poll(
            ws_get_last_cards=self._card_store.get_last_cards,
            ws_snapshot=self._ws_snapshot,
            last_hand_hash=self._last_hand_hash,
            hand_hash_fn=self._hand_hash,
        )

        # keep original behavior: if waiting and active -> show status
        if self.active_profile in waiting:
            self.view.set_p_status("Chờ bài…")

        any_new_hand = False

        # Defensive: busy map exists only after first _apply_btn_set_busy call
        busy_map = getattr(self, "_apply_busy", None) or {}
        freeze_map = getattr(self, "_ws_freeze", None) or {}

        for up in updates:
            pid = up.pid
            log.warning(
                "[WS->Strategy] pid=%s is_new_hand=%s busy=%s hand_hash=%s last_hash=%s first3=%s",
                up.pid,
                up.is_new_hand,
                busy_map.get(up.pid, False),
                up.hand_hash[:6],
                (self._last_hand_hash.get(up.pid)[:6] if self._last_hand_hash.get(up.pid) else None),
                up.codes_slot_order[:3],
            )

            codes = list(up.codes_slot_order or [])
            if len(codes) != 13:
                continue

            # Mark the raw WS packet as seen even while apply is running, so an
            # old in-drag 606 is not replayed after the freeze opens. The apply
            # worker uses the tab layout store sequence/time to choose post-drag 606.
            self._ws_snapshot[pid] = list(up.raw_cards)

            # HƯỚNG A: Nếu đang apply => hoãn reset (pending), không đụng state ngay
            if busy_map.get(pid, False) or freeze_map.get(pid, False):
                if up.is_new_hand:
                    if not hasattr(self, "_pending_ws_reset"):
                        self._pending_ws_reset = {}
                    self._pending_ws_reset[pid] = list(codes)
                    log.warning("[WS PENDING RESET] pid=%s (busy/freeze) first3=%s", pid, codes[:3])
                else:
                    if not hasattr(self, "_pending_ws_samehand"):
                        self._pending_ws_samehand = {}
                    self._pending_ws_samehand[pid] = list(codes)
                    log.warning("[WS PENDING SAMEHAND] pid=%s (busy/freeze) first3=%s", pid, codes[:3])
                continue

            # HƯỚNG A: WS 13 lá => reset tuyệt đối + set cards + trigger compute
            try:
                busy = (getattr(self, "_apply_busy", {}) or {}).get(pid, False)
                log.warning("[WS BEFORE FORCE] pid=%s busy=%s first3=%s", pid, busy, list(codes)[:3])
            except Exception:
                pass

            if up.is_new_hand:
                log.warning("[WS FORCE RESET] pid=%s first3=%s", pid, codes[:3])
                self._force_reset_pid_state(pid)
                self._hand_generation[pid] = int(self._hand_generation.get(pid, 0) or 0) + 1
                self._last_hand_hash[pid] = up.hand_hash

                self._codes_slot_order[pid] = list(codes)
                self._layout_codes[pid] = list(codes)

                if pid == self.active_profile:
                    self.view.set_cards_p_normalized(list(codes))
                    log.info("[UI SET CARDS] pid=%s first3=%s", pid, codes[:3])
                    self.view.set_p_status("Đang tính gợi ý…")

                self._batch_debounce.stop()
                self._batch_debounce.start()
                any_new_hand = True
            else:
                # SAME HAND: cmd=606/layout snapshot updates only current layout.
                # Keep _codes_slot_order as the cmd=600 hand base so 606 cannot
                # perturb suggestions, NGU derivation or Auto strategy.
                self._layout_codes[pid] = list(codes)
                if pid == self.active_profile:
                    try:
                        if self._suggestions_render.get(pid) or self._suggestions.get(pid):
                            self._render_p_active()
                        else:
                            self.view.set_cards_p_normalized(list(codes))
                    except Exception:
                        pass
                log.debug("[WS SAME HAND] layout synced pid=%s first3=%s", pid, list(codes)[:3])


        if any_new_hand:
            self._refresh_ngu_from_3p(force=True)
            self._schedule_missing_3p_alert()

    # =================== NEW: staged sequential scheduler ===================
    @property
    def build_suggestions_for_codes(self):
        return build_suggestions_for_codes

    @property
    def pick_default_suggestion(self):
        return pick_default_suggestion

    @property
    def LabelingContext(self):
        return LabelingContext

    def _enqueue_batch_jobs(self) -> None:
        return self._scheduler.enqueue_batch_jobs(self)

    def _run_next_job(self) -> None:
        return self._scheduler.run_next_job(self)

    def _build_base_suggestion(self, key: str, codes: List[str], kind: str) -> Optional[dict]:
        res = self._pipeline.build_base_suggestion(key, codes, kind)
        if res is None:
            log.error("[Strategy2] base suggestion failed key=%s kind=%s", key, kind)
        return res

    def _filter_extras(self, full: List[dict]) -> List[dict]:
        return self._pipeline.filter_extras(full)

    def _poll_suggest_results(self) -> None:
        self._scheduler.poll_suggest_results(self)

    # =================== legacy worker (kept) ===================
    def _start_suggest_worker(self, key: str, codes: List[str]) -> None:
        self._gen[key] = int(self._gen.get(key, 0)) + 1
        gen = self._gen[key]
        codes_cp = list(codes)

        def _worker():
            try:
                out = build_suggestions_for_codes(key, codes_cp)
                self._q.put((key, gen, out, None))
            except Exception as e:
                self._q.put((key, gen, None, e))

        threading.Thread(target=_worker, name=f"MB-Strategy2-Suggest-{key}", daemon=True).start()

    def _make_split_key(self, s: dict) -> str:
        try:
            c1 = tuple(sorted(map(str, s.get("chi1_codes") or [])))
            c2 = tuple(sorted(map(str, s.get("chi2_codes") or [])))
            c3 = tuple(sorted(map(str, s.get("chi3_codes") or [])))
            return "|".join([",".join(c3), ",".join(c2), ",".join(c1)])
        except Exception:
            return ""

    # =================== render ===================
    def _build_preview_codes(self, suggestion: dict) -> Optional[List[str]]:
        return self._renderer.build_preview_codes(suggestion)

    def _render_ngu(self) -> None:
        self._renderer.render_ngu(self)
        self._update_special_labels()   # mỗi lần render OPP, cập nhật label
        self._refresh_sap_lang_combo()

    def _render_p_active(self) -> None:
        self._renderer.render_p_active(self)
        self._update_special_labels()   # mỗi lần render P active, cập nhật label
        self._refresh_sap_lang_combo()
        self._sync_apply_button_enabled()


    # =================== NGU derive ===================
    def _derive_ngu_from_3p(self) -> Optional[List[str]]:
        res = self._ngu_deriver.derive(self._codes_slot_order, FULL_DECK)
        if not res:
            return None
        return list(res.codes13)

    def _refresh_ngu_from_3p(self, force: bool) -> None:
        res = self._ngu_deriver.derive(self._codes_slot_order, FULL_DECK)

        # Không đủ 3P -> clear hoàn toàn OPP
        if res is None:
            self._ngu_base_codes = []
            self._ngu_suggestions = []
            self._ngu_selected_index = 0
            self.view.set_ngu_status("Chờ đủ 3P để suy NGU…")
            self.view.set_cards_ngu_normalized([])
            self.view.set_ngu_labels([], 0)
            self.view.set_ngu_labels([], 0)
            try:
                self.view.set_ngu_special_text("", None)
            except Exception:
                pass
            return

        # Nếu không force và key giống hệt ván cũ -> không làm gì
        if (not force) and self._ngu_key == res.key:
            return

        # NGU sang ván mới (hoặc bị force) -> reset state OPP tuyệt đối
        self._ngu_key = res.key
        self._ngu_base_codes = list(res.codes13)

        # QUAN TRỌNG: xóa mọi gợi ý & selection OPP của ván trước
        self._ngu_suggestions = []
        self._ngu_selected_index = 0
        self.view.set_cards_ngu_normalized([])
        self.view.set_ngu_labels([], 0)
        self.view.set_ngu_status("Đang tính gợi ý NGU…")
        # Reset cờ "đã click OPP" cho ván mới
        self._ngu_clicked_once = False

        # (tuỳ chọn nhưng nên thêm) clear cache worker cho NGU để tránh reuse nhầm
        try:
            from .strategy_suggest_worker import clear_cache_for_pid
            clear_cache_for_pid("NGU")
        except Exception:
            pass

        # Trigger staged scheduler debounce để tính lại gợi ý cho NGU
        self._batch_debounce.stop()
        self._batch_debounce.start()

    # =================== Apply ===================
    def _on_apply(self, pid: str):
        try:
            busy = (getattr(self, "_apply_busy", {}) or {}).get(pid, False)
            log.warning("[APPLY CLICK] pid=%s busy=%s", pid, busy)
        except Exception:
            pass
        return self._apply_controller.on_apply(self, pid)

    def _on_apply_all(self) -> None:
        """
        Apply ALL:
        - Snapshot P1/P2/P3 without switching active_profile.
        - Start per-profile apply workers with a small stagger.
        """
        try:
            self._apply_controller.on_apply_all(self)
        except Exception:
            log.exception("[ALL] on_apply_all failed")

    def _prepare_manual_apply(self, profile_ids) -> bool:
        """Give a manual action ownership of the visible hand before it starts.

        Auto Play may still have delayed callbacks for the same cards. Invalidate
        those callbacks as one session and suppress re-planning until a new hand
        arrives. A running drag is never interrupted because stopping it halfway
        would leave the game layout in an undefined state.
        """
        requested = {str(pid) for pid in (profile_ids or ()) if str(pid) in self.profiles}
        if not requested:
            return False

        running_requested = [
            str(pid)
            for pid, worker in (getattr(self, "_apply_threads", {}) or {}).items()
            if str(pid) in requested
            if worker is not None and getattr(worker, "is_alive", lambda: False)()
        ]
        if running_requested:
            self._auto_play_log(
                f"Bỏ thao tác tay vì đang xếp: {','.join(sorted(running_requested))}."
            )
            return False

        # Thao tác tay phải thu hồi ngay quyền click Xong/Báo binh đang chờ của
        # Auto trên đúng P được chọn. Không đụng token của các P khác.
        for pid in requested:
            try:
                self._confirmed_apply_tokens.pop(pid, None)
            except Exception:
                pass

        if self._auto_play_enabled or self._auto_play_reservations:
            self._auto_play_session += 1
            self._auto_play_hand_key = None
            self._auto_play_pending_key = None
            self._auto_reset_internal_cycle()
            for key, state in list(self._auto_play_reservations.items()):
                if state == "pending":
                    self._auto_play_reservations[key] = "cancelled"
            for pid in self.profiles:
                codes = list(self._codes_slot_order.get(pid) or [])
                if len(codes) == 13:
                    self._auto_play_applied_profile_keys.add(self._auto_profile_apply_key(pid))
            self._auto_play_log(
                f"Thao tác tay nhận quyền ván hiện tại: {','.join(sorted(requested))}."
            )
        return True

    def set_auto_play_log_sink(self, sink) -> None:
        self._auto_play_log_sink = sink

    def set_auto_settings_notifier(self, notifier) -> None:
        """Attach the cached Auto settings/notifier service owned by MainWindow."""
        self._auto_settings_notifier = notifier

    def _schedule_missing_3p_alert(self) -> None:
        """Debounce WS hand bursts before checking whether all 3P share one table."""
        notifier = getattr(self, "_auto_settings_notifier", None)
        if (
            not self._auto_play_enabled
            or notifier is None
            or not notifier.is_missing_3p_enabled()
        ):
            return
        self._missing_3p_alert_timer.stop()
        self._missing_3p_alert_timer.start()

    def _current_missing_3p_hand_key(self) -> Optional[str]:
        """Build an order-insensitive key so drag updates cannot duplicate alerts."""
        parts = []
        for pid in self.profiles:
            codes = list(self._codes_slot_order.get(pid) or [])
            if len(codes) == 13:
                parts.append(f"{pid}:{','.join(sorted(map(str, codes)))}")
        return "|".join(parts) or None

    def _check_missing_3p_alert(self) -> None:
        """Alert only when realtime roster proves that fewer than 3P share a table."""
        try:
            notifier = getattr(self, "_auto_settings_notifier", None)
            if (
                not self._auto_play_enabled
                or notifier is None
                or not notifier.is_missing_3p_enabled()
            ):
                return
            context = classify_auto_room_context(self._get_room_engine())
            controlled_count = len(context.controlled_pids)
            if controlled_count <= 0 or controlled_count >= len(self.profiles):
                return
            hand_key = self._current_missing_3p_hand_key()
            if hand_key:
                notifier.send_missing_3p(hand_key)
        except Exception:
            log.exception("[AUTO-PLAY] missing 3P alert check failed")

    def set_auto_play(self, enabled: bool, rounds: int = 0, delay_min_ms: int = 8000, delay_max_ms: int = 18000) -> None:
        self._auto_play_session += 1
        self._auto_play_enabled = bool(enabled)
        self._auto_play_remaining = -1 if enabled else 0
        a = max(0, int(delay_min_ms or 0))
        b = max(0, int(delay_max_ms or 0))
        self._auto_play_delay_min_ms = min(a, b)
        self._auto_play_delay_max_ms = max(a, b)
        self._auto_play_hand_key = None
        self._auto_play_pending_key = None
        self._auto_play_applied_profile_keys = set()
        self._auto_play_reservations = {}
        self._auto_apply_unsafe_retry_counts = {}
        self._auto_play_counted_round_keys = set()
        self._auto_reset_internal_cycle()
        if not self._auto_play_enabled:
            self._missing_3p_alert_timer.stop()
        state_text = "bật liên tục" if self._auto_play_enabled else "tắt"
        self._auto_play_log(
            f"Auto Play {state_text} | delay={self._auto_play_delay_min_ms}-{self._auto_play_delay_max_ms}ms"
        )
        self._sync_auto_play_sink_state()

    def get_auto_play_state(self) -> tuple[bool, int]:
        return bool(self._auto_play_enabled), int(self._auto_play_remaining)

    def _auto_play_log(self, text: str) -> None:
        log.info("[AUTO-PLAY] %s", text)
        sink = getattr(self, "_auto_play_log_sink", None)
        if sink is not None and hasattr(sink, "append_log"):
            try:
                sink.append_log(str(text))
            except Exception:
                pass

    def _sync_auto_play_sink_state(self) -> None:
        sink = getattr(self, "_auto_play_log_sink", None)
        if sink is not None and hasattr(sink, "set_auto_state"):
            try:
                sink.set_auto_state(bool(self._auto_play_enabled), int(self._auto_play_remaining))
            except Exception:
                pass

    def _current_auto_play_hand_key(self) -> Optional[str]:
        cards_ready = {
            pid
            for pid in self.profiles
            if len(list(self._codes_slot_order.get(pid) or [])) == 13
        }
        if len(cards_ready) == len(self.profiles):
            pending = [
                pid
                for pid in self.profiles
                if self._auto_profile_apply_key(pid) not in self._auto_play_applied_profile_keys
            ]
            if not pending:
                return None
            if any(not (self._suggestions.get(pid) or []) for pid in pending):
                return None

        parts = []
        ready_count = 0
        for pid in self.profiles:
            codes = list(self._codes_slot_order.get(pid) or [])
            pkey = self._auto_profile_apply_key(pid)
            if (
                len(codes) == 13
                and (self._suggestions.get(pid) or [])
                and pkey not in self._auto_play_applied_profile_keys
            ):
                ready_count += 1
                parts.append(pkey)
        if ready_count <= 0:
            return None
        return f"NGU:{self._ngu_key or '-'}|" + "|".join(parts)

    def _auto_profile_apply_key(self, pid: str) -> str:
        codes = list(self._codes_slot_order.get(pid) or [])
        generation = int((getattr(self, "_hand_generation", {}) or {}).get(pid, 0) or 0)
        return f"{pid}:g{generation}:{','.join(sorted(map(str, codes)))}"

    @staticmethod
    def _auto_room_context_key(context) -> str:
        """Stable roster signature used to reject delayed plans after a table move."""
        return "|".join(
            [
                str(getattr(context, "kind", "") or ""),
                ",".join(sorted(map(str, getattr(context, "controlled_pids", ()) or ()))),
                ",".join(sorted(map(str, getattr(context, "roster", ()) or ()))),
                ",".join(sorted(map(str, getattr(context, "external_uids", ()) or ()))),
            ]
        )

    def _auto_should_decrement_round(self) -> bool:
        cards_pids = [
            pid
            for pid in self.profiles
            if len(list(self._codes_slot_order.get(pid) or [])) == 13
        ]
        if not cards_pids:
            return True
        return all(
            self._auto_play_reservations.get(self._auto_profile_apply_key(pid)) == "done"
            for pid in cards_pids
        )

    def _auto_current_round_key(self) -> str:
        """Stable key for the currently visible hands, independent from slot order."""
        return "|".join(
            self._auto_profile_apply_key(pid)
            for pid in self.profiles
            if len(list(self._codes_slot_order.get(pid) or [])) == 13
        )

    def _auto_reset_internal_cycle(self) -> None:
        """Reset transient internal-balance cycle state."""
        self._auto_play_internal_streak = 0
        self._auto_play_internal_sap_ham_done = False
        self._auto_play_round_modes = {}

    def _auto_register_round_mode(self, mode: str) -> None:
        """Remember how a scheduled round must affect the internal cycle."""
        round_key = self._auto_current_round_key()
        if round_key:
            self._auto_play_round_modes.setdefault(round_key, str(mode or "other"))

    def _auto_commit_round_mode(self, round_key: str) -> None:
        """Update the cycle only after every visible profile finished applying."""
        mode = self._auto_play_round_modes.pop(round_key, "other")
        if mode == "internal_balance":
            limit = int(getattr(self, "_auto_play_internal_cycle_limit", 4) or 4)
            self._auto_play_internal_streak = min(limit, self._auto_play_internal_streak + 1)
            self._auto_play_log(
                f"Chu ky noi bo: {self._auto_play_internal_streak}/{limit} van lien tiep."
            )
            return
        if mode == "internal_sap_ham":
            limit = int(getattr(self, "_auto_play_internal_cycle_limit", 4) or 4)
            self._auto_play_internal_streak = limit
            self._auto_play_internal_sap_ham_done = True
            self._auto_play_log("Chu ky noi bo: da xep Sap Ham, van tiep theo dung Money rieng.")
            return
        if mode == "internal_cycle_money":
            limit = int(getattr(self, "_auto_play_internal_cycle_limit", 4) or 4)
            self._auto_play_internal_streak = 0
            self._auto_play_internal_sap_ham_done = False
            self._auto_play_log(f"Chu ky noi bo: da xep Money rieng, reset ve 0/{limit}.")
            return
        self._auto_play_internal_streak = 0
        self._auto_play_internal_sap_ham_done = False

    def _auto_finish_round_if_ready(self) -> None:
        """Finalize current Auto round only after every visible profile has finished apply."""
        if not self._auto_should_decrement_round():
            return
        round_key = self._auto_current_round_key()
        if not round_key or round_key in self._auto_play_counted_round_keys:
            return
        self._auto_play_counted_round_keys.add(round_key)
        self._auto_commit_round_mode(round_key)
        self._sync_auto_play_sink_state()

    def _auto_release_pending_group(self, expected_group_keys: Dict[str, str]) -> None:
        """Release only callbacks that have not started dragging, then allow re-plan."""
        has_started = any(
            self._auto_play_reservations.get(key) in ("applied", "done", "failed")
            for key in expected_group_keys.values()
        )
        for key in expected_group_keys.values():
            if self._auto_play_reservations.get(key) == "pending":
                if has_started:
                    self._auto_play_reservations[key] = "cancelled"
                else:
                    self._auto_play_reservations.pop(key, None)
                    self._auto_play_applied_profile_keys.discard(key)
        self._auto_play_hand_key = None
        self._auto_play_pending_key = None
        if not has_started and self._auto_play_enabled:
            session = self._auto_play_session
            QTimer.singleShot(0, lambda s=session: self._maybe_run_auto_play(s))

    def _auto_mark_profile_done(self, profile_key: str) -> None:
        if self._auto_play_reservations.get(profile_key) == "applied":
            self._auto_play_reservations[profile_key] = "done"
        try:
            self._auto_apply_unsafe_retry_counts.pop(profile_key, None)
        except Exception:
            pass
        self._auto_finish_round_if_ready()

    def _auto_mark_profile_unsafe(
        self,
        profile_key: str,
        expected_group_keys: Dict[str, str],
        reason: str = "unknown",
    ) -> None:
        """
        Apply của một P lỗi thật sự trước khi hoàn tất.

        Retry độc lập theo P; tuyệt đối không giải phóng/reset các P khác đang
        kéo hoặc đã hoàn tất trong cùng plan.
        """
        reason = str(reason or "unknown")
        # Các lỗi liên quan 606 xảy ra sau khi layout thật không được xác nhận.
        # Retry tự động có thể kéo chồng từ trạng thái sai, nên khóa riêng P cho
        # tới ván mới thay vì lập kế hoạch/kéo lại cùng ván.
        if reason.startswith("layout606_"):
            self._auto_play_reservations[profile_key] = "failed"
            self._auto_play_log(
                f"Dừng riêng {profile_key.split(':', 1)[0]} trong ván hiện tại: {reason}; không retry mù."
            )
            apply_trace("auto_retry_blocked_606", profile_key.split(":", 1)[0], reason=reason)
            return

        retry_counts = getattr(self, "_auto_apply_unsafe_retry_counts", None)
        if not isinstance(retry_counts, dict):
            retry_counts = {}
            self._auto_apply_unsafe_retry_counts = retry_counts
        retry_count = int(retry_counts.get(profile_key, 0) or 0) + 1
        retry_counts[profile_key] = retry_count

        if retry_count >= 2:
            self._auto_play_reservations[profile_key] = "failed"
            self._auto_play_log("Dừng retry P hiện tại vì DevTools/apply lỗi hai lần.")
            return

        self._auto_play_reservations.pop(profile_key, None)
        self._auto_play_applied_profile_keys.discard(profile_key)
        self._auto_play_hand_key = None
        self._auto_play_pending_key = None
        if self._auto_play_enabled:
            session = self._auto_play_session
            QTimer.singleShot(1000, lambda s=session: self._maybe_run_auto_play(s))

    def _auto_is_waiting_for_ngu_suggestions(self) -> bool:
        """Keep the full 3P path alive while the derived OPP job is still pending."""
        if not self._ngu_key or len(list(self._ngu_base_codes or [])) != 13:
            return False
        scheduler = getattr(self, "_scheduler", None)
        if scheduler is None:
            return False
        if bool(getattr(scheduler, "job_running", False)):
            return True
        return any(
            job and job[0] == "NGU"
            for job in list(getattr(scheduler, "job_q", ()) or ())
        )

    def _maybe_run_auto_play(self, expected_session: Optional[int] = None) -> None:
        if expected_session is not None and expected_session != self._auto_play_session:
            return
        if not self._auto_play_enabled:
            return

        hand_key = self._current_auto_play_hand_key()
        if not hand_key or hand_key == self._auto_play_hand_key:
            return
        if hand_key != getattr(self, "_auto_play_pending_key", None):
            self._auto_play_pending_key = hand_key
            dmin = max(0, int(getattr(self, "_auto_play_delay_min_ms", 0) or 0))
            dmax = max(dmin, int(getattr(self, "_auto_play_delay_max_ms", dmin) or dmin))
            delay_ms = random.randint(dmin, dmax) if dmax > dmin else dmin
            self._auto_play_log(f"Đủ bài/gợi ý, random delay {delay_ms}ms trước khi xếp.")
            session = self._auto_play_session
            QTimer.singleShot(delay_ms, lambda s=session: self._maybe_run_auto_play(s))
            return
        try:
            has_auto_opp = any(s.get("_auto_opp_money") for s in self._ngu_suggestions)
            room_context = classify_auto_room_context(self._get_room_engine())
            allow_opp_plan = room_context.kind == "external_opp"
            allow_intentional_foul = (
                allow_opp_plan
                and len(room_context.external_uids) == 1
                and bool(
                    self._auto_settings_notifier is not None
                    and self._auto_settings_notifier.is_intentional_foul_enabled()
                )
            )
            is_internal = room_context.kind in ("internal_3p", "internal_2p")
            self._auto_play_log(
                f"[ROOM] kind={room_context.kind} controlled={list(room_context.controlled_pids)}"
                f" external={list(room_context.external_uids)}"
                f" gold={dict(room_context.gold_by_pid)}"
                + (f" reason={room_context.reason}" if room_context.reason else "")
            )

            if allow_opp_plan and not has_auto_opp and self._auto_is_waiting_for_ngu_suggestions():
                self._auto_play_log("Đang chờ gợi ý Money của OPP để xếp combo 3P.")
                session = self._auto_play_session
                QTimer.singleShot(250, lambda s=session: self._maybe_run_auto_play(s))
                return

            # ── Chọn plan theo bối cảnh bàn ──────────────────────────────
            internal_cycle_limit = int(getattr(self, "_auto_play_internal_cycle_limit", 4) or 4)
            sap_ham_due = bool(
                is_internal
                and self._auto_play_internal_streak >= internal_cycle_limit
                and not bool(getattr(self, "_auto_play_internal_sap_ham_done", False))
            )
            internal_cycle_money = bool(
                is_internal
                and self._auto_play_internal_streak >= internal_cycle_limit
                and bool(getattr(self, "_auto_play_internal_sap_ham_done", False))
            )
            if allow_opp_plan and has_auto_opp:
                plan = build_auto_play_plan(
                    self,
                    max_opp=3,
                    allow_intentional_foul=allow_intentional_foul,
                )
            elif is_internal:
                if internal_cycle_money:
                    plan = build_money_fallback_plan(self)
                elif sap_ham_due:
                    plan = build_internal_sap_ham_plan(self, room_context)
                    if plan is None:
                        self._auto_play_log("Chu ky noi bo: chua tim duoc Sap Ham an toan, dung noi bo khong sap.")
                        plan = build_internal_balance_plan(self, room_context)
                else:
                    plan = build_internal_balance_plan(self, room_context)
                if plan is None:
                    # Fallback: gold bằng nhau / thiếu data → Money độc lập
                    plan = build_money_fallback_plan(self)
            else:
                plan = build_money_fallback_plan(self)

            if plan is None:
                if allow_opp_plan and not has_auto_opp:
                    self._auto_play_log("Bỏ qua: đang chờ gợi ý Money cho P sẵn sàng.")
                    return
                self._auto_play_log("Bỏ qua: chưa có P nào đủ bài/gợi ý hợp lệ để Auto Play.")
                return

            separate_plan = None
            if room_context.kind == "internal_2p" and plan.kind in ("internal_balance", "internal_sap_ham"):
                pair_pids = set(room_context.controlled_pids)
                separate_plan = build_money_fallback_plan(
                    self,
                    profile_ids=[pid for pid in self.profiles if pid not in pair_pids],
                )

            # Loại bỏ các pid đã apply trong ván này
            plan.suggestions = {
                pid: dict(sug)
                for pid, sug in (plan.suggestions or {}).items()
                if self._auto_profile_apply_key(pid) not in self._auto_play_applied_profile_keys
            }
            plan.selected_index = {
                pid: int(idx)
                for pid, idx in (plan.selected_index or {}).items()
                if pid in plan.suggestions
            }
            plan.report_binh_pids = tuple(
                pid for pid in (plan.report_binh_pids or ()) if pid in plan.suggestions
            )
            if not plan.suggestions:
                if separate_plan is not None:
                    separate_pids = list((separate_plan.suggestions or {}).keys())
                    self._auto_play_hand_key = hand_key
                    self._auto_register_round_mode("internal_balance")
                    self._auto_play_log(f"Money ban rieng: {','.join(separate_pids)}")
                    self._auto_apply_suggestions_random(
                        separate_plan.suggestions,
                        report_binh_pids=set(separate_plan.report_binh_pids or ()),
                        dependency_groups=separate_plan.dependency_groups,
                    )
                return

            self._auto_play_hand_key = hand_key
            if plan.kind == "internal_balance":
                self._auto_register_round_mode("internal_balance")
            elif plan.kind == "internal_sap_ham":
                self._auto_register_round_mode("internal_sap_ham")
                self._auto_play_log(
                    f"Chu ky noi bo: van thu {internal_cycle_limit + 1} dung Sap Ham noi bo."
                )
            elif internal_cycle_money:
                self._auto_register_round_mode("internal_cycle_money")
                self._auto_play_log(
                    f"Chu ky noi bo: van thu {internal_cycle_limit + 2} dung Money rieng cho tung P."
                )
            else:
                self._auto_register_round_mode("other")

            # OPP selection chỉ cập nhật khi có external OPP
            if plan.kind not in ("money_fallback", "internal_balance", "internal_sap_ham"):
                self._ngu_clicked_once = True
                self._ngu_selected_index = int(plan.opp_index)

            # ── Apply theo từng loại plan ─────────────────────────────────
            if plan.kind == "sap_lang" and plan.combo is not None:
                self._auto_play_log(
                    f"Chọn OPP #{plan.opp_index + 1} | dùng Bẻ Sập Làng | score={plan.score}"
                )
                self._auto_apply_suggestions_random(
                    plan.suggestions,
                    dependency_groups=plan.dependency_groups,
                    expected_room_context_key=self._auto_room_context_key(room_context),
                )

            elif plan.kind == "intentional_foul":
                self._auto_play_log("OPP ăn sập làng không thể chạy | dùng Binh Lủng 3P.")
                self._auto_apply_intentional_foul_random(
                    plan.suggestions,
                    hand_key,
                    expected_room_context_key=self._auto_room_context_key(room_context),
                )

            elif plan.kind == "internal_balance":
                ready_pids = list((plan.suggestions or {}).keys())
                binh_text = f" | báo binh {','.join(plan.report_binh_pids)}" if plan.report_binh_pids else ""
                gold_map = room_context.gold_by_pid
                gold_info = " | vàng " + " > ".join(
                    f"{p}={gold_map.get(p)}"
                    for p in sorted(ready_pids, key=lambda x: (gold_map.get(x) or 0))
                )
                self._auto_play_log(
                    f"Tối ưu nội bộ {room_context.kind}: {','.join(ready_pids)}{gold_info}{binh_text}"
                )
                self._auto_apply_suggestions_random(
                    plan.suggestions,
                    report_binh_pids=set(plan.report_binh_pids or ()),
                    dependency_groups=plan.dependency_groups,
                    expected_room_context_key=self._auto_room_context_key(room_context),
                )
                if room_context.kind == "internal_2p":
                    if separate_plan is not None:
                        separate_pids = list((separate_plan.suggestions or {}).keys())
                        self._auto_play_log(f"Money ban rieng: {','.join(separate_pids)}")
                        self._auto_apply_suggestions_random(
                            separate_plan.suggestions,
                            report_binh_pids=set(separate_plan.report_binh_pids or ()),
                            dependency_groups=separate_plan.dependency_groups,
                        )

            elif plan.kind == "internal_sap_ham":
                ready_pids = list((plan.suggestions or {}).keys())
                gold_map = room_context.gold_by_pid
                sorted_ready = sorted(ready_pids, key=lambda x: (gold_map.get(x) or 0))
                sap_text = (
                    f" | {sorted_ready[-1]} thua Sap Ham {sorted_ready[0]}"
                    if len(sorted_ready) >= 2
                    else ""
                )
                self._auto_play_log(
                    f"Toi uu Sap Ham noi bo {room_context.kind}: {','.join(ready_pids)}{sap_text}"
                )
                self._auto_apply_suggestions_random(
                    plan.suggestions,
                    report_binh_pids=set(plan.report_binh_pids or ()),
                    dependency_groups=plan.dependency_groups,
                    expected_room_context_key=self._auto_room_context_key(room_context),
                )
                if room_context.kind == "internal_2p" and separate_plan is not None:
                    separate_pids = list((separate_plan.suggestions or {}).keys())
                    self._auto_play_log(f"Money ban rieng: {','.join(separate_pids)}")
                    self._auto_apply_suggestions_random(
                        separate_plan.suggestions,
                        report_binh_pids=set(separate_plan.report_binh_pids or ()),
                        dependency_groups=separate_plan.dependency_groups,
                    )

            elif plan.kind == "money_fallback":
                ready_pids = list((plan.suggestions or {}).keys())
                binh_text = f" | báo binh {','.join(plan.report_binh_pids)}" if plan.report_binh_pids else ""
                if room_context.kind in ("internal_3p", "internal_2p"):
                    fallback_reason = f"gold bằng nhau / thiếu data ({room_context.kind})"
                else:
                    fallback_reason = room_context.reason or "chưa đủ combo 3P"
                self._auto_play_log(
                    f"Fallback Money độc lập: {','.join(ready_pids)} vì {fallback_reason}{binh_text}"
                )
                self._auto_apply_suggestions_random(
                    plan.suggestions,
                    report_binh_pids=set(plan.report_binh_pids or ()),
                    dependency_groups=plan.dependency_groups,
                )

            else:
                # External OPP: normal / partial
                ready_pids = list((plan.suggestions or {}).keys())
                binh_text = f" | báo binh {','.join(plan.report_binh_pids)}" if plan.report_binh_pids else ""
                self._auto_play_log(
                    f"Chọn OPP #{plan.opp_index + 1} | {'xếp riêng ' + ','.join(ready_pids) if plan.partial else 'xếp tối ưu'}{binh_text} | score={plan.score}"
                )
                opp = self._ngu_suggestions[plan.opp_index]
                for pid in ready_pids:
                    rendered = list(self._build_render_suggestions(list(self._suggestions.get(pid) or []), opp) or [])
                    self._suggestions_render[pid] = rendered[:self.MAX_UI_P_ITEMS]
                    self._selected_index[pid] = int(plan.selected_index.get(pid, 0))
                self._render_ngu()
                self._render_p_active()
                self._auto_apply_suggestions_random(
                    plan.suggestions,
                    report_binh_pids=set(plan.report_binh_pids or ()),
                    dependency_groups=plan.dependency_groups,
                    expected_room_context_key=self._auto_room_context_key(room_context),
                )

            self._sync_auto_play_sink_state()
        except Exception as e:
            self._auto_play_log(f"Lỗi Auto Play: {e}")
            log.exception("[AUTO-PLAY] failed")

    def _auto_random_delay_ms(self) -> int:
        dmin = max(0, int(getattr(self, "_auto_play_delay_min_ms", 0) or 0))
        dmax = max(dmin, int(getattr(self, "_auto_play_delay_max_ms", dmin) or dmin))
        return random.randint(dmin, dmax) if dmax > dmin else dmin

    def _auto_schedule_click_binh(
        self,
        pid: str,
        expected_profile_key: Optional[str] = None,
        expected_auto_session: Optional[int] = None,
    ) -> None:
        """Wait for the game to show Báo binh after special layout, then click it."""
        self._auto_play_log(f"{pid}: đã xếp hình binh, chờ 2000ms để click Báo binh.")
        confirmed_token = (getattr(self, "_confirmed_apply_tokens", {}) or {}).get(pid)

        def _click() -> None:
            try:
                current_token = (getattr(self, "_confirmed_apply_tokens", {}) or {}).get(pid)
                if not confirmed_token or current_token != confirmed_token:
                    apply_trace(
                        "click_binh_blocked_unconfirmed",
                        pid,
                        expected_tx=confirmed_token,
                        current_tx=current_token,
                    )
                    self._auto_play_log(f"{pid}: chặn click Báo binh vì giao dịch xếp không còn được xác nhận.")
                    return
                # Khi apply đã hoàn tất thì phải chốt thao tác của chính P đó.
                # Không hủy giữa chừng vì session/roster/WS thay đổi sau khi kéo.
                controller = self._get_game_controller()
                if controller is None or not hasattr(controller, "click_binh"):
                    raise RuntimeError("game_controller chưa hỗ trợ click_binh")
                controller.click_binh(pid)
                apply_trace("click_binh_sent", pid, tx=confirmed_token)
                self._auto_play_log(f"{pid}: đã click Báo binh.")
            except Exception as e:
                self._auto_play_log(f"{pid}: lỗi click Báo binh: {e}")
                log.exception("[AUTO-PLAY] click Binh failed pid=%s", pid)

        apply_trace("schedule_click_binh", pid, session=expected_auto_session, tx=confirmed_token)
        QTimer.singleShot(2000, _click)

    def _auto_schedule_click_done(
        self,
        pid: str,
        expected_profile_key: Optional[str] = None,
        expected_auto_session: Optional[int] = None,
    ) -> None:
        """Wait for the game to enable Xong after a normal layout, then click it."""
        self._auto_play_log(f"{pid}: đã xếp bài, chờ 1000ms để click Xong.")
        confirmed_token = (getattr(self, "_confirmed_apply_tokens", {}) or {}).get(pid)

        def _click() -> None:
            try:
                current_token = (getattr(self, "_confirmed_apply_tokens", {}) or {}).get(pid)
                if not confirmed_token or current_token != confirmed_token:
                    apply_trace(
                        "click_done_blocked_unconfirmed",
                        pid,
                        expected_tx=confirmed_token,
                        current_tx=current_token,
                    )
                    self._auto_play_log(f"{pid}: chặn click Xong vì giao dịch xếp không còn được xác nhận.")
                    return
                # Apply đã thành công thì luôn click Xong; không để thay đổi
                # trạng thái của P khác hoặc một WS đến muộn làm bỏ hoàn tất.
                controller = self._get_game_controller()
                if controller is None or not hasattr(controller, "click_done"):
                    raise RuntimeError("game_controller chưa hỗ trợ click_done")
                controller.click_done(pid)
                apply_trace("click_done_sent", pid, tx=confirmed_token)
                self._auto_play_log(f"{pid}: đã click Xong.")
            except Exception as e:
                self._auto_play_log(f"{pid}: lỗi click Xong: {e}")
                log.exception("[AUTO-PLAY] click Done failed pid=%s", pid)

        apply_trace("schedule_click_done", pid, session=expected_auto_session, tx=confirmed_token)
        QTimer.singleShot(1000, _click)

    def _auto_apply_suggestions_random(
        self,
        suggestions_by_pid: Dict[str, dict],
        report_binh_pids=None,
        no_complete_pids=None,
        expected_profile_keys=None,
        on_apply_started=None,
        expected_auto_session=None,
        dependency_groups=None,
        expected_room_context_key=None,
    ) -> None:
        """Apply Auto Play profile-by-profile with an independent random delay per P."""
        from ui2.tabs.strategy2.modules.apply_auto import apply_suggestion_dashboard_style

        report_binh_pids = set(report_binh_pids or ())
        no_complete_pids = set(no_complete_pids or ())
        expected_profile_keys = dict(expected_profile_keys or {})
        groups = [tuple(group) for group in (dependency_groups or ()) if group]
        if not groups:
            groups = [(pid,) for pid in self.profiles if (suggestions_by_pid or {}).get(pid)]
        group_keys_by_pid: Dict[str, Dict[str, str]] = {}
        for group in groups:
            keys = {pid: self._auto_profile_apply_key(pid) for pid in group}
            for pid in group:
                group_keys_by_pid[pid] = keys
        if expected_profile_keys:
            for pid in expected_profile_keys:
                group_keys_by_pid[pid] = dict(expected_profile_keys)
        if expected_auto_session is None:
            expected_auto_session = self._auto_play_session

        for pid in self.profiles:
            sug = dict((suggestions_by_pid or {}).get(pid) or {})
            ws_codes = list(self._codes_slot_order.get(pid) or [])
            if len(ws_codes) != 13 or not sug:
                continue

            delay_ms = self._auto_random_delay_ms()
            self._auto_play_log(f"{pid}: chờ random {delay_ms}ms rồi xếp.")
            profile_key = self._auto_profile_apply_key(pid)
            self._auto_play_applied_profile_keys.add(profile_key)
            self._auto_play_reservations[profile_key] = "pending"

            def _apply_one(
                profile_id=pid,
                cards=list(ws_codes),
                suggestion=dict(sug),
                expected_key=profile_key,
                expected_group_keys=dict(group_keys_by_pid.get(pid) or {pid: profile_key}),
                auto_session=expected_auto_session,
                room_context_key=expected_room_context_key,
            ) -> None:
                try:
                    if auto_session != self._auto_play_session:
                        self._auto_play_log(f"{profile_id}: bỏ xếp vì phiên Auto đã đổi.")
                        return
                    self._auto_play_reservations[expected_key] = "applied"
                    if callable(on_apply_started):
                        on_apply_started(profile_id)
                    spawned = apply_suggestion_dashboard_style(
                        tab=self,
                        profile_id=profile_id,
                        ws_codes=list(cards),
                        suggestion=dict(suggestion),
                        on_complete=None if profile_id in no_complete_pids else (
                            (
                                lambda p=profile_id, key=expected_key, session=auto_session:
                                self._auto_schedule_click_binh(p, key, session)
                            )
                            if profile_id in report_binh_pids
                            else (
                                lambda p=profile_id, key=expected_key, session=auto_session:
                                self._auto_schedule_click_done(p, key, session)
                            )
                        ),
                        on_finished=lambda key=expected_key: self._auto_mark_profile_done(key),
                        on_unsafe=(
                            lambda reason="unknown", key=expected_key, keys=dict(expected_group_keys):
                            self._auto_mark_profile_unsafe(key, keys, reason)
                        ),
                    )
                    if not spawned:
                        # on_unsafe có thể đã khóa P vì pipeline 606 chưa sẵn sàng.
                        # Không được ghi đè failed rồi re-plan liên tục.
                        if self._auto_play_reservations.get(expected_key) != "failed":
                            self._auto_play_reservations[expected_key] = "pending"
                            self._auto_release_pending_group(expected_group_keys)
                except Exception as e:
                    self._auto_play_reservations[expected_key] = "failed"
                    self._auto_play_log(f"{profile_id}: lỗi xếp auto: {e}")
                    log.exception("[AUTO-PLAY] apply profile failed pid=%s", profile_id)

            QTimer.singleShot(delay_ms, _apply_one)

    def _auto_apply_intentional_foul_random(
        self,
        suggestions_by_pid: Dict[str, dict],
        hand_key: str,
        expected_room_context_key=None,
    ) -> None:
        """Apply intentional foul layouts without clicking Xong or Báo binh."""
        expected = {pid: self._auto_profile_apply_key(pid) for pid in self.profiles}
        notifier = getattr(self, "_auto_settings_notifier", None)

        def _notify_once(_pid: str) -> None:
            try:
                if notifier is not None:
                    notifier.send_bi_sap_lang(hand_key)
            except Exception:
                log.exception("[AUTO-PLAY] send bị sập làng Telegram failed")

        self._auto_apply_suggestions_random(
            suggestions_by_pid,
            no_complete_pids=set(self.profiles),
            expected_profile_keys=expected,
            on_apply_started=_notify_once,
            dependency_groups=(tuple(self.profiles),),
            expected_room_context_key=expected_room_context_key,
        )

    def _get_selected_opp_suggestion(self) -> Optional[dict]:
        lst = list(self._ngu_suggestions or [])
        if not lst:
            return None
        idx = int(self._ngu_selected_index or 0)
        if idx < 0 or idx >= len(lst):
            idx = 0
        if self._is_special_row(lst[idx]) and len(lst) > 1:
            idx = 1
        return lst[idx]

    def _refresh_sap_lang_combo(self) -> None:
        """Detect a global 3P sap-lang combo and show/hide its action button."""
        try:
            opp = self._get_selected_opp_suggestion()
            combo = find_sap_lang_combo(
                suggestions_by_pid={
                    pid: list(self._suggestions_render.get(pid) or []) + list(self._suggestions.get(pid) or [])
                    for pid in self.profiles
                },
                ws_codes_by_pid={pid: list(self._codes_slot_order.get(pid) or []) for pid in self.profiles},
                opp_suggestion=opp,
            )
            self._sap_lang_combo = combo
            if hasattr(self.view, "set_break_sap_lang_available"):
                self.view.set_break_sap_lang_available(combo is not None, combo.leader if combo else "")
        except Exception as e:
            self._sap_lang_combo = None
            try:
                self.view.set_break_sap_lang_available(False)
            except Exception:
                pass
            log.exception("[Strategy2] refresh sap-lang combo failed: %s", e)

    def _on_break_sap_lang(self) -> None:
        """Apply the detected sap-lang combo for all 3 profiles."""
        combo = getattr(self, "_sap_lang_combo", None)
        if combo is None:
            return
        try:
            self._apply_controller.on_apply_combo(self, combo.suggestions)
        except Exception:
            log.exception("[BẺ SẬP] apply combo failed")

    # ===== Legacy UI contract (used by strategy_suggest.py) =====
    def _sync_apply_button_enabled(self) -> None:
        """Keep the shared Apply button locked only for the active profile."""
        try:
            if not hasattr(self.view, "btn_hup") or self.view.btn_hup is None:
                return

            active = str(getattr(self, "active_profile", "") or "")
            busy = bool((getattr(self, "_apply_busy", {}) or {}).get(active, False))
            if busy:
                self.view.btn_hup.setEnabled(False)
                return

            suggs = self._suggestions_render.get(active) or self._suggestions.get(active) or []
            idx = int(self._selected_index.get(active, 0))
            has_split = False
            if suggs and 0 <= idx < len(suggs):
                s = suggs[idx] or {}
                has_split = (
                    len(list(s.get("chi1_codes") or [])) == 5
                    and len(list(s.get("chi2_codes") or [])) == 5
                    and len(list(s.get("chi3_codes") or [])) == 3
                )
            self.view.btn_hup.setEnabled(bool(has_split))
        except Exception:
            log.exception("[Strategy2] _sync_apply_button_enabled failed")

    def _apply_btn_set_busy(self, profile_id: str) -> None:
        """Backward-compat UI hook: mark Apply as busy for a given profile.

        Strategy2 moved apply logic into ApplyController, but some legacy helpers
        (strategy_suggest.py) still call these methods. Keep them lightweight and safe:
        - do NOT touch core logic
        - only adjust UI enable/disable state
        """
        log.warning("[APPLY BUSY] pid=%s", profile_id)
        try:
            # Track busy per profile (optional).
            if not hasattr(self, "_apply_busy"):
                self._apply_busy = {pid: False for pid in (self.profiles + ["NGU"])}
            self._apply_busy[str(profile_id)] = True

            # Single Apply button (HÚP) in current StrategyView
            self._sync_apply_button_enabled()

            # If view exposes a per-profile API, call it.
            if hasattr(self.view, "set_apply_button_busy"):
                self.view.set_apply_button_busy(str(profile_id))
        except Exception:
            log.exception("[Strategy2] _apply_btn_set_busy failed pid=%s", profile_id)

    def _apply_btn_set_default(self, profile_id: str) -> None:
        """Backward-compat UI hook: restore Apply button to default state."""
        log.warning("[APPLY DEFAULT] pid=%s", profile_id)

        try:
            if not hasattr(self, "_apply_busy"):
                self._apply_busy = {pid: False for pid in (self.profiles + ["NGU"])}
            self._apply_busy[str(profile_id)] = False

            self._sync_apply_button_enabled()

            if hasattr(self.view, "set_apply_button_default"):
                self.view.set_apply_button_default(str(profile_id))
        except Exception:
            log.exception("[Strategy2] _apply_btn_set_default failed pid=%s", profile_id)
            
        # Apply pending WS reset (if any) right after apply finishes
        try:
            self._apply_pending_ws_reset_if_any(str(profile_id))
        except Exception:
            pass
        # Apply pending WS same-hand (if any) right after apply finishes
        try:
            self._apply_pending_ws_samehand_if_any(str(profile_id))
        except Exception:
            pass

    def _on_profile_switch(self, pid: str) -> None:
        if pid not in self.profiles:
            return
        self.active_profile = pid
        self._render_p_active()
        self._render_ngu()

    def _on_p_label_clicked(self, idx: int) -> None:
        pid = self.active_profile  # MUST be first

        # (log tùy chọn) - dùng pid sau khi đã gán
        try:
            log.warning(
                "[P CLICK] pid=%s idx=%s first3_layout=%s",
                pid,
                idx,
                (self._layout_codes.get(pid) or [])[:3],
            )
        except Exception:
            pass

        ridx = int(idx)

        lst = self._suggestions_render.get(pid) or []
        # NOTE: Cho phép chọn special row ở index 0 để APPLY bài đặc biệt.
        # (NGU vẫn giữ rule skip special ở _on_ngu_label_clicked)

        self._selected_index[pid] = ridx
        self._render_p_active()

        if self._ngu_suggestions:
            self._rebuild_ngu_labels_html()
            self.view.set_ngu_labels(self._ngu_suggestions, self._ngu_selected_index)

    def _on_ngu_label_clicked(self, idx: int) -> None:
        ridx = int(idx)

        if (
            self._ngu_suggestions
            and ridx == 0
            and self._is_special_row(self._ngu_suggestions[0])
            and len(self._ngu_suggestions) > 1
        ):
            ridx = 1

        # Đánh dấu: từ giờ trở đi đã có 1 OPP được chọn -> bật sort theo chi thắng
        self._ngu_clicked_once = True

        self._ngu_selected_index = ridx
        self._render_ngu()
        self._render_p_active()

        if self._ngu_suggestions:
            self._rebuild_ngu_labels_html()
            self.view.set_ngu_labels(self._ngu_suggestions, self._ngu_selected_index)
    # =================== Manual retry P suggestions ===================
    def _on_p_retry_clicked(self) -> None:
        """Callback khi user click nút reset gợi ý P ACTIVE."""
        pid = str(self.active_profile)
        try:
            self._retry_suggestions_for_pid(pid)
        except Exception:
            log.exception("[Strategy2] _on_p_retry_clicked failed pid=%s", pid)

    def _retry_suggestions_for_pid(self, pid: str) -> None:
        """Force chạy lại pipeline gợi ý cho 1 profile dựa trên 13 lá hiện có.

        Ý tưởng:
        - Chỉ chạy khi profile đó đã có đủ 13 lá trong _codes_slot_order.
        - Dùng lại toàn bộ flow Hướng A:
          + _force_reset_pid_state(pid) để xóa state cũ + clear cache worker.
          + Gán lại _codes_slot_order/_layout_codes bằng 13 lá hiện tại.
          + Nếu pid đang active: render lại bài, set status "Đang tính lại gợi ý…",
            ẩn nút reset trong lúc đang chạy.
          + Kick _batch_debounce để StagedScheduler enqueue job như WS-hand mới.
        """
        pid = str(pid)
        if pid not in self.profiles:
            return

        codes = list(self._codes_slot_order.get(pid) or [])
        # Không đủ 13 lá thì không retry được
        if len(codes) != 13:
            return

        # Reset toàn bộ state logic cho pid giống như khi WS báo ván mới
        try:
            self._force_reset_pid_state(pid)
        except Exception:
            log.exception("[Strategy2] _retry_suggestions_for_pid: _force_reset_pid_state failed pid=%s", pid)

        # Nếu anh muốn chắc chắn scheduler coi đây là batch mới hoàn toàn:
        try:
            if hasattr(self, "_scheduled_hash") and isinstance(self._scheduled_hash, dict):
                self._scheduled_hash[pid] = None
        except Exception:
            pass

        # Gán lại 13 lá cho slot-order + layout
        self._codes_slot_order[pid] = list(codes)
        self._layout_codes[pid] = list(codes)

        # Nếu đây là profile đang ACTIVE -> đồng bộ UI ngay
        if pid == self.active_profile:
            try:
                self.view.set_cards_p_normalized(list(codes))
                self.view.set_p_status("Đang tính lại gợi ý…")
                if hasattr(self.view, "set_p_retry_visible"):
                    # ẩn icon trong lúc đang chạy để tránh spam
                    self.view.set_p_retry_visible(False)
            except Exception:
                pass

        # Kick debounce để staged scheduler chạy lại job suggest cho pid này
        try:
            self._batch_debounce.stop()
            self._batch_debounce.start()
        except Exception:
            log.exception("[Strategy2] _retry_suggestions_for_pid: debounce failed pid=%s", pid)

    # ===== used by apply_suggestion_dashboard_style =====
    def refresh_slot_order_by_scan(self, profile_id: str) -> None:
        return self._apply_controller.refresh_slot_order_by_scan(self, profile_id)
     
    def _has_playable_split(self, sug: dict) -> bool:
        if not sug:
            return False
        return (
            len(list(sug.get("chi1_codes") or [])) == 5
            and len(list(sug.get("chi2_codes") or [])) == 5
            and len(list(sug.get("chi3_codes") or [])) == 3
        )

    def _pick_current_suggestion_for_pid(self, pid: str):
        # Dùng đúng gợi ý đang được chọn trên UI, fallback sang dòng chơi được đầu tiên.
        render_list = list(self._suggestions_render.get(pid) or [])
        base_list = list(self._suggestions.get(pid) or [])
        candidates = render_list or base_list

        if candidates:
            try:
                idx = int(self._selected_index.get(pid, 0) or 0)
            except Exception:
                idx = 0
            if 0 <= idx < len(candidates):
                selected = candidates[idx]
                if self._has_playable_split(selected) and not self._is_special_row(selected):
                    return selected

        for item in render_list:
            if self._has_playable_split(item) and not self._is_special_row(item):
                return item
        for item in base_list:
            if self._has_playable_split(item) and not self._is_special_row(item):
                return item
        return None

    def _pick_current_ngu_suggestion(self):
        if not self._ngu_suggestions:
            return None
        try:
            idx = int(self._ngu_selected_index or 0)
        except Exception:
            idx = 0
        if 0 <= idx < len(self._ngu_suggestions):
            selected = self._ngu_suggestions[idx]
            if self._has_playable_split(selected) and not self._is_special_row(selected):
                return selected
        for item in self._ngu_suggestions:
            if self._has_playable_split(item) and not self._is_special_row(item):
                return item
        return None

    def _compute_sap_lang_flags_for_active_suggestion(self, pid: str, sug: dict):
        # trả (lang_win, lang_lose)
        # yêu cầu đủ 3 đối thủ: NGU + 2 profile còn lại (vì tool anh là 3P + NGU)
        opp_list = []

        # NGU: dùng selection hiện tại (skip special)
        opp = self._pick_current_ngu_suggestion()
        if opp:
            opp_list.append(opp)

        # 2 profile còn lại
        for other in self.profiles:
            if other == pid:
                continue
            s2 = self._pick_current_suggestion_for_pid(other)
            if s2 and (not self._is_special_row(s2)):
                opp_list.append(s2)

        # cần đủ 3 đối thủ để kết luận “làng”
        if len(opp_list) < 3:
            return (False, False)

        def sweep_vs(opp_sug: dict) -> int:
            # return +1 nếu sug sweep opp, -1 nếu bị sweep, 0 otherwise (hoà => 0)
            d1 = self._labeling.compare_chi(list(sug.get("chi1_codes") or []), list(opp_sug.get("chi1_codes") or []), 1)
            d2 = self._labeling.compare_chi(list(sug.get("chi2_codes") or []), list(opp_sug.get("chi2_codes") or []), 2)
            d3 = self._labeling.compare_chi(list(sug.get("chi3_codes") or []), list(opp_sug.get("chi3_codes") or []), 3)

            # Rule: có hoà => không sập
            if d1 == 0 or d2 == 0 or d3 == 0:
                return 0
            if d1 > 0 and d2 > 0 and d3 > 0:
                return 1
            if d1 < 0 and d2 < 0 and d3 < 0:
                return -1
            return 0

        wins_all = True
        lose_all = True
        for opp_sug in opp_list:
            r = sweep_vs(opp_sug)
            if r != 1:
                wins_all = False
            if r != -1:
                lose_all = False

        return (wins_all, lose_all)
