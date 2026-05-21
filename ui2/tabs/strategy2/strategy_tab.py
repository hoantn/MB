from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import hashlib
import threading
import queue
import re

from PySide6.QtCore import QTimer, QThread, Signal, Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout

from .modules.ngu_derive import NGUDeriver
from .modules.suggest_pipeline import SuggestPipeline

# UI perf guards
MAX_UI_P_ITEMS = 12
MAX_UI_NGU_ITEMS = 12

from core.logger import log
from ui2.bridge.ws_card_store import ws_card_store
from ui2.tabs.dashboard.dashboard_constants import FULL_DECK

from .strategy_view import StrategyView
from .strategy_suggest_worker import build_suggestions_for_codes
from .strategy_suggest import pick_default_suggestion
from .strategy_anti_sap import build_anti_sap_suggestions
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

    def __init__(self, browser_manager, parent=None):
        super().__init__(parent)

        # Ensure ui_call is connected on the owning (UI) thread.
        try:
            self.ui_call.connect(self._on_ui_call)
        except Exception:
            pass
            
        self.browser_manager = browser_manager

        self.capture_manager = (
            getattr(parent, "capture_manager", None)
            or getattr(browser_manager, "capture_manager", None)
            or getattr(browser_manager, "capture", None)
        )

        self.MAX_UI_P_ITEMS = MAX_UI_P_ITEMS
        self.MAX_UI_NGU_ITEMS = MAX_UI_NGU_ITEMS

        self.profiles = ["P1", "P2", "P3"]
        self._ngu_deriver = NGUDeriver(self.profiles)
        self._pipeline = SuggestPipeline(self.profiles, FULL_DECK)
        self.active_profile = "P1"

        lay = QVBoxLayout(self)
        self.view = StrategyView(self.profiles, self)
        lay.addWidget(self.view)

        # UI events
        self.view.profile_changed.connect(self._on_profile_switch)
        self.view.p_label_clicked.connect(self._on_p_label_clicked)
        self.view.ngu_label_clicked.connect(self._on_ngu_label_clicked)
        self.view.btn_hup.clicked.connect(lambda: self._on_apply(self.active_profile))
        self.view.apply_all_clicked.connect(self._on_apply_all)
        
        # retry gợi ý P ACTIVE khi không có gợi ý
        if hasattr(self.view, "p_retry_clicked"):
            self.view.p_retry_clicked.connect(self._on_p_retry_clicked)

        # WS -> slot order codes (reverse y hệt dashboard)
        self._codes_slot_order: Dict[str, List[str]] = {pid: [] for pid in self.profiles}
        self._ws_snapshot: Dict[str, Optional[List[str]]] = {pid: None for pid in self.profiles}
        self._last_hand_hash: Dict[str, Optional[str]] = {pid: None for pid in self.profiles}

        self._layout_codes: Dict[str, List[str]] = {}

        self._suggestions: Dict[str, List[dict]] = {pid: [] for pid in self.profiles}
        self._suggestions_render: Dict[str, List[dict]] = {pid: [] for pid in self.profiles}
        self._selected_index: Dict[str, int] = {pid: 0 for pid in self.profiles}

        self._ngu_base_codes: List[str] = []
        self._ngu_suggestions: List[dict] = []
        self._ngu_selected_index: int = 0
        self._ngu_key: Optional[str] = None
        # Đánh dấu đã từng click chọn 1 gợi ý OPP/NGU hay chưa
        self._ngu_clicked_once: bool = False

        # Anti-sập (vs NGU) is expensive. Default OFF to avoid lag/spam labels.
        self._anti_sap_enabled: bool = False

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

    @property
    def log(self):
        return log

    @property
    def build_anti_sap_suggestions(self):
        return build_anti_sap_suggestions

    # =================== helpers ===================
    def _hand_hash(self, codes: List[str]) -> str:
        """Order-sensitive hand hash (matches legacy strategy_tab - Copy.py).

        This hash is used ONLY for WS dedup/new-hand detection and must remain stable across refactors.
        """
        m = hashlib.md5()
        for c in codes:
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

        # 2) last_hand_hash không còn ý nghĩa theo Hướng A (vẫn có thể giữ để debug)
        self._last_hand_hash[pid] = None
        # Khi bất kỳ P nào reset bài, coi như NGU key cũ không còn giá trị
        self._ngu_key = None
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
            self._codes_slot_order[pid] = list(codes)
            self._layout_codes[pid] = list(codes)
            if pid == self.active_profile:
                self.view.set_cards_p_normalized(list(codes))
                self.view.set_p_status("Đang tính gợi ý…")
            # trigger staged scheduler
            self._batch_debounce.stop()
            self._batch_debounce.start()
    def _apply_pending_ws_samehand_if_any(self, pid: str) -> None:
        try:
            codes = (getattr(self, "_pending_ws_samehand", {}) or {}).pop(pid, None)
        except Exception:
            codes = None

        if not (codes and isinstance(codes, list) and len(codes) == 13):
            return

        # SAME HAND: chỉ sync layout/slot + UI, KHÔNG force reset, KHÔNG trigger pipeline
        self._codes_slot_order[pid] = list(codes)
        self._layout_codes[pid] = list(codes)

        if pid == self.active_profile:
            try:
                self.view.set_cards_p_normalized(list(codes))
            except Exception:
                pass

    def _poll_ws(self) -> None:
        updates, waiting = self._ws_ingest.poll(
            ws_get_last_cards=ws_card_store.get_last_cards,
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

            # Always store raw snapshot (optional but useful for debug)
            self._ws_snapshot[pid] = list(up.raw_cards)

            codes = list(up.codes_slot_order or [])
            if len(codes) != 13:
                continue

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
                # SAME HAND: chỉ sync nhẹ, không reset, không trigger compute
                self._codes_slot_order[pid] = list(codes)
                self._layout_codes[pid] = list(codes)
                if pid == self.active_profile:
                    try:
                        self.view.set_cards_p_normalized(list(codes))
                    except Exception:
                        pass


        if any_new_hand:
            self._refresh_ngu_from_3p(force=True)

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
        return self._scheduler.poll_suggest_results(self)

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

    def _render_p_active(self) -> None:
        self._renderer.render_p_active(self)
        self._update_special_labels()   # mỗi lần render P active, cập nhật label


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
        Khi click ALL:
        - Lần lượt click P1 -> P2 -> P3 (giống user bấm nút P)
        - Mỗi lần click cách nhau 100ms để dễ quan sát
        - Sau đó mới chạy ApplyController.on_apply_all (hành vi cũ)
        """
        ordered = ["P1", "P2", "P3"]
        ordered = [pid for pid in ordered if pid in self.profiles]

        delay_ms = 100

        def _click_next(index: int):
            if index >= len(ordered):
                # Sau khi click xong P1,P2,P3 -> chạy ALL như cũ
                try:
                    self._apply_controller.on_apply_all(self)
                except Exception:
                    log.exception("[ALL] on_apply_all failed")
                return

            pid = ordered[index]
            try:
                log.info("[ALL] click profile %s", pid)
                self._on_profile_switch(pid)
            except Exception:
                log.exception("[ALL] click profile %s failed", pid)

            # Hẹn click profile tiếp theo sau 100ms
            QTimer.singleShot(delay_ms, lambda: _click_next(index + 1))

        # Bắt đầu chuỗi click
        _click_next(0)

    # ===== Legacy UI contract (used by strategy_suggest.py) =====
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
            if hasattr(self.view, "btn_hup") and self.view.btn_hup is not None:
                self.view.btn_hup.setEnabled(False)

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

            # Re-enable Apply button only if no other profile is busy (defensive).
            any_busy = any(bool(v) for v in getattr(self, "_apply_busy", {}).values())
            if hasattr(self.view, "btn_hup") and self.view.btn_hup is not None:
                self.view.btn_hup.setEnabled(not any_busy)

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
