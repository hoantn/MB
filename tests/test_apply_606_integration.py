import threading
import time
import unittest
from unittest.mock import patch

from engine.ws_card_mapping import CARD_TO_WS_CODE
from ui2.bridge.ws_layout_store import layout606_to_slot_order, ws_layout_store
from ui2.tabs.strategy2.modules.apply_confirmation import confirm_and_repair_layout
from ui2.tabs.strategy2.strategy_suggest import apply_suggestion_dashboard_style


BOTTOM = ["9C", "QB", "JB", "TC", "KT"]
MIDDLE = ["3C", "2R", "5T", "3R", "3B"]
TOP = ["QR", "AT", "KB"]
SLOT_LAYOUT = TOP + MIDDLE + BOTTOM
RAW_606 = [CARD_TO_WS_CODE[code] for code in reversed(SLOT_LAYOUT)]
SUGGESTION = {
    "mode": "money",
    "chi1_codes": BOTTOM,
    "chi2_codes": MIDDLE,
    "chi3_codes": TOP,
}


class _Signal:
    def emit(self, fn):
        fn()


class _BrowserManager:
    def get_active_tab(self, _pid):
        return object()


class _Tab:
    def __init__(self):
        self.browser_manager = _BrowserManager()
        self.ui_call = _Signal()
        self._layout_codes = {"P1": list(SLOT_LAYOUT)}
        self._apply_threads = {}
        self._ws_freeze = {}
        self._confirmed_apply_tokens = {}

    def _apply_btn_set_busy(self, _pid):
        return None

    def _apply_btn_set_default(self, _pid):
        return None


def _fast_confirmation(*args, **kwargs):
    kwargs["timeout_s"] = 0.08
    kwargs["first_snapshot_timeout_s"] = 0.08
    kwargs["timeout_retry_count"] = 0
    kwargs["timeout_retry_s"] = 0.08
    return confirm_and_repair_layout(*args, **kwargs)


