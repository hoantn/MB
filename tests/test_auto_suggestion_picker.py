import unittest

import ui2.tabs.strategy2.auto_suggestion_picker as picker
from ui2.tabs.strategy2.auto_suggestion_picker import (
    mark_auto_suggestion,
    split_key,
)


def _sug(label, c1, c2, c3, *, special=False):
    return {
        "mode": "special" if special else "max",
        "label": label,
        "chi1_codes": list(c1),
        "chi2_codes": list(c2),
        "chi3_codes": list(c3),
        "_is_special_row": bool(special),
    }


class AutoSuggestionPickerTests(unittest.TestCase):
    def test_opp_auto_is_marked_from_existing_final_list_by_policy(self):
        first = _sug(
            "dead top",
            ["2C", "2R", "4B", "5T", "6C"],
            ["7C", "8R", "9B", "TC", "JC"],
            ["QC", "KR", "AC"],
        )
        second = _sug(
            "three live",
            ["2R", "2B", "4R", "4B", "6R"],
            ["7R", "7B", "9R", "TR", "JR"],
            ["QR", "QB", "AR"],
        )
        base = [dict(first), dict(second)]
        final = [dict(first), dict(second)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertEqual(
            [split_key(s) for s in base if s.get("_auto_opp_money")],
            [split_key(final[1])],
        )

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

    def test_premium_straight_pair_high_dead_top_beats_weak_three_pairs(self):
        straight_pair_high_top = _sug(
            "straight pair high top",
            ["4B", "5T", "6R", "7C", "8C"],
            ["2C", "QR", "QC", "6R", "7C"],
            ["9R", "TC", "AR"],
        )
        weak_three_pairs = _sug(
            "weak three pairs",
            ["2C", "QR", "QC", "4B", "5T"],
            ["9R", "TC", "7B", "7C", "8C"],
            ["AR", "6T", "6R"],
        )
        base = [dict(weak_three_pairs), dict(straight_pair_high_top)]
        final = [dict(weak_three_pairs), dict(straight_pair_high_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_straight_flush_bonus_beats_three_live_without_bonus(self):
        straight_flush_bonus = _sug(
            "straight flush bonus",
            ["TS", "JS", "QS", "KS", "AS"],
            ["3C", "8H", "8C", "TC", "KC"],
            ["6H", "9D", "QH"],
        )
        three_live_no_bonus = _sug(
            "three live no bonus",
            ["3C", "8H", "8C", "TS", "TC"],
            ["6H", "9D", "JS", "KS", "KC"],
            ["QH", "QS", "AS"],
        )
        base = [dict(three_live_no_bonus), dict(straight_flush_bonus)]
        final = [dict(three_live_no_bonus), dict(straight_flush_bonus)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_full_house_trips_high_top_beats_trips_trips_small_top_pair(self):
        trips_trips_small_top_pair = _sug(
            "trips trips small top pair",
            ["4H", "5D", "9D", "9S", "9C"],
            ["6D", "6S", "6C", "JH", "QH"],
            ["2D", "2H", "AS"],
        )
        full_house_trips_high_top = _sug(
            "full house trips high top",
            ["2D", "2H", "9D", "9S", "9C"],
            ["6D", "6S", "6C", "JH", "QH"],
            ["4H", "5D", "AS"],
        )
        base = [dict(trips_trips_small_top_pair), dict(full_house_trips_high_top)]
        final = [dict(trips_trips_small_top_pair), dict(full_house_trips_high_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_flush_two_pair_high_top_beats_flush_two_pairs_jack_top_pair(self):
        flush_pair_pair = _sug(
            "flush pair pair",
            ["2H", "3H", "4H", "6H", "TH"],
            ["4D", "8C", "9S", "KH", "KS"],
            ["JH", "JC", "AD"],
        )
        flush_two_pair_high_top = _sug(
            "flush two pair high top",
            ["2H", "3H", "4H", "6H", "TH"],
            ["8C", "9S", "JH", "KH", "KS"],
            ["4D", "JC", "AD"],
        )
        base = [dict(flush_pair_pair), dict(flush_two_pair_high_top)]
        final = [dict(flush_pair_pair), dict(flush_two_pair_high_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_flush_two_pair_ace_top_beats_flush_pair_jack_top_pair_render_variant(self):
        flush_pair_pair = _sug(
            "flush pair pair",
            ["2H", "3H", "4H", "6H", "TH"],
            ["4D", "8C", "9S", "KH", "KS"],
            ["JH", "JC", "AD"],
        )
        flush_two_pair_ace_top = _sug(
            "flush two pair ace top",
            ["2H", "3H", "6H", "TH", "KH"],
            ["4H", "4D", "8C", "JH", "JC"],
            ["9S", "KS", "AD"],
        )
        base = [dict(flush_two_pair_ace_top), dict(flush_pair_pair)]
        final = [dict(flush_two_pair_ace_top), dict(flush_pair_pair)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 0)
        self.assertTrue(final[0].get("_auto_opp_money"))
        self.assertFalse(final[1].get("_auto_opp_money"))

    def test_exact_hand_preference_is_hand_scoped(self):
        first = _sug(
            "first",
            ["2C", "2R", "4B", "5T", "6C"],
            ["7C", "8R", "9B", "TC", "JC"],
            ["QC", "KR", "AC"],
        )
        second = _sug(
            "second",
            ["2R", "2B", "4R", "4B", "6R"],
            ["7R", "7B", "9R", "TR", "JR"],
            ["QR", "QB", "AR"],
        )
        original = picker.EXACT_HAND_TEMPLATE_PREFERENCES
        try:
            picker.EXACT_HAND_TEMPLATE_PREFERENCES = (
                (picker._hand_key_from_suggestion(first), picker._template_key(first)),
            )
            base = [dict(first), dict(second)]
            final = [dict(first), dict(second)]

            idx = mark_auto_suggestion(base, final, policy="opp")

            self.assertEqual(idx, 0)
            self.assertTrue(final[0].get("_auto_opp_money"))
            self.assertFalse(final[1].get("_auto_opp_money"))
        finally:
            picker.EXACT_HAND_TEMPLATE_PREFERENCES = original

    def test_quads_two_pair_king_top_beats_quads_small_pair_pair(self):
        quads_small_pair_pair = _sug(
            "quads small pair pair",
            ["6D", "TD", "TH", "TS", "TC"],
            ["3H", "3S", "7S", "8C", "JC"],
            ["2S", "2C", "KD"],
        )
        quads_two_pair_king_top = _sug(
            "quads two pair king top",
            ["6D", "TD", "TH", "TS", "TC"],
            ["2S", "2C", "3H", "3S", "JC"],
            ["7S", "8C", "KD"],
        )
        base = [dict(quads_small_pair_pair), dict(quads_two_pair_king_top)]
        final = [dict(quads_small_pair_pair), dict(quads_two_pair_king_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_flush_pair_high_top_beats_weak_three_pairs(self):
        weak_three_pairs = _sug(
            "weak three pairs",
            ["2H", "3C", "5C", "KH", "KC"],
            ["6H", "6C", "8S", "TD", "JD"],
            ["4S", "4C", "QC"],
        )
        flush_pair_high_top = _sug(
            "flush pair high top",
            ["2H", "3C", "5C", "KH", "KC"],
            ["6H", "6C", "8S", "TD", "JD"],
            ["4S", "4C", "QC"],
        )
        # Make the alternative a real bottom flush while keeping a middle pair
        # and high-card top. The exact split shape is what the pairwise rule
        # is meant to choose over weak three pairs.
        flush_pair_high_top["chi1_codes"] = ["3C", "5C", "4C", "KC", "QC"]
        flush_pair_high_top["chi2_codes"] = ["6H", "6C", "8S", "TD", "JD"]
        flush_pair_high_top["chi3_codes"] = ["2H", "4S", "KH"]
        base = [dict(weak_three_pairs), dict(flush_pair_high_top)]
        final = [dict(weak_three_pairs), dict(flush_pair_high_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_flush_pair_ace_top_beats_weak_two_pair_pair_pair(self):
        weak_three_live = _sug(
            "weak two-pair pair pair",
            ["5H", "5S", "6C", "6D", "AC"],
            ["3C", "4C", "4D", "JC", "TH"],
            ["9D", "9S", "AH"],
        )
        flush_pair_ace_top = _sug(
            "flush pair ace top",
            ["3C", "4C", "6C", "JC", "AC"],
            ["4D", "5H", "5S", "6D", "9S"],
            ["9D", "TH", "AH"],
        )
        base = [dict(weak_three_live), dict(flush_pair_ace_top)]
        final = [dict(weak_three_live), dict(flush_pair_ace_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_flush_premium_pair_broadway_top_beats_tiny_top_three_pairs(self):
        flush_pair_broadway_top = _sug(
            "flush pair broadway top",
            ["2D", "AD", "8D", "QD", "3D"],
            ["2S", "4H", "6H", "KC", "KS"],
            ["TS", "JC", "QS"],
        )
        tiny_top_three_pairs = _sug(
            "tiny top three pairs",
            ["3D", "4H", "6H", "KC", "KS"],
            ["8D", "TS", "JC", "QD", "QS"],
            ["2D", "2S", "AD"],
        )
        base = [dict(flush_pair_broadway_top), dict(tiny_top_three_pairs)]
        final = [dict(flush_pair_broadway_top), dict(tiny_top_three_pairs)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 0)
        self.assertTrue(final[0].get("_auto_opp_money"))
        self.assertFalse(final[1].get("_auto_opp_money"))

    def test_big_full_house_ace_pair_high_top_beats_trips_ace_pair_top_pair(self):
        trips_ace_pair_top_pair = _sug(
            "trips ace pair top pair",
            ["JS", "JC", "JH", "2C", "4H"],
            ["5D", "5C", "6H", "8H", "TS"],
            ["AS", "AD", "QD"],
        )
        full_house_ace_pair_high_top = _sug(
            "full house ace pair high top",
            ["5D", "5C", "JS", "JC", "JH"],
            ["2C", "4H", "6H", "AS", "AD"],
            ["8H", "TS", "QD"],
        )

        base = [dict(trips_ace_pair_top_pair), dict(full_house_ace_pair_high_top)]
        final = [dict(trips_ace_pair_top_pair), dict(full_house_ace_pair_high_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_full_house_two_pair_high_top_beats_trips_two_pair_ace_pair(self):
        trips_two_pair_ace_pair = _sug(
            "trips two-pair ace pair",
            ["6D", "7C", "KH", "KS", "KC"],
            ["2H", "2C", "4S", "4C", "TH"],
            ["QH", "AD", "AS"],
        )
        full_house_two_pair_high_top = _sug(
            "full-house two-pair high top",
            ["2H", "2C", "KH", "KS", "KC"],
            ["4S", "4C", "AD", "AS", "7C"],
            ["6D", "TH", "QH"],
        )
        base = [dict(trips_two_pair_ace_pair), dict(full_house_two_pair_high_top)]
        final = [dict(trips_two_pair_ace_pair), dict(full_house_two_pair_high_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_full_house_big_pair_high_top_beats_trips_pair_small_top_pair(self):
        trips_pair_small_top_pair = _sug(
            "trips pair small top pair",
            ["2H", "5S", "6S", "6H", "6D"],
            ["7D", "TC", "QH", "QD", "KC"],
            ["4C", "4H", "AH"],
        )
        full_house_pair_high_top = _sug(
            "full-house pair high top",
            ["4C", "4H", "6S", "6H", "6D"],
            ["7D", "QH", "QD", "2H", "5S"],
            ["AH", "TC", "KC"],
        )
        base = [dict(trips_pair_small_top_pair), dict(full_house_pair_high_top)]
        final = [dict(trips_pair_small_top_pair), dict(full_house_pair_high_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_full_house_pair_ace_top_beats_straight_two_pair_ace_top(self):
        straight_two_pair_ace_top = _sug(
            "straight two-pair ace top",
            ["6H", "7D", "8H", "9H", "TH"],
            ["2D", "9S", "9C", "KD", "KC"],
            ["3S", "8S", "AD"],
        )
        full_house_pair_ace_top = _sug(
            "full-house pair ace top",
            ["9S", "9C", "9H", "KD", "KC"],
            ["2D", "6H", "7D", "8H", "8S"],
            ["3S", "TH", "AD"],
        )
        base = [dict(straight_two_pair_ace_top), dict(full_house_pair_ace_top)]
        final = [dict(straight_two_pair_ace_top), dict(full_house_pair_ace_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_full_house_ace_pair_king_top_beats_trips_two_pair_king_top(self):
        full_house_ace_pair_king_top = _sug(
            "full-house ace pair king top",
            ["3D", "3H", "3S", "JC", "JS"],
            ["2H", "5C", "8H", "AS", "AD"],
            ["9S", "TS", "KH"],
        )
        trips_two_pair_king_top = _sug(
            "trips two-pair king top",
            ["3D", "3H", "3S", "2H", "5C"],
            ["8H", "JC", "JS", "AS", "AD"],
            ["9S", "TS", "KH"],
        )
        base = [dict(full_house_ace_pair_king_top), dict(trips_two_pair_king_top)]
        final = [dict(full_house_ace_pair_king_top), dict(trips_two_pair_king_top)]

        idx = mark_auto_suggestion(base, final, policy="self")

        self.assertEqual(idx, 0)
        self.assertTrue(final[0].get("_auto_profile_money"))
        self.assertFalse(final[1].get("_auto_profile_money"))

    def test_full_house_two_pair_ace_top_beats_full_house_pair_small_top_pair(self):
        full_house_two_pair_ace_top = _sug(
            "full-house two-pair ace top",
            ["4C", "4H", "JD", "JC", "JH"],
            ["5H", "5D", "7D", "7S", "KS"],
            ["3S", "8H", "AC"],
        )
        full_house_pair_small_top_pair = _sug(
            "full-house pair small top pair",
            ["4C", "4H", "JD", "JC", "JH"],
            ["3S", "7D", "7S", "8H", "KS"],
            ["5H", "5D", "AC"],
        )
        base = [dict(full_house_two_pair_ace_top), dict(full_house_pair_small_top_pair)]
        final = [dict(full_house_two_pair_ace_top), dict(full_house_pair_small_top_pair)]

        idx = mark_auto_suggestion(base, final, policy="self")

        self.assertEqual(idx, 0)
        self.assertTrue(final[0].get("_auto_profile_money"))
        self.assertFalse(final[1].get("_auto_profile_money"))

    def test_flush_pair_ace_top_beats_medium_three_pairs(self):
        flush_pair_ace_top = _sug(
            "flush pair ace top",
            ["5S", "8S", "9S", "TS", "QS"],
            ["3D", "4H", "7D", "7H", "9H"],
            ["TD", "JH", "AC"],
        )
        medium_three_pairs = _sug(
            "medium three pairs",
            ["5S", "8S", "9S", "9H", "QS"],
            ["3D", "4H", "7D", "7H", "JH"],
            ["TS", "TD", "AC"],
        )
        base = [dict(medium_three_pairs), dict(flush_pair_ace_top)]
        final = [dict(medium_three_pairs), dict(flush_pair_ace_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_full_house_nine_pair_ace_top_beats_underpowered_bottom_pair_pair(self):
        underpowered_bottom_pair_pair = _sug(
            "underpowered bottom pair pair",
            ["3H", "4D", "5C", "7C", "9C"],
            ["2D", "3S", "3C", "9D", "4S"],
            ["JS", "KS", "AD"],
        )
        full_house_nine_pair_ace_top = _sug(
            "full-house nine pair ace top",
            ["3H", "3S", "3C", "4D", "4S"],
            ["2D", "5C", "7C", "9D", "9C"],
            ["JS", "KS", "AD"],
        )
        base = [dict(underpowered_bottom_pair_pair), dict(full_house_nine_pair_ace_top)]
        final = [dict(underpowered_bottom_pair_pair), dict(full_house_nine_pair_ace_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_full_house_live_middle_ace_top_beats_flush_two_pair_ace_top(self):
        flush_two_pair_ace_top = _sug(
            "flush two-pair ace top",
            ["3H", "7H", "8H", "TH", "QH"],
            ["2D", "2C", "3D", "3C", "4S"],
            ["7D", "QC", "AC"],
        )
        full_house_pair_ace_top = _sug(
            "full-house pair ace top",
            ["2D", "2C", "3D", "3C", "3H"],
            ["7D", "7H", "8H", "TH", "QH"],
            ["4S", "QC", "AC"],
        )
        base = [dict(flush_two_pair_ace_top), dict(full_house_pair_ace_top)]
        final = [dict(flush_two_pair_ace_top), dict(full_house_pair_ace_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_same_full_house_prefers_middle_trips_over_small_pair_with_ace_top(self):
        full_house_pair_ace_top = _sug(
            "full-house pair ace top",
            ["JH", "JS", "QH", "QS", "QC"],
            ["2S", "3D", "3S", "7D", "8D"],
            ["3C", "TS", "AC"],
        )
        full_house_trips_ace_top = _sug(
            "full-house trips ace top",
            ["JH", "JS", "QH", "QS", "QC"],
            ["2S", "3D", "3S", "3C", "7D"],
            ["8D", "TS", "AC"],
        )
        base = [dict(full_house_pair_ace_top), dict(full_house_trips_ace_top)]
        final = [dict(full_house_pair_ace_top), dict(full_house_trips_ace_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))

    def test_full_house_flush_middle_beats_full_house_trips_middle_with_ace_top(self):
        full_house_trips_ace_top = _sug(
            "full-house trips ace top",
            ["8D", "8H", "8S", "9D", "9S"],
            ["4D", "6S", "JH", "JS", "JC"],
            ["2D", "QH", "AC"],
        )
        full_house_flush_ace_top = _sug(
            "full-house flush ace top",
            ["8D", "8H", "8S", "9D", "9S"],
            ["4H", "6H", "9H", "JH", "QH"],
            ["2D", "JC", "AC"],
        )
        base = [dict(full_house_trips_ace_top), dict(full_house_flush_ace_top)]
        final = [dict(full_house_trips_ace_top), dict(full_house_flush_ace_top)]

        idx = mark_auto_suggestion(base, final, policy="opp")

        self.assertEqual(idx, 1)
        self.assertTrue(final[1].get("_auto_opp_money"))
        self.assertFalse(final[0].get("_auto_opp_money"))


if __name__ == "__main__":
    unittest.main()
