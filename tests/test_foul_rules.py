import unittest

from engine.card import Card
from engine.foul_rules import evaluate_top_for_foul, is_no_foul_codes
from engine.money_scoring import _no_foul
from engine.arranger_parts.splits import _validate_no_foul


def _cards(codes):
    return [Card.from_code(code) for code in codes]


class FoulRulesTests(unittest.TestCase):
    def test_three_card_run_is_only_high_card(self):
        hand_type, detail = evaluate_top_for_foul(_cards(["QT", "KR", "AC"]))
        self.assertEqual(hand_type, 0)
        self.assertEqual(detail, [12, 11, 10])

    def test_real_log_layouts_are_valid(self):
        cases = [
            (
                ["9C", "QB", "JB", "TC", "KT"],
                ["3C", "2R", "5T", "3R", "3B"],
                ["QR", "AT", "KB"],
            ),
            (
                ["6R", "5B", "6T", "6B", "4R"],
                ["9B", "TT", "7C", "JT", "JC"],
                ["QT", "KR", "AC"],
            ),
            (
                ["KT", "JT", "QT", "TT", "AT"],
                ["6B", "8B", "2B", "3C", "8T"],
                ["KC", "QC", "JB"],
            ),
        ]
        for bottom, middle, top in cases:
            with self.subTest(top=top):
                self.assertTrue(is_no_foul_codes(bottom, middle, top))
                self.assertTrue(_no_foul(_cards(bottom), _cards(middle), _cards(top)))
                self.assertTrue(_validate_no_foul(_cards(bottom), _cards(middle), _cards(top)))

    def test_actual_foul_is_rejected_consistently(self):
        bottom = _cards(["2B", "3R", "4T", "7C", "9B"])
        middle = _cards(["AT", "AR", "5B", "6C", "8T"])
        top = _cards(["QT", "KR", "AC"])

        self.assertFalse(_no_foul(bottom, middle, top))
        self.assertFalse(_validate_no_foul(bottom, middle, top))


if __name__ == "__main__":
    unittest.main()
