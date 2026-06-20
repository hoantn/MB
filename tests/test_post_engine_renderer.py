import unittest

from ui2.tabs.strategy2.modules.post_engine_renderer import PostEngineRenderer


class _Log:
    def __init__(self, calls):
        self.calls = calls

    def info(self, *_args):
        pass

    def exception(self, message):
        self.calls.append(("log_exception", message))


class _View:
    def __init__(self, calls):
        self.calls = calls

    def set_ngu_labels(self, items, selected_index):
        self.calls.append(("set_ngu_labels", list(items), selected_index))


class _Tab:
    MAX_UI_NGU_ITEMS = 2

    def __init__(self):
        self.calls = []
        self.log = _Log(self.calls)
        self.view = _View(self.calls)
        self._ngu_suggestions = [{"mode": "a"}, {"mode": "b"}, {"mode": "c"}]
        self._ngu_selected_index = 1

    def _pre_render_profile(self, pid):
        self.calls.append(("pre_render", pid))

    def _render_ngu(self):
        self.calls.append(("render_ngu",))

    def _rebuild_ngu_labels_html(self):
        self.calls.append(("rebuild_ngu_labels",))

    def _render_p_active(self):
        self.calls.append(("render_p_active",))

    def _maybe_run_auto_play(self):
        self.calls.append(("maybe_auto_play",))


class _TabWithPostEngineHook(_Tab):
    def _render_ngu_post_engine(self):
        self.calls.append(("render_ngu_post_engine",))


class _TabWithPendingNgu(_Tab):
    def _is_ngu_refresh_pending(self):
        return True


class _TabWithBlockedNgu(_Tab):
    def _should_allow_ngu_work(self):
        return False


class _TabWithPreRenderQueue(_Tab):
    def _queue_pre_render_profile(self, pid):
        self.calls.append(("queue_pre_render", pid))


