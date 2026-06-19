import unittest
import sqlite3

from ui2.tabs.strategy2.auto_suggestion_picker import mark_auto_suggestion, split_key
import ui2.tabs.strategy2.auto_suggestion_picker as picker
import ui2.tabs.strategy2.auto_choice_rules as rules


def _sug(label, c1, c2, c3, *, mode="max", special=False):
    return {
        "mode": "special" if special else mode,
        "label": label,
        "chi1_codes": list(c1),
        "chi2_codes": list(c2),
        "chi3_codes": list(c3),
        "_is_special_row": bool(special),
    }


class AutoSuggestionPickerTests(unittest.TestCase):
    def test_without_money_row_falls_back_to_first_playable_and_mirrors_to_base(self):
        weaker = _sug(
            "weak",
            ["2C", "3C", "4C", "5C", "7D"],
            ["8D", "8S", "9D", "TD", "JD"],
            ["QD", "KD", "AD"],
        )
        stronger = _sug(
            "stronger",
            ["2C", "3C", "4C", "5C", "6C"],
            ["7D", "8D", "9D", "TD", "JD"],
            ["QD", "KD", "AD"],
        )
        base = [dict(weaker), dict(stronger)]
        final = [dict(weaker), dict(stronger)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 0)
        self.assertTrue(final[0].get("_auto_opp_money"))
        self.assertEqual(final[0].get("_auto_choice_source"), "fallback")
        self.assertEqual(
            [split_key(s) for s in base if s.get("_auto_opp_money")],
            [split_key(final[0])],
        )

    def test_engine_money_row_beats_other_visible_rows(self):
        money = _sug(
            "money row",
            ["2C", "3C", "4C", "5C", "6C"],
            ["7D", "7S", "9D", "TD", "JD"],
            ["QD", "KD", "AD"],
            mode="money",
        )
        stronger_visible = _sug(
            "stronger visible row",
            ["2D", "2S", "4C", "5C", "6C"],
            ["7D", "8D", "9D", "TD", "JD"],
            ["QC", "KC", "AC"],
        )
        base = [dict(money), dict(stronger_visible)]
        final = [dict(money), dict(stronger_visible)]

        idx = mark_auto_suggestion(base, final, policy="self")

        self.assertEqual(idx, 0)
        self.assertTrue(final[0].get("_auto_profile_money"))
        self.assertEqual(final[0].get("_auto_choice_source"), "engine_money")
        self.assertFalse(final[1].get("_auto_profile_money"))

    def test_user_rule_beats_money_like_default(self):
        default = _sug(
            "default",
            ["2C", "3C", "4C", "5C", "6C"],
            ["7D", "7S", "9D", "TD", "JD"],
            ["QD", "KD", "AD"],
        )
        learned = _sug(
            "learned",
            ["2D", "2S", "4C", "5C", "6C"],
            ["7D", "8D", "9D", "TD", "JD"],
            ["QC", "KC", "AC"],
        )
        base = [dict(default), dict(learned)]
        final = [dict(default), dict(learned)]
        used = []
        original_find = picker.find_rule_match
        original_mark = picker.mark_rule_used
        try:
            picker.find_rule_match = lambda hand_codes, suggestions, scope="global": (
                1,
                99,
                {"match_type": "exact", "similarity": 100.0},
            )
            picker.mark_rule_used = lambda rule_id: used.append(rule_id)

            idx = mark_auto_suggestion(
                base,
                final,
                policy="self",
                hand_codes=default["chi1_codes"] + default["chi2_codes"] + default["chi3_codes"],
            )

            self.assertEqual(idx, 1)
            self.assertTrue(final[1].get("_auto_profile_money"))
            self.assertTrue(final[1].get("_auto_user_rule"))
            self.assertEqual(final[1].get("_auto_choice_source"), "user_rule")
            self.assertEqual(used, [99])
        finally:
            picker.find_rule_match = original_find
            picker.mark_rule_used = original_mark

    def test_picker_skips_special_row(self):
        special = _sug(
            "special",
            ["2C", "3C", "4C", "5C", "6C"],
            ["7C", "8C", "9C", "TC", "JC"],
            ["QC", "KC", "AC"],
            special=True,
        )
        normal = _sug(
            "normal",
            ["2R", "3R", "4R", "5R", "6R"],
            ["7R", "8R", "9R", "TR", "JR"],
            ["QR", "KR", "AR"],
        )
        base = [dict(special), dict(normal)]
        final = [dict(special), dict(normal)]

        idx = mark_auto_suggestion(
            base,
            final,
            policy="self",
            is_special_row=lambda s: bool(s.get("_is_special_row")),
        )

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_profile_money"))
        self.assertFalse(final[0].get("_auto_profile_money"))

    def test_selected_money_mode_is_preserved_for_next_render(self):
        row = _sug(
            "money",
            ["2C", "3C", "4C", "5C", "6C"],
            ["7D", "8D", "9D", "TD", "JD"],
            ["QD", "KD", "AD"],
            mode="money",
        )
        base = [dict(row)]
        final = [dict(row)]

        idx = mark_auto_suggestion(base, final, policy="self")

        self.assertEqual(idx, 0)
        self.assertEqual(final[0].get("mode"), "money")
        self.assertEqual(base[0].get("mode"), "money")

    def test_appends_selected_row_when_base_does_not_contain_final_split(self):
        base_row = _sug(
            "base",
            ["2C", "3C", "4C", "5C", "7D"],
            ["8D", "8S", "9D", "TD", "JD"],
            ["QD", "KD", "AD"],
        )
        final_row = _sug(
            "final",
            ["2C", "3C", "4C", "5C", "6C"],
            ["7D", "8D", "9D", "TD", "JD"],
            ["QD", "KD", "AD"],
        )
        base = [dict(base_row)]
        final = [dict(final_row)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 0)
        self.assertEqual(len(base), 2)
        self.assertTrue(base[-1].get("_auto_opp_money"))
        self.assertEqual(split_key(base[-1]), split_key(final[0]))

    def test_saved_rule_is_unified_without_target(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        original_get_connection = rules.get_connection
        try:
            rules.get_connection = lambda: conn
            default = _sug(
                "default",
                ["2C", "3C", "4C", "5C", "6C"],
                ["7D", "7S", "9D", "TD", "JD"],
                ["QD", "KD", "AD"],
            )
            learned = _sug(
                "learned",
                ["2D", "2S", "4C", "5C", "6C"],
                ["7D", "8D", "9D", "TD", "JD"],
                ["QC", "KC", "AC"],
            )
            hand = default["chi1_codes"] + default["chi2_codes"] + default["chi3_codes"]

            self.assertTrue(rules.save_rule(hand, learned))
            idx, rule_id, info = rules.find_rule_match(hand, [default, learned])

            self.assertEqual(idx, 1)
            self.assertIsNotNone(rule_id)
            self.assertEqual(info.get("match_type"), "exact")
            self.assertEqual(len(rules.list_rules()), 1)

            self.assertTrue(rules.set_rule_enabled(int(rule_id), False))
            idx2, rule_id2, _info2 = rules.find_rule_match(hand, [default, learned])
            self.assertEqual(idx2, -1)
            self.assertIsNone(rule_id2)
        finally:
            rules.get_connection = original_get_connection

    def test_similar_rule_can_beat_money_when_enabled(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        original_get_connection = rules.get_connection
        try:
            rules.get_connection = lambda: conn
            saved_hand = [
                "2C", "2D", "3C", "3D", "4C",
                "4D", "5C", "6C", "7C", "8C",
                "9D", "TD", "AD",
            ]
            saved_choice = _sug(
                "learned full house style",
                ["4C", "4D", "5C", "6C", "7C"],
                ["2C", "2D", "3C", "3D", "8C"],
                ["9D", "TD", "AD"],
            )
            self.assertTrue(rules.save_rule(saved_hand, saved_choice))
            self.assertTrue(rules.save_ai_learning_settings(similarity_enabled=True, similarity_threshold=70))

            money = _sug(
                "money",
                ["5C", "6C", "7C", "8C", "9C"],
                ["2S", "2H", "3S", "3H", "4S"],
                ["TD", "JD", "AD"],
                mode="money",
            )
            similar = _sug(
                "similar learned",
                ["4S", "4H", "5C", "6C", "7C"],
                ["2S", "2H", "3S", "3H", "8C"],
                ["TD", "JD", "AD"],
            )
            current_hand = similar["chi1_codes"] + similar["chi2_codes"] + similar["chi3_codes"]
            base = [dict(money), dict(similar)]
            final = [dict(money), dict(similar)]

            idx = mark_auto_suggestion(base, final, policy="opp", hand_codes=current_hand)

            self.assertEqual(idx, 1)
            self.assertTrue(final[1].get("_auto_opp_money"))
            self.assertEqual(final[1].get("_auto_choice_source"), "user_rule_similar")
            self.assertGreaterEqual(final[1].get("_auto_rule_match", {}).get("similarity", 0), 70)
        finally:
            rules.get_connection = original_get_connection

    def test_disabling_similarity_keeps_money_default_for_non_exact_hand(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        original_get_connection = rules.get_connection
        try:
            rules.get_connection = lambda: conn
            saved_hand = ["2C", "2D", "3C", "3D", "4C", "4D", "5C", "6C", "7C", "8C", "9D", "TD", "AD"]
            saved_choice = _sug(
                "learned",
                ["4C", "4D", "5C", "6C", "7C"],
                ["2C", "2D", "3C", "3D", "8C"],
                ["9D", "TD", "AD"],
            )
            self.assertTrue(rules.save_rule(saved_hand, saved_choice))
            self.assertTrue(rules.save_ai_learning_settings(similarity_enabled=False, similarity_threshold=50))

            money = _sug(
                "money",
                ["5C", "6C", "7C", "8C", "9C"],
                ["2S", "2H", "3S", "3H", "4S"],
                ["TD", "JD", "AD"],
                mode="money",
            )
            similar = _sug(
                "similar learned",
                ["4S", "4H", "5C", "6C", "7C"],
                ["2S", "2H", "3S", "3H", "8C"],
                ["TD", "JD", "AD"],
            )
            current_hand = similar["chi1_codes"] + similar["chi2_codes"] + similar["chi3_codes"]
            base = [dict(money), dict(similar)]
            final = [dict(money), dict(similar)]

            idx = mark_auto_suggestion(base, final, policy="opp", hand_codes=current_hand)

            self.assertEqual(idx, 0)
            self.assertEqual(final[0].get("_auto_choice_source"), "engine_money")
        finally:
            rules.get_connection = original_get_connection


if __name__ == "__main__":
    unittest.main()