class Apply606IntegrationTests(unittest.TestCase):
    def setUp(self):
        # Ép tạo generation mới để mỗi test không dùng snapshot singleton cũ.
        ws_layout_store.begin_hand("P1", list(range(13, 26)))
        ws_layout_store.begin_hand("P1", RAW_606)
        ws_layout_store.update_layout("P1", RAW_606, event_at=time.time())
        self.tab = _Tab()

    def _wait_worker(self):
        deadline = time.time() + 1.0
        while time.time() < deadline:
            worker = self.tab._apply_threads.get("P1")
            if worker is None:
                return
            worker.join(0.02)
        self.fail("apply worker did not finish")

    def test_auto_callbacks_only_run_after_confirmed_606(self):
        events = []

        def apply_ok(*_args, **_kwargs):
            threading.Timer(
                0.01,
                lambda: ws_layout_store.update_layout("P1", RAW_606, event_at=time.time()),
            ).start()
            return list(SLOT_LAYOUT)

        with patch("ui2.tabs.strategy2.strategy_suggest.apply_arrangement", side_effect=apply_ok):
            with patch(
                "ui2.tabs.strategy2.strategy_suggest.confirm_and_repair_layout",
                side_effect=_fast_confirmation,
            ):
                self.assertTrue(
                    apply_suggestion_dashboard_style(
                        self.tab,
                        "P1",
                        list(SLOT_LAYOUT),
                        dict(SUGGESTION),
                        on_complete=lambda: events.append("complete"),
                        on_finished=lambda: events.append("finished"),
                    )
                )
                self._wait_worker()

        self.assertEqual(events, ["complete", "finished"])
        self.assertTrue(self.tab._confirmed_apply_tokens.get("P1"))

    def test_no_606_blocks_complete_and_finished(self):
        events = []

        with patch(
            "ui2.tabs.strategy2.strategy_suggest.apply_arrangement",
            return_value=list(SLOT_LAYOUT),
        ):
            with patch(
                "ui2.tabs.strategy2.strategy_suggest.confirm_and_repair_layout",
                side_effect=_fast_confirmation,
            ):
                apply_suggestion_dashboard_style(
                    self.tab,
                    "P1",
                    list(SLOT_LAYOUT),
                    dict(SUGGESTION),
                    on_complete=lambda: events.append("complete"),
                    on_finished=lambda: events.append("finished"),
                    on_unsafe=lambda: events.append("unsafe"),
                )
                self._wait_worker()

        self.assertEqual(events, ["unsafe"])

    def test_missing_initial_606_still_drags_from_cmd600_then_fails_closed(self):
        ws_layout_store.begin_hand("P1", list(range(13, 26)))
        ws_layout_store.begin_hand("P1", RAW_606)
        events = []

        with patch(
            "ui2.tabs.strategy2.strategy_suggest.apply_arrangement",
            return_value=list(SLOT_LAYOUT),
        ) as apply_mock:
            with patch(
                "ui2.tabs.strategy2.strategy_suggest.confirm_and_repair_layout",
                side_effect=_fast_confirmation,
            ):
                spawned = apply_suggestion_dashboard_style(
                    self.tab,
                    "P1",
                    list(SLOT_LAYOUT),
                    dict(SUGGESTION),
                    on_unsafe=lambda reason: events.append(reason),
                )
                self._wait_worker()

        self.assertTrue(spawned)
        apply_mock.assert_called_once()
        self.assertEqual(events, ["layout606_timeout"])

    def test_first_drag_always_starts_from_cmd600_not_cache_or_old_606(self):
        self.tab._layout_codes["P1"] = list(reversed(SLOT_LAYOUT))
        captured_bases = []

        def apply_ok(_pid, _manager, base_layout, *_args, **_kwargs):
            captured_bases.append(list(base_layout))
            threading.Timer(
                0.01,
                lambda: ws_layout_store.update_layout("P1", RAW_606, event_at=time.time()),
            ).start()
            return list(SLOT_LAYOUT)

        with patch("ui2.tabs.strategy2.strategy_suggest.apply_arrangement", side_effect=apply_ok):
            with patch(
                "ui2.tabs.strategy2.strategy_suggest.confirm_and_repair_layout",
                side_effect=_fast_confirmation,
            ):
                self.assertTrue(
                    apply_suggestion_dashboard_style(
                        self.tab,
                        "P1",
                        list(SLOT_LAYOUT),
                        dict(SUGGESTION),
                    )
                )
                self._wait_worker()

        self.assertEqual(captured_bases, [SLOT_LAYOUT])

    def test_manual_apply_confirms_but_never_auto_completes(self):
        def apply_ok(*_args, **_kwargs):
            threading.Timer(
                0.01,
                lambda: ws_layout_store.update_layout("P1", RAW_606, event_at=time.time()),
            ).start()
            return list(SLOT_LAYOUT)

        with patch("ui2.tabs.strategy2.strategy_suggest.apply_arrangement", side_effect=apply_ok):
            with patch(
                "ui2.tabs.strategy2.strategy_suggest.confirm_and_repair_layout",
                side_effect=_fast_confirmation,
            ):
                apply_suggestion_dashboard_style(
                    self.tab,
                    "P1",
                    list(SLOT_LAYOUT),
                    dict(SUGGESTION),
                )
                self._wait_worker()

        self.assertTrue(self.tab._confirmed_apply_tokens.get("P1"))

    def test_intentional_foul_style_finishes_without_complete_callback(self):
        events = []

        def apply_ok(*_args, **_kwargs):
            threading.Timer(
                0.01,
                lambda: ws_layout_store.update_layout("P1", RAW_606, event_at=time.time()),
            ).start()
            return list(SLOT_LAYOUT)

        with patch("ui2.tabs.strategy2.strategy_suggest.apply_arrangement", side_effect=apply_ok):
            with patch(
                "ui2.tabs.strategy2.strategy_suggest.confirm_and_repair_layout",
                side_effect=_fast_confirmation,
            ):
                apply_suggestion_dashboard_style(
                    self.tab,
                    "P1",
                    list(SLOT_LAYOUT),
                    dict(SUGGESTION),
                    on_complete=None,
                    on_finished=lambda: events.append("finished"),
                )
                self._wait_worker()

        self.assertEqual(events, ["finished"])

    def test_mismatch_is_repaired_from_actual_606_before_callbacks(self):
        events = []
        mismatch = list(RAW_606)
        mismatch[0], mismatch[5] = mismatch[5], mismatch[0]
        calls = []

        def apply_then_repair(*_args, **_kwargs):
            calls.append(True)
            raw = mismatch if len(calls) == 1 else RAW_606
            threading.Timer(
                0.01,
                lambda value=list(raw): ws_layout_store.update_layout(
                    "P1", value, event_at=time.time()
                ),
            ).start()
            return list(SLOT_LAYOUT)

        with patch(
            "ui2.tabs.strategy2.strategy_suggest.apply_arrangement",
            side_effect=apply_then_repair,
        ):
            with patch(
                "ui2.tabs.strategy2.strategy_suggest.confirm_and_repair_layout",
                side_effect=_fast_confirmation,
            ):
                apply_suggestion_dashboard_style(
                    self.tab,
                    "P1",
                    list(SLOT_LAYOUT),
                    dict(SUGGESTION),
                    on_complete=lambda: events.append("complete"),
                    on_finished=lambda: events.append("finished"),
                )
                self._wait_worker()

        self.assertEqual(len(calls), 2)
        self.assertEqual(events, ["complete", "finished"])

    def test_double_pass_uses_fresh_606_layout_before_slow_confirm(self):
        events = []
        mismatch = list(RAW_606)
        mismatch[0], mismatch[5] = mismatch[5], mismatch[0]
        mismatch_layout = layout606_to_slot_order(mismatch)
        captured_bases = []

        def apply_then_fast_repair(_pid, _manager, base_layout, *_args, **_kwargs):
            captured_bases.append(list(base_layout))
            if len(captured_bases) == 1:
                threading.Timer(
                    0.005,
                    lambda: ws_layout_store.update_layout(
                        "P1", list(mismatch), event_at=time.time()
                    ),
                ).start()
            else:
                threading.Timer(
                    0.005,
                    lambda: ws_layout_store.update_layout(
                        "P1", RAW_606, event_at=time.time()
                    ),
                ).start()
            return list(SLOT_LAYOUT)

        with patch(
            "ui2.tabs.strategy2.strategy_suggest.load_config",
            return_value={
                "ui": {
                    "apply": {
                        "delay_between_drag_ms": 0,
                        "double_pass": True,
                        "double_pass_gap_ms": 20,
                    }
                }
            },
        ):
            with patch(
                "ui2.tabs.strategy2.strategy_suggest.apply_arrangement",
                side_effect=apply_then_fast_repair,
            ):
                with patch(
                    "ui2.tabs.strategy2.strategy_suggest.confirm_and_repair_layout",
                    side_effect=_fast_confirmation,
                ):
                    apply_suggestion_dashboard_style(
                        self.tab,
                        "P1",
                        list(SLOT_LAYOUT),
                        dict(SUGGESTION),
                        on_complete=lambda: events.append("complete"),
                        on_finished=lambda: events.append("finished"),
                    )
                    self._wait_worker()

        self.assertEqual(captured_bases, [SLOT_LAYOUT, mismatch_layout])
        self.assertEqual(events, ["complete", "finished"])

    def test_double_pass_ignores_606_captured_before_drag_finished(self):
        events = []
        mismatch = list(RAW_606)
        mismatch[0], mismatch[5] = mismatch[5], mismatch[0]
        captured_bases = []

        def apply_with_mid_drag_606(_pid, _manager, base_layout, *_args, **_kwargs):
            captured_bases.append(list(base_layout))
            ws_layout_store.update_layout("P1", list(mismatch), event_at=time.time())
            time.sleep(0.02)
            return list(SLOT_LAYOUT)

        with patch(
            "ui2.tabs.strategy2.strategy_suggest.load_config",
            return_value={
                "ui": {
                    "apply": {
                        "delay_between_drag_ms": 0,
                        "double_pass": True,
                        "double_pass_gap_ms": 20,
                    }
                }
            },
        ):
            with patch(
                "ui2.tabs.strategy2.strategy_suggest.apply_arrangement",
                side_effect=apply_with_mid_drag_606,
            ):
                with patch(
                    "ui2.tabs.strategy2.strategy_suggest.confirm_and_repair_layout",
                    side_effect=_fast_confirmation,
                ):
                    apply_suggestion_dashboard_style(
                        self.tab,
                        "P1",
                        list(SLOT_LAYOUT),
                        dict(SUGGESTION),
                        on_finished=lambda: events.append("finished"),
                        on_unsafe=lambda reason: events.append(reason),
                    )
                    self._wait_worker()

        self.assertEqual(captured_bases, [SLOT_LAYOUT])
        self.assertEqual(events, ["layout606_timeout"])


if __name__ == "__main__":
    unittest.main()
