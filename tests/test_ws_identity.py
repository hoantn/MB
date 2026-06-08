import unittest

from ui2.bridge.ws_card_store import _extract_cmd600
from ui2.tabs.strategy2.strategy_tab import StrategyTab


class WSIdentityTests(unittest.TestCase):
    def test_cmd606_never_becomes_original_hand(self):
        event = {
            "profile_id": "P1",
            "payload": {"cmd": 606, "cs": list(range(13))},
        }
        self.assertIsNone(_extract_cmd600(event))

    def test_hand_hash_ignores_slot_order(self):
        first = [f"C{i}" for i in range(13)]
        second = list(reversed(first))
        dummy = object()

        self.assertEqual(
            StrategyTab._hand_hash(dummy, first),
            StrategyTab._hand_hash(dummy, second),
        )


if __name__ == "__main__":
    unittest.main()
