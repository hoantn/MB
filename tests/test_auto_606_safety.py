import unittest

from ui2.tabs.strategy2.strategy_tab import StrategyTab


class _AutoDummy:
    profiles = ["P1", "P2", "P3"]
    _auto_play_enabled = True
    _auto_play_remaining = 10
    _auto_play_session = 1
    _auto_play_reservations = {}
    _auto_apply_unsafe_retry_counts = {}
    _auto_play_applied_profile_keys = set()
    _auto_play_hand_key = "hand"
    _auto_play_pending_key = "hand"

    def __init__(self):
        self.logs = []

    def _auto_play_log(self, message):
        self.logs.append(str(message))

    def _maybe_run_auto_play(self, _session=None):
        raise AssertionError("606 failure must not schedule a blind retry")

    def _auto_profile_apply_key(self, pid):
        return f"{pid}:hand"


class Auto606SafetyTests(unittest.TestCase):
    def test_606_failure_marks_profile_failed_without_retry(self):
        dummy = _AutoDummy()
        key = "P1:hand"
        dummy._auto_play_reservations = {key: "applied"}

        StrategyTab._auto_mark_profile_unsafe(
            dummy,
            key,
            {"P1": key},
            "layout606_timeout",
        )

        self.assertEqual(dummy._auto_play_reservations[key], "failed")
        self.assertTrue(any("retry" in line for line in dummy.logs))


if __name__ == "__main__":
    unittest.main()
