import unittest
from unittest.mock import patch

from ui2.tabs.strategy2.modules import labeling as labeling_module
from ui2.tabs.strategy2.modules.labeling import Labeling


class LabelingCompareCacheTests(unittest.TestCase):
    def test_compare_chi_5_card_result_is_cached_for_same_input(self):
        labeling = Labeling()
        original_eval = labeling_module.evaluate_5cards

        with patch.object(labeling_module, "evaluate_5cards", side_effect=original_eval) as eval_5:
            first = labeling.compare_chi(
                ["AC", "KC", "QC", "JC", "TC"],
                ["9R", "9C", "9B", "2T", "3C"],
                1,
            )
            second = labeling.compare_chi(
                ["AC", "KC", "QC", "JC", "TC"],
                ["9R", "9C", "9B", "2T", "3C"],
                1,
            )

        self.assertEqual(first, second)
        self.assertEqual(eval_5.call_count, 2)

    def test_compare_chi_3_card_result_is_cached_for_same_input(self):
        labeling = Labeling()
        original_eval = labeling_module.evaluate_3cards

        with patch.object(labeling_module, "evaluate_3cards", side_effect=original_eval) as eval_3:
            first = labeling.compare_chi(["AC", "AB", "AT"], ["KR", "QC", "2B"], 3)
            second = labeling.compare_chi(["AC", "AB", "AT"], ["KR", "QC", "2B"], 3)

        self.assertEqual(first, second)
        self.assertEqual(eval_3.call_count, 2)


if __name__ == "__main__":
    unittest.main()
