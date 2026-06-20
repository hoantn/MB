import unittest
from unittest.mock import patch

from ui2.tabs.strategy2.modules.apply_controller import ApplyController


WS_CODES = ["2C", "3C", "4C", "5C", "6C", "7C", "8C", "9C", "TC", "JC", "QC", "KC", "AC"]


class _Tab:
    def __init__(self):
        self.profiles = ["P1", "P2", "P3"]
        self._codes_slot_order = {"P1": list(WS_CODES)}
        self._suggestions = {"P1": []}
        self._suggestions_render = {"P1": []}
        self._selected_index = {"P1": 0}
        self.flushed = []

    def _flush_pre_render_for_profile(self, pid):
        self.flushed.append(pid)
        self._suggestions_render[pid] = [
            {
                "mode": "money",
                "chi1_codes": WS_CODES[:5],
                "chi2_codes": WS_CODES[5:10],
                "chi3_codes": WS_CODES[10:],
            }
        ]

    def _is_special_row(self, _s):
        return False


class ApplyControllerPreRenderFlushTests(unittest.TestCase):
    def test_on_apply_flushes_pending_render_before_reading_suggestion(self):
        tab = _Tab()

        with patch(
            "ui2.tabs.strategy2.modules.apply_controller.apply_manual_copy_style"
        ) as apply_manual:
            ApplyController().on_apply(tab, "P1")

        self.assertEqual(tab.flushed, ["P1"])
        apply_manual.assert_called_once()
        kwargs = apply_manual.call_args.kwargs
        self.assertEqual(kwargs["profile_id"], "P1")
        self.assertEqual(kwargs["suggestion"]["chi1_codes"], WS_CODES[:5])


if __name__ == "__main__":
    unittest.main()
