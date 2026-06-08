import unittest

from ui2.tabs.strategy2.modules.layout_verifier import LayoutScanResult, trusted_layout_codes


class LayoutVerifierTests(unittest.TestCase):
    def setUp(self):
        self.codes = [f"C{i}" for i in range(13)]

    def test_accepts_exact_high_confidence_scan(self):
        result = LayoutScanResult("P1", list(reversed(self.codes)), 1.0, [0.9] * 13)
        self.assertEqual(
            trusted_layout_codes(result, self.codes, min_confidence=0.7),
            list(reversed(self.codes)),
        )

    def test_rejects_wrong_card_set(self):
        wrong = list(self.codes)
        wrong[-1] = "OTHER"
        result = LayoutScanResult("P1", wrong, 1.0, [0.9] * 13)
        self.assertIsNone(trusted_layout_codes(result, self.codes))

    def test_rejects_low_confidence_scan(self):
        confidence = [0.9] * 13
        confidence[4] = 0.4
        result = LayoutScanResult("P1", self.codes, 1.0, confidence)
        self.assertIsNone(trusted_layout_codes(result, self.codes, min_confidence=0.7))


if __name__ == "__main__":
    unittest.main()
