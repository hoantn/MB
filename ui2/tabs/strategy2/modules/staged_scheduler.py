from __future__ import annotations

import hashlib
import threading
import time
from collections import deque


class StagedScheduler:
    """
    Extracted staged sequential scheduler from StrategyTab.

    Nguyên tắc:
    - Chỉ move/điều phối, không đụng engine/worker/luật.
    - Không đổi tuple-shape put vào tab._q.
    - StrategyTab vẫn giữ pipeline adapters: _build_base_suggestion, _filter_extras.
    - Fix: không cần active tab vẫn có selected mặc định + label_html sẵn (pre-render compute-only).
    """

    def __init__(self) -> None:
        self.job_q = deque()  # items: (key, stage, kind, hand_hash, codes_snapshot)
        self.job_running: bool = False

    # ---- moved from StrategyTab._enqueue_batch_jobs ----
    def enqueue_batch_jobs(self, tab) -> None:
        pending_ngu_refresh = False
        pending_fn = getattr(tab, "_is_ngu_refresh_pending", None)
        if callable(pending_fn):
            try:
                pending_ngu_refresh = bool(pending_fn())
            except Exception:
                pending_ngu_refresh = False

        allow_ngu_jobs = True
        allow_fn = getattr(tab, "_should_enqueue_ngu_jobs", None)
        if callable(allow_fn):
            try:
                allow_ngu_jobs = bool(allow_fn())
            except Exception:
                allow_ngu_jobs = False

        if pending_ngu_refresh:
            tab._ngu_base_codes = []
            tab._ngu_key = None
        elif not allow_ngu_jobs:
            clear_fn = getattr(tab, "_clear_ngu_for_ineligible_room", None)
            if callable(clear_fn):
                try:
                    clear_fn()
                except Exception:
                    tab._ngu_base_codes = []
                    tab._ngu_key = None
            else:
                tab._ngu_base_codes = []
                tab._ngu_key = None
        else:
            derived = tab._derive_ngu_from_3p()
            if derived is not None:
                tab._ngu_base_codes = list(derived)
                tab._ngu_key = hashlib.md5("|".join(derived).encode()).hexdigest()
            else:
                tab._ngu_base_codes = []
                tab._ngu_key = None

        ps = tab._pipeline.build_snapshot(
            codes_slot_order=tab._codes_slot_order,
            ngu_codes13=tab._ngu_base_codes if (tab._ngu_base_codes and len(tab._ngu_base_codes) == 13) else None,
        )
        snapshot = ps.snapshot
        ordered_keys = ps.ordered_keys

        if not snapshot:
            return

        while self.job_q:
            try:
                dropped_key, _stage, _kind, dropped_hash, _codes = self.job_q.popleft()
                if tab._scheduled_hash.get(dropped_key) == dropped_hash:
                    tab._scheduled_hash[dropped_key] = None
            except Exception:
                continue

        # Chỉ còn 1 job duy nhất cho mỗi key: EXTRA/ALL
        for k in ordered_keys:
            codes = snapshot[k]
            h = tab._hand_hash(codes)
            if tab._scheduled_hash.get(k) == h:
                continue
            tab._scheduled_hash[k] = h

            # EXTRA/ALL sẽ gọi build_suggestions_for_codes (Cách 2)
            self.job_q.append((k, "EXTRA", "ALL", h, list(codes)))

        self.run_next_job(tab)

    # ---- moved from StrategyTab._run_next_job ----
    def run_next_job(self, tab) -> None:
        if self.job_running:
            return
        if not self.job_q:
            return

        k, stage, kind, h, codes = self.job_q.popleft()

        if len(codes) != 13:
            self.run_next_job(tab)
            return

        cur_codes = tab._ngu_base_codes if k == "NGU" else (tab._codes_slot_order.get(k) or [])
        if len(cur_codes) != 13 or tab._hand_hash(cur_codes) != h:
            # ván đã đổi / snapshot mismatch -> bỏ job
            if tab._scheduled_hash.get(k) == h:
                tab._scheduled_hash[k] = None
            self.run_next_job(tab)
            return

        self.job_running = True

        if k == tab.active_profile and stage == "BASE":
            tab.view.set_p_status("Đang tính gợi ý…")

        def _worker():
            try:
                if stage == "BASE":
                    res = tab._build_base_suggestion(k, codes, kind)
                    tab._q.put((k, None, [res] if res else [], None, stage, kind, h))
                else:
                    full = tab.build_suggestions_for_codes(k, codes)
                    extras = tab._filter_extras(full)
                    tab._q.put((k, None, extras, None, stage, kind, h))
            except Exception as e:
                tab._q.put((k, None, None, e, stage, kind, h))

        threading.Thread(
            target=_worker,
            name=f"MB-Strategy2-Job-{k}-{stage}-{kind}",
            daemon=True
        ).start()

    def _pre_render_profile(self, tab, key: str) -> None:
        post_renderer = getattr(tab, "_post_engine_renderer", None)
        if post_renderer is not None:
            post_renderer.pre_render_profile(tab, key)
            return
        tab._pre_render_profile(key)

    def _render_after_queue(
        self,
        tab,
        *,
        ngu_updated: bool,
        p_changed_any: bool,
        active_updated: bool,
        defer_ngu_work: bool = False,
        defer_p_work: bool = False,
    ) -> None:
        post_renderer = getattr(tab, "_post_engine_renderer", None)
        if post_renderer is not None:
            try:
                post_renderer.render_after_queue(
                    tab,
                    ngu_updated=ngu_updated,
                    p_changed_any=p_changed_any,
                    active_updated=active_updated,
                    defer_ngu_work=defer_ngu_work,
                    defer_p_work=defer_p_work,
                )
            except TypeError as exc:
                if "defer_ngu_work" not in str(exc) and "defer_p_work" not in str(exc):
                    raise
                post_renderer.render_after_queue(
                    tab,
                    ngu_updated=ngu_updated,
                    p_changed_any=p_changed_any,
                    active_updated=active_updated,
                )
            return

        # Legacy fallback for lightweight tests/mocks that do not build a full StrategyTab.
        if ngu_updated or p_changed_any:
            if not defer_ngu_work:
                if ngu_updated or not (tab._ngu_suggestions or []):
                    tab._render_ngu()

                try:
                    tab._rebuild_ngu_labels_html()
                    tab.view.set_ngu_labels(
                        tab._ngu_suggestions[:tab.MAX_UI_NGU_ITEMS],
                        tab._ngu_selected_index,
                    )
                except Exception:
                    pass

            if defer_p_work:
                try:
                    tab._post_engine_p_deferred = True
                    tab._post_engine_auto_deferred = True
                except Exception:
                    pass
                return

            tab._render_p_active()
            try:
                tab._post_engine_p_deferred = False
            except Exception:
                pass
            try:
                tab._maybe_run_auto_play()
            except Exception:
                logger = getattr(tab, "log", None)
                if logger is not None:
                    logger.exception("[AUTO-PLAY] trigger after suggestions failed")
            finally:
                try:
                    tab._post_engine_auto_deferred = False
                except Exception:
                    pass

        elif active_updated:
            if defer_p_work:
                try:
                    tab._post_engine_p_deferred = True
                except Exception:
                    pass
                return
            try:
                tab._render_p_active()
                try:
                    tab._post_engine_p_deferred = False
                except Exception:
                    pass
            except Exception:
                pass

    # ---- moved from StrategyTab._poll_suggest_results ----
    def poll_suggest_results(self, tab) -> None:
        active_updated = False
        ngu_updated = False
        p_changed_any = False

        deadline = time.perf_counter() + 0.010
        processed = 0
        while processed < 6:
            if time.perf_counter() >= deadline:
                break
            try:
                item = tab._q.get_nowait()
            except Exception:
                break

            processed += 1
            if len(item) == 4:
                key, _gen, sugg, err = item
                stage, kind, h = "FULL", "ALL", None
            else:
                key, _gen, sugg, err, stage, kind, h = item

            if key == "NGU":
                allow_fn = getattr(tab, "_should_enqueue_ngu_jobs", None)
                allow_ngu_result = True
                if callable(allow_fn):
                    try:
                        allow_ngu_result = bool(allow_fn())
                    except Exception:
                        allow_ngu_result = False
                if not allow_ngu_result:
                    clear_fn = getattr(tab, "_clear_ngu_for_ineligible_room", None)
                    if callable(clear_fn):
                        try:
                            clear_fn()
                        except Exception:
                            pass
                    if h is not None and tab._scheduled_hash.get(key) == h:
                        tab._scheduled_hash[key] = None
                    self.job_running = False
                    self.run_next_job(tab)
                    continue

            if h is not None:
                cur_codes = tab._ngu_base_codes if key == "NGU" else (tab._codes_slot_order.get(key) or [])
                if len(cur_codes) != 13 or tab._hand_hash(cur_codes) != h:
                    if tab._scheduled_hash.get(key) == h:
                        tab._scheduled_hash[key] = None
                    self.job_running = False
                    self.run_next_job(tab)
                    continue

            if err is not None:
                if h is not None and tab._scheduled_hash.get(key) == h:
                    tab._scheduled_hash[key] = None
                if key == tab.active_profile:
                    tab.view.set_p_status("Lỗi gợi ý")
                if key == "NGU":
                    tab.view.set_ngu_status("Lỗi gợi ý NGU")
                self.job_running = False
                self.run_next_job(tab)
                continue

            suggs = sugg or []
            if not suggs and h is not None and tab._scheduled_hash.get(key) == h:
                tab._scheduled_hash[key] = None

            if stage == "BASE":
                if key == "NGU":
                    # -------- NGU: giữ nguyên logic hiện tại --------
                    base_map = {str(s.get("mode")).lower(): s for s in tab._ngu_suggestions}
                    for s in suggs:
                        base_map[str(s.get("mode")).lower()] = s
                    merged = []
                    if "max" in base_map:
                        merged.append(base_map["max"])
                    tab._ngu_suggestions = merged

                    if tab._ngu_base_codes and len(tab._ngu_base_codes) == 13:
                        tab._ngu_suggestions = tab._inject_special_row_for_profile(
                            "NGU",
                            tab._ngu_base_codes,
                            tab._ngu_suggestions,
                        )

                    tab._ngu_selected_index = tab.pick_default_suggestion(tab._ngu_suggestions)
                    if tab._ngu_selected_index < 0:
                        tab._ngu_selected_index = 0
                    if tab._ngu_suggestions and tab._is_special_row(tab._ngu_suggestions[0]):
                        if tab._ngu_selected_index <= 0:
                            tab._ngu_selected_index = 1

                    for s in tab._ngu_suggestions:
                        if tab._is_special_row(s):
                            continue
                        if not s.get("_split_key"):
                            s["_split_key"] = tab._make_split_key(s)
                        ctx = tab.LabelingContext(
                            profiles=tab.profiles,
                            active_profile=tab.active_profile,
                            suggestions=tab._suggestions,
                            suggestions_render=tab._suggestions_render,
                            selected_index=tab._selected_index,
                            max_ui_ngu_items=tab.MAX_UI_NGU_ITEMS,
                        )
                        s["label_html"] = tab._labeling.build_label_html_ngu_vs_3p(s, ctx, tab._is_special_row)

                    tab.view.set_ngu_labels(tab._ngu_suggestions[:tab.MAX_UI_NGU_ITEMS], tab._ngu_selected_index)
                    ngu_updated = True

                else:
                    # -------- P1/P2/P3 --------
                    base_map = {str(s.get("mode")).lower(): s for s in (tab._suggestions.get(key) or [])}
                    for s in suggs:
                        base_map[str(s.get("mode")).lower()] = s
                    merged = []
                    if "max" in base_map:
                        merged.append(base_map["max"])

                    tab._suggestions[key] = merged
                    p_changed_any = True

                    # (1) Chọn mặc định đúng rule
                    idx = int(tab._selected_index.get(key, 0))
                    if idx < 0 or idx >= len(merged):
                        idx = tab.pick_default_suggestion(merged)
                        if idx < 0:
                            idx = 0
                    # Né special-row nếu nó đứng đầu và có >1 item
                    # if merged and tab._is_special_row(merged[0]) and idx <= 0 and len(merged) > 1:
                        # idx = 1
                    tab._selected_index[key] = idx

                    # (2) Pre-render compute-only để P không active vẫn có label_html sẵn
                    try:
                        self._pre_render_profile(tab, key)
                    except Exception:
                        pass

                    if key == tab.active_profile:
                        active_updated = True

            elif stage == "EXTRA":
                if key == "NGU":
                    # -------- NGU EXTRA (FULL list cho đúng 1 ván NGU hiện tại) --------
                    extras = list(suggs or [])

                    for s in extras:
                        if tab._is_special_row(s):
                            continue
                        if not s.get("_split_key"):
                            s["_split_key"] = tab._make_split_key(s)

                    tab._ngu_suggestions = extras[:tab.MAX_UI_NGU_ITEMS]

                    if tab._ngu_base_codes and len(tab._ngu_base_codes) == 13:
                        tab._ngu_suggestions = tab._inject_special_row_for_profile(
                            "NGU",
                            tab._ngu_base_codes,
                            tab._ngu_suggestions,
                        )

                    if tab._ngu_selected_index < 0 or tab._ngu_selected_index >= len(tab._ngu_suggestions):
                        tab._ngu_selected_index = tab.pick_default_suggestion(tab._ngu_suggestions)
                        if tab._ngu_selected_index < 0:
                            tab._ngu_selected_index = 0

                    if (
                        tab._ngu_suggestions
                        and tab._is_special_row(tab._ngu_suggestions[0])
                        and tab._ngu_selected_index <= 0
                        and len(tab._ngu_suggestions) > 1
                    ):
                        tab._ngu_selected_index = 1

                    ngu_updated = True

                else:
                    # -------- P1/P2/P3 EXTRA --------
                    base = list(tab._suggestions.get(key) or [])
                    tab._suggestions[key] = base + list(suggs or [])
                    p_changed_any = True

                    # Pre-render compute-only (để label_html cập nhật sẵn cho P không active)
                    try:
                        self._pre_render_profile(tab, key)
                    except Exception:
                        pass

                    if key == tab.active_profile:
                        active_updated = True
            else:
                if key == "NGU":
                    # -------- NGU FULL --------
                    tab._ngu_suggestions = list(suggs[:tab.MAX_UI_NGU_ITEMS])

                    if tab._ngu_base_codes and len(tab._ngu_base_codes) == 13:
                        tab._ngu_suggestions = tab._inject_special_row_for_profile(
                            "NGU",
                            tab._ngu_base_codes,
                            tab._ngu_suggestions,
                        )

                    tab._ngu_selected_index = tab.pick_default_suggestion(tab._ngu_suggestions)
                    if tab._ngu_selected_index < 0:
                        tab._ngu_selected_index = 0
                    if (
                        tab._ngu_suggestions
                        and tab._is_special_row(tab._ngu_suggestions[0])
                        and tab._ngu_selected_index <= 0
                    ):
                        tab._ngu_selected_index = 1

                    for s in tab._ngu_suggestions:
                        if tab._is_special_row(s):
                            continue
                        if not s.get("_split_key"):
                            s["_split_key"] = tab._make_split_key(s)
                        ctx = tab.LabelingContext(
                            profiles=tab.profiles,
                            active_profile=tab.active_profile,
                            suggestions=tab._suggestions,
                            suggestions_render=tab._suggestions_render,
                            selected_index=tab._selected_index,
                            max_ui_ngu_items=tab.MAX_UI_NGU_ITEMS,
                        )
                        s["label_html"] = tab._labeling.build_label_html_ngu_vs_3p(s, ctx, tab._is_special_row)

                    tab.view.set_ngu_labels(tab._ngu_suggestions, tab._ngu_selected_index)
                    ngu_updated = True

                else:
                    tab._suggestions[key] = list(suggs)
                    p_changed_any = True

                    # Default select + pre-render compute-only
                    try:
                        merged = tab._suggestions[key] or []
                        idx = tab.pick_default_suggestion(merged)
                        if idx < 0:
                            idx = 0
                        if merged and tab._is_special_row(merged[0]) and idx <= 0 and len(merged) > 1:
                            idx = 1
                        tab._selected_index[key] = idx
                        self._pre_render_profile(tab, key)
                    except Exception:
                        pass

                    if key == tab.active_profile:
                        active_updated = True

            self.job_running = False
            self.run_next_job(tab)

        defer_ngu_work = bool(self.job_running or self.job_q)
        try:
            defer_ngu_work = defer_ngu_work or (not tab._q.empty())
        except Exception:
            pass
        defer_p_work = bool(defer_ngu_work)

        # === SAU KHI XỬ LÝ QUEUE: RENDER UI =====
        self._render_after_queue(
            tab,
            ngu_updated=ngu_updated,
            p_changed_any=p_changed_any,
            active_updated=active_updated,
            defer_ngu_work=defer_ngu_work,
            defer_p_work=defer_p_work,
        )