class PostEngineRendererTests(unittest.TestCase):
    def test_pre_render_profile_delegates_without_changing_contract(self):
        tab = _Tab()
        renderer = PostEngineRenderer()

        renderer.pre_render_profile(tab, "P2")

        self.assertEqual(tab.calls, [("pre_render", "P2")])

    def test_pre_render_profile_uses_idle_queue_when_available(self):
        tab = _TabWithPreRenderQueue()
        renderer = PostEngineRenderer()

        renderer.pre_render_profile(tab, "P2")

        self.assertEqual(tab.calls, [("queue_pre_render", "P2")])

    def test_full_post_engine_sequence_keeps_legacy_order(self):
        tab = _Tab()
        renderer = PostEngineRenderer()

        renderer.render_after_queue(
            tab,
            ngu_updated=True,
            p_changed_any=True,
            active_updated=True,
        )

        self.assertEqual(
            tab.calls,
            [
                ("render_ngu",),
                ("rebuild_ngu_labels",),
                ("set_ngu_labels", [{"mode": "a"}, {"mode": "b"}], 1),
                ("render_p_active",),
                ("maybe_auto_play",),
            ],
        )

    def test_full_post_engine_sequence_uses_post_engine_ngu_hook_when_available(self):
        tab = _TabWithPostEngineHook()
        renderer = PostEngineRenderer()

        renderer.render_after_queue(
            tab,
            ngu_updated=True,
            p_changed_any=True,
            active_updated=True,
        )

        self.assertEqual(
            tab.calls,
            [
                ("render_ngu_post_engine",),
                ("rebuild_ngu_labels",),
                ("set_ngu_labels", [{"mode": "a"}, {"mode": "b"}], 1),
                ("render_p_active",),
                ("maybe_auto_play",),
            ],
        )

    def test_p_change_without_ngu_data_still_renders_ngu_first(self):
        tab = _Tab()
        tab._ngu_suggestions = []
        renderer = PostEngineRenderer()

        renderer.render_after_queue(
            tab,
            ngu_updated=False,
            p_changed_any=True,
            active_updated=False,
        )

        self.assertEqual(tab.calls[0], ("render_ngu",))
        self.assertIn(("render_p_active",), tab.calls)

    def test_p_change_during_ngu_debounce_skips_ngu_work(self):
        tab = _TabWithPendingNgu()
        tab._ngu_suggestions = []
        renderer = PostEngineRenderer()

        renderer.render_after_queue(
            tab,
            ngu_updated=False,
            p_changed_any=True,
            active_updated=False,
        )

        self.assertEqual(
            tab.calls,
            [
                ("render_p_active",),
                ("maybe_auto_play",),
            ],
        )

    def test_p_change_when_ngu_room_gate_blocks_skips_ngu_work(self):
        tab = _TabWithBlockedNgu()
        renderer = PostEngineRenderer()

        renderer.render_after_queue(
            tab,
            ngu_updated=False,
            p_changed_any=True,
            active_updated=False,
        )

        self.assertEqual(
            tab.calls,
            [
                ("render_p_active",),
                ("maybe_auto_play",),
            ],
        )

    def test_pending_batch_defers_ngu_work_but_keeps_p_render_and_auto_check(self):
        tab = _Tab()
        renderer = PostEngineRenderer()

        renderer.render_after_queue(
            tab,
            ngu_updated=True,
            p_changed_any=True,
            active_updated=True,
            defer_ngu_work=True,
        )

        self.assertEqual(
            tab.calls,
            [
                ("render_p_active",),
                ("maybe_auto_play",),
            ],
        )
        self.assertTrue(tab._post_engine_ngu_deferred)

    def test_deferred_ngu_work_renders_once_when_batch_finishes(self):
        tab = _Tab()
        renderer = PostEngineRenderer()

        renderer.render_after_queue(
            tab,
            ngu_updated=True,
            p_changed_any=True,
            active_updated=True,
            defer_ngu_work=True,
        )
        tab.calls.clear()

        renderer.render_after_queue(
            tab,
            ngu_updated=False,
            p_changed_any=True,
            active_updated=True,
            defer_ngu_work=False,
        )

        self.assertEqual(
            tab.calls,
            [
                ("render_ngu",),
                ("rebuild_ngu_labels",),
                ("set_ngu_labels", [{"mode": "a"}, {"mode": "b"}], 1),
                ("render_p_active",),
                ("maybe_auto_play",),
            ],
        )
        self.assertFalse(tab._post_engine_ngu_deferred)

    def test_pending_batch_defers_p_render_and_auto_until_queue_is_stable(self):
        tab = _Tab()
        renderer = PostEngineRenderer()

        renderer.render_after_queue(
            tab,
            ngu_updated=True,
            p_changed_any=True,
            active_updated=True,
            defer_ngu_work=True,
            defer_p_work=True,
        )

        self.assertEqual(tab.calls, [])
        self.assertTrue(tab._post_engine_ngu_deferred)
        self.assertTrue(tab._post_engine_p_deferred)
        self.assertTrue(tab._post_engine_auto_deferred)

        renderer.render_after_queue(
            tab,
            ngu_updated=False,
            p_changed_any=False,
            active_updated=False,
            defer_ngu_work=False,
            defer_p_work=False,
        )

        self.assertEqual(
            tab.calls,
            [
                ("render_ngu",),
                ("rebuild_ngu_labels",),
                ("set_ngu_labels", [{"mode": "a"}, {"mode": "b"}], 1),
                ("render_p_active",),
                ("maybe_auto_play",),
            ],
        )
        self.assertFalse(tab._post_engine_ngu_deferred)
        self.assertFalse(tab._post_engine_p_deferred)
        self.assertFalse(tab._post_engine_auto_deferred)

    def test_active_only_deferred_p_render_does_not_trigger_auto_play(self):
        tab = _Tab()
        renderer = PostEngineRenderer()

        renderer.render_after_queue(
            tab,
            ngu_updated=False,
            p_changed_any=False,
            active_updated=True,
            defer_p_work=True,
        )

        self.assertEqual(tab.calls, [])
        self.assertTrue(tab._post_engine_p_deferred)
        self.assertFalse(getattr(tab, "_post_engine_auto_deferred", False))

        renderer.render_after_queue(
            tab,
            ngu_updated=False,
            p_changed_any=False,
            active_updated=False,
        )

        self.assertEqual(tab.calls, [("render_p_active",)])
        self.assertFalse(tab._post_engine_p_deferred)
        self.assertFalse(getattr(tab, "_post_engine_auto_deferred", False))

    def test_active_only_renders_p_without_auto_play(self):
        tab = _Tab()
        renderer = PostEngineRenderer()

        renderer.render_after_queue(
            tab,
            ngu_updated=False,
            p_changed_any=False,
            active_updated=True,
        )

        self.assertEqual(tab.calls, [("render_p_active",)])


if __name__ == "__main__":
    unittest.main()
