from __future__ import annotations

import time
import logging
from typing import Callable


_log = logging.getLogger("MauBinhTool")


class PostEngineRenderer:
    """Owns UI-side work that happens after suggestion workers return.

    This intentionally keeps the existing call order. The first goal is to make
    the post-engine phase measurable and isolated without changing the final
    suggestion/render result.
    """

    def __init__(self, *, slow_step_ms: float = 8.0, slow_total_ms: float = 16.0) -> None:
        self.slow_step_ms = float(slow_step_ms)
        self.slow_total_ms = float(slow_total_ms)

    def _time_step(self, tab, name: str, fn: Callable[[], None]) -> None:
        start = time.perf_counter()
        try:
            fn()
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            if elapsed_ms >= self.slow_step_ms:
                try:
                    logger = getattr(tab, "log", _log)
                    logger.info("[Strategy2][post-engine] %s %.1fms", name, elapsed_ms)
                except Exception:
                    pass

    def pre_render_profile(self, tab, pid: str) -> None:
        self._time_step(tab, f"pre_render:{pid}", lambda: tab._pre_render_profile(pid))

    def _render_ngu_post_engine(self, tab) -> None:
        fn = getattr(tab, "_render_ngu_post_engine", None)
        if callable(fn):
            fn()
            return
        tab._render_ngu()

    def _is_ngu_refresh_pending(self, tab) -> bool:
        fn = getattr(tab, "_is_ngu_refresh_pending", None)
        if not callable(fn):
            return False
        try:
            return bool(fn())
        except Exception:
            return False

    def _allows_ngu_work(self, tab) -> bool:
        fn = getattr(tab, "_should_allow_ngu_work", None)
        if not callable(fn):
            return True
        try:
            return bool(fn())
        except Exception:
            return True

    def render_after_queue(
        self,
        tab,
        *,
        ngu_updated: bool,
        p_changed_any: bool,
        active_updated: bool,
        defer_ngu_work: bool = False,
        defer_p_work: bool = False,
    ) -> None:
        """Run the same final render sequence previously in StagedScheduler."""
        deferred_ngu_pending = bool(getattr(tab, "_post_engine_ngu_deferred", False))
        deferred_p_pending = bool(getattr(tab, "_post_engine_p_deferred", False))
        deferred_auto_pending = bool(getattr(tab, "_post_engine_auto_deferred", False))
        if not (
            ngu_updated
            or p_changed_any
            or active_updated
            or deferred_ngu_pending
            or deferred_p_pending
            or deferred_auto_pending
        ):
            return

        total_start = time.perf_counter()
        try:
            if ngu_updated or p_changed_any or deferred_ngu_pending or deferred_auto_pending:
                ngu_refresh_pending = self._is_ngu_refresh_pending(tab)
                allows_ngu_work = self._allows_ngu_work(tab)
                can_touch_ngu_after_refresh = not (ngu_refresh_pending and not ngu_updated)
                if defer_ngu_work and allows_ngu_work and can_touch_ngu_after_refresh:
                    try:
                        tab._post_engine_ngu_deferred = True
                    except Exception:
                        pass
                    deferred_ngu_pending = True
                should_touch_ngu = (
                    allows_ngu_work
                    and not defer_ngu_work
                    and can_touch_ngu_after_refresh
                )
                if should_touch_ngu and (ngu_updated or deferred_ngu_pending or not (tab._ngu_suggestions or [])):
                    self._time_step(tab, "render_ngu", lambda: self._render_ngu_post_engine(tab))
                    try:
                        tab._post_engine_ngu_deferred = False
                    except Exception:
                        pass
                elif not allows_ngu_work:
                    try:
                        tab._post_engine_ngu_deferred = False
                    except Exception:
                        pass

                if should_touch_ngu:
                    try:
                        self._time_step(tab, "rebuild_ngu_labels", tab._rebuild_ngu_labels_html)
                        self._time_step(
                            tab,
                            "commit_ngu_labels",
                            lambda: tab.view.set_ngu_labels(
                                tab._ngu_suggestions[:tab.MAX_UI_NGU_ITEMS],
                                tab._ngu_selected_index,
                            ),
                        )
                    except Exception:
                        # Match the legacy scheduler behavior: never crash UI on a
                        # small label rebuild issue.
                        pass

                if defer_p_work:
                    try:
                        tab._post_engine_p_deferred = True
                        tab._post_engine_auto_deferred = True
                    except Exception:
                        pass
                    return

                self._time_step(tab, "render_p_active", tab._render_p_active)
                try:
                    tab._post_engine_p_deferred = False
                except Exception:
                    pass
                if ngu_updated or p_changed_any or deferred_auto_pending:
                    try:
                        self._time_step(tab, "maybe_auto_play", tab._maybe_run_auto_play)
                    except Exception:
                        logger = getattr(tab, "log", _log)
                        logger.exception("[AUTO-PLAY] trigger after suggestions failed")
                    finally:
                        try:
                            tab._post_engine_auto_deferred = False
                        except Exception:
                            pass
                return

            if active_updated or deferred_p_pending:
                if defer_p_work:
                    try:
                        tab._post_engine_p_deferred = True
                    except Exception:
                        pass
                    return
                try:
                    self._time_step(tab, "render_p_active", tab._render_p_active)
                    try:
                        tab._post_engine_p_deferred = False
                    except Exception:
                        pass
                except Exception:
                    pass
                if deferred_auto_pending:
                    try:
                        self._time_step(tab, "maybe_auto_play", tab._maybe_run_auto_play)
                    except Exception:
                        logger = getattr(tab, "log", _log)
                        logger.exception("[AUTO-PLAY] trigger after deferred active render failed")
                    finally:
                        try:
                            tab._post_engine_auto_deferred = False
                        except Exception:
                            pass
        finally:
            elapsed_ms = (time.perf_counter() - total_start) * 1000.0
            if elapsed_ms >= self.slow_total_ms:
                try:
                    logger = getattr(tab, "log", _log)
                    logger.info("[Strategy2][post-engine] total %.1fms", elapsed_ms)
                except Exception:
                    pass
