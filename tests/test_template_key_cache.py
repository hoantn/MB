import unittest
from unittest.mock import patch

from ui2.tabs.strategy2.modules import templates as templates_module
from ui2.tabs.strategy2.modules.templates import extract_template_key_from_suggestion


def _suggestion():
    return {
        "chi1_codes": ["AC", "KC", "QC", "JC", "TC"],
        "chi2_codes": ["9R", "9C", "9B", "2T", "3C"],
        "chi3_codes": ["AB", "KB", "QB"],
    }


class TemplateKeyCacheTests(unittest.TestCase):
    def test_repeated_template_key_uses_cached_value_for_same_split(self):
        sug = _suggestion()
        original_eval_5 = templates_module.evaluate_5cards
        original_eval_3 = templates_module.evaluate_3cards

        with (
            patch.object(templates_module, "evaluate_5cards", side_effect=original_eval_5) as eval_5,
            patch.object(templates_module, "evaluate_3cards", side_effect=original_eval_3) as eval_3,
        ):
            first = extract_template_key_from_suggestion(sug)
            second = extract_template_key_from_suggestion(sug)

        self.assertEqual(first, second)
        self.assertEqual(eval_5.call_count, 2)
        self.assertEqual(eval_3.call_count, 1)

    def test_template_key_cache_invalidates_when_split_changes(self):
        sug = _suggestion()
        first = extract_template_key_from_suggestion(sug)

        original_eval_5 = templates_module.evaluate_5cards
        original_eval_3 = templates_module.evaluate_3cards
        sug["chi3_codes"] = ["AR", "KR", "QR"]

        with (
            patch.object(templates_module, "evaluate_5cards", side_effect=original_eval_5) as eval_5,
            patch.object(templates_module, "evaluate_3cards", side_effect=original_eval_3) as eval_3,
        ):
            changed = extract_template_key_from_suggestion(sug)
            cached = extract_template_key_from_suggestion(sug)

        self.assertIsNotNone(first)
        self.assertEqual(changed, cached)
        self.assertEqual(eval_5.call_count, 2)
        self.assertEqual(eval_3.call_count, 1)


if __name__ == "__main__":
    unittest.main()
