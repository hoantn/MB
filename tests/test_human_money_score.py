import unittest

from core.constants import RANK_ORDER
from engine.card import Card
from engine.rules import evaluate_5cards
from engine.scorer import evaluate_3cards
from engine.arranger_parts.arrange import (
    arrange_13_cards,
    arrange_cache_clear,
    arrange_cached_money_split,
)
from ui2.tabs.strategy2.auto_suggestion_picker import mark_auto_suggestion, split_key
from ui2.tabs.strategy2.strategy_suggest_worker import build_suggestions_for_codes


def _cards(codes):
    return [Card.from_code(code) for code in codes]


def _money_for_codes(codes):
    arrange_cache_clear()
    arrange_13_cards(_cards(codes), max_candidates=None)
    money = arrange_cached_money_split(_cards(codes))
    if money is None:
        raise AssertionError("Money split was not cached")
    return money


def _money_types(codes):
    chi1, chi2, chi3 = _money_for_codes(codes)
    return (
        evaluate_5cards(chi1)[0],
        evaluate_5cards(chi2)[0],
        evaluate_3cards(chi3)[0],
    )


class HumanMoneyScoreTests(unittest.TestCase):
    def test_five_pair_like_hand_prefers_balanced_two_pair_two_pair_pair(self):
        # This hand can make a diamond flush, but that leaves middle/top as mau.
        # Human-style Money should prefer live force on all three chi.
        codes = [
            "9C", "TC", "KT",
            "3C", "5B", "6T", "7C", "AB",
            "6R", "9R", "TR", "KR", "AR",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 2)  # two pair
        self.assertEqual(evaluate_5cards(chi2)[0], 2)  # two pair
        self.assertEqual(evaluate_3cards(chi3)[0], 1)  # pair

    def test_full_house_pair_high_card_beats_trips_two_pair_high_card(self):
        # A human keeps the bottom full house here. Breaking it into trips just
        # to make chi2 two-pair is not worth it when chi3 remains high-card.
        codes = [
            "2T", "4C", "5B", "6T", "8R", "8C", "9C",
            "9B", "9T", "TR", "JR", "JT", "KC",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 6)  # full house
        self.assertEqual(evaluate_5cards(chi2)[0], 1)  # one pair
        self.assertEqual(evaluate_3cards(chi3)[0], 0)  # high-card

    def test_full_house_straight_high_card_beats_straight_trips_small_pair(self):
        # Do not sacrifice full-house + straight just to keep a small top pair.
        codes = [
            "5R", "5C", "8B", "3B", "4T", "6R", "6B",
            "6T", "8R", "9C", "TR", "JC", "QR",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 6)  # full house
        self.assertEqual(evaluate_5cards(chi2)[0], 4)  # straight
        self.assertEqual(evaluate_3cards(chi3)[0], 0)  # high-card

    def test_premium_top_pair_can_compete_with_full_house_straight_anchor(self):
        # Same structure, but top pair A is valuable enough to keep.
        codes = [
            "AR", "AC", "8B", "3B", "4T", "6R", "6B",
            "6T", "8R", "9C", "TR", "JC", "QR",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        _chi1, _chi2, chi3 = money
        self.assertEqual(evaluate_3cards(chi3)[0], 1)  # pair
        self.assertEqual(evaluate_3cards(chi3)[1][0], 12)  # aces

    def test_flush_trips_pair_king_beats_full_house_flush_high_card(self):
        # Three live chi with a premium top pair should beat full-house + flush
        # when the full-house line leaves chi3 dead.
        codes = [
            "JR", "KB", "KT", "2R", "3R", "3C", "3T",
            "4T", "4C", "5C", "7C", "8C", "QC",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 5)  # flush
        self.assertEqual(evaluate_5cards(chi2)[0], 3)  # trips
        self.assertEqual(evaluate_3cards(chi3)[0], 1)  # pair
        self.assertEqual(evaluate_3cards(chi3)[1][0], 11)  # kings

    def test_flush_pair_pair_jack_beats_full_house_pair_high_card(self):
        # Flush + pair + top pair J is a stronger three-live-chi layout than
        # keeping full-house while leaving chi3 high-card.
        codes = [
            "JB", "JT", "KR", "2C", "8B", "9R", "QC",
            "QB", "3T", "4T", "7T", "9T", "QT",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 5)  # flush
        self.assertEqual(evaluate_5cards(chi2)[0], 1)  # one pair
        self.assertEqual(evaluate_3cards(chi3)[0], 1)  # pair
        self.assertEqual(evaluate_3cards(chi3)[1][0], 9)  # jacks

    def test_flush_pair_pair_queen_is_preferred_as_three_live_chi(self):
        # With a Q/K/A top pair, flush-pair-pair should stay ahead of dead
        # top-card alternatives.
        codes = [
            "2R", "4R", "6R", "8R", "TR", "AR", "AC",
            "QB", "QT", "7T", "9C", "JB", "KB",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 5)  # flush
        self.assertEqual(evaluate_5cards(chi2)[0], 1)  # one pair
        self.assertEqual(evaluate_3cards(chi3)[0], 1)  # pair
        self.assertEqual(evaluate_3cards(chi3)[1][0], 10)  # queens

    def test_ace_high_flush_pair_pair_beats_small_full_house_pair_high_card(self):
        codes = [
            "TR", "KC", "AC", "4C", "6B", "7T", "JB",
            "JT", "2R", "2C", "5R", "5C", "5T",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 5)  # flush
        self.assertEqual(evaluate_5cards(chi2)[0], 1)  # one pair
        self.assertEqual(evaluate_3cards(chi3)[0], 1)  # pair

    def test_trips_on_top_bonus_beats_full_house_flush_pair(self):
        codes = [
            "7B", "AC", "AT", "4T", "6T", "7T", "9T",
            "KT", "6C", "6B", "8R", "8C", "8B",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 5)  # flush
        self.assertEqual(evaluate_5cards(chi2)[0], 3)  # trips
        self.assertEqual(evaluate_3cards(chi3)[0], 2)  # trips

    def test_full_house_pair_pair_beats_trips_two_pair_pair(self):
        codes = [
            "QC", "AC", "AB", "3R", "3C", "9C", "9T",
            "JB", "2T", "6T", "TR", "TC", "TT",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 6)  # full house
        self.assertEqual(evaluate_5cards(chi2)[0], 1)  # one pair
        self.assertEqual(evaluate_3cards(chi3)[0], 1)  # pair

    def test_full_house_pair_pair_second_shape_beats_trips_two_pair_pair(self):
        codes = [
            "KT", "AR", "AC", "3C", "3B", "6C", "6B",
            "TT", "5B", "7C", "7B", "7T", "8T",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 6)  # full house
        self.assertEqual(evaluate_5cards(chi2)[0], 1)  # one pair
        self.assertEqual(evaluate_3cards(chi3)[0], 1)  # pair

        sugg = build_suggestions_for_codes("NGU", codes)
        self.assertTrue(sugg)
        self.assertFalse(any(s.get("mode") == "money" for s in sugg))
        final = list(sugg[:5])
        selected = mark_auto_suggestion(sugg, final, policy="opp")
        self.assertGreaterEqual(selected, 0)
        auto = final[selected]
        self.assertTrue(auto.get("_auto_opp_money"))
        self.assertIn(split_key(auto), {split_key(s) for s in sugg})

    def test_flush_trips_high_card_beats_small_full_house_pair_high_card(self):
        codes = [
            "TT", "QR", "KC", "2C", "3T", "7T", "JC",
            "JT", "5R", "5B", "5T", "8C", "8T",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 5)  # flush
        self.assertEqual(evaluate_5cards(chi2)[0], 3)  # trips
        self.assertEqual(evaluate_3cards(chi3)[0], 0)  # high-card

    def test_straight_pair_ace_pair_beats_straight_two_pair_high_card(self):
        codes = [
            "4B", "JT", "KB", "3C", "5R", "5T", "AC",
            "AB", "7T", "8T", "9B", "TR", "JR",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 4)  # straight
        self.assertEqual(evaluate_5cards(chi2)[0], 1)  # one pair
        self.assertEqual(evaluate_5cards(chi2)[1][0], 12)  # aces
        self.assertEqual(evaluate_3cards(chi3)[0], 1)  # pair

    def test_straight_two_pair_high_card_beats_small_pair_pair(self):
        codes = [
            "6T", "7C", "AR", "2R", "4R", "4C", "5C",
            "5T", "9C", "TT", "JT", "QB", "KT",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 4)  # straight
        self.assertEqual(evaluate_5cards(chi2)[0], 2)  # two pair
        self.assertEqual(evaluate_3cards(chi3)[0], 0)  # high-card

    def test_two_pair_two_pair_high_card_beats_small_top_pair_line(self):
        codes = [
            "7B", "7T", "AB", "9C", "TC", "JC", "JT",
            "KT", "2B", "2T", "4C", "4T", "6B",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 2)  # two pair
        self.assertEqual(evaluate_5cards(chi2)[0], 2)  # two pair
        self.assertEqual(evaluate_3cards(chi3)[0], 0)  # high-card

    def test_two_straights_pair_beats_full_house_straight_high_card(self):
        codes = [
            "3B", "4R", "6R", "8T", "9B", "TB", "JR",
            "QT", "5R", "5C", "5B", "7R", "7B",
        ]
        arrange_cache_clear()
        arrange_13_cards(_cards(codes), max_candidates=None)
        money = arrange_cached_money_split(_cards(codes))
        self.assertIsNotNone(money)
        chi1, chi2, chi3 = money
        self.assertEqual(evaluate_5cards(chi1)[0], 4)  # straight
        self.assertEqual(evaluate_5cards(chi2)[0], 4)  # straight
        self.assertEqual(evaluate_3cards(chi3)[0], 1)  # pair

    def test_two_made_chi_high_card_is_kept_when_suits_make_it_stronger(self):
        # The reference photo was marked straight-straight-mau; with this exact
        # suit mapping, the same strategic class becomes flush-flush-mau.
        codes = [
            "JR", "JB", "AR", "2R", "TC", "QC", "KR",
            "KC", "3C", "4R", "5C", "6B", "7T",
        ]
        t1, t2, t3 = _money_types(codes)
        self.assertIn(t1, (4, 5))
        self.assertIn(t2, (4, 5))
        self.assertEqual(t3, 0)

    def test_two_straights_high_card_reference_shape(self):
        codes = [
            "JC", "JB", "AB", "2B", "TT", "QR", "QT",
            "KR", "3B", "4C", "5R", "6R", "7T",
        ]
        self.assertEqual(_money_types(codes), (4, 4, 0))

    def test_flush_two_pair_high_card_beats_flush_pair_pair_when_top_pair_is_small(self):
        codes = [
            "7B", "7T", "AT", "5R", "8B", "JC", "JB",
            "QT", "2C", "3C", "5C", "6C", "KC",
        ]
        self.assertEqual(_money_types(codes), (5, 2, 0))

    def test_two_pair_pair_pair_beats_two_pair_two_pair_dead_top_when_live_chi_are_useful(self):
        codes = [
            "8R", "9C", "QC", "2C", "4T", "6R", "6T",
            "7T", "2B", "3B", "7B", "8B", "TB",
        ]
        self.assertEqual(_money_types(codes), (2, 1, 1))

    def test_strong_full_house_pair_pair_stays_ahead_of_flush_pair_pair(self):
        codes = [
            "JT", "KR", "KT", "4R", "6R", "TR", "AC",
            "AT", "4B", "5B", "TB", "QB", "KB",
        ]
        self.assertEqual(_money_types(codes), (6, 1, 1))

    def test_two_flushes_high_card_reference_shape(self):
        codes = [
            "5R", "5C", "QR", "2R", "7B", "JR", "KR",
            "KC", "3C", "4C", "9C", "TC", "AC",
        ]
        self.assertEqual(_money_types(codes), (5, 5, 0))

    def test_flush_straight_high_card_reference_shape(self):
        codes = [
            "4B", "4T", "AT", "3B", "5T", "6C", "6T",
            "7B", "5R", "6R", "TR", "JR", "KR",
        ]
        self.assertEqual(_money_types(codes), (5, 4, 0))

    def test_flush_two_pair_pair_beats_full_house_pair_pair_when_full_house_is_not_premium(self):
        codes = [
            "6R", "6B", "KC", "3C", "8C", "QB", "AR",
            "AC", "2R", "2B", "JR", "JC", "JB",
        ]
        self.assertEqual(_money_types(codes), (5, 2, 1))

    def test_same_straight_two_pair_anchor_prefers_live_top_pair(self):
        # If chi1 remains straight and chi2 remains two-pair, a human-style
        # Money choice should not leave chi3 dead when a top pair is available.
        codes = [
            "2T", "7R", "JT", "2B", "3C", "3T", "4B",
            "4T", "TR", "JB", "QC", "KT", "AR",
        ]
        self.assertEqual(_money_types(codes), (4, 2, 1))

    def test_same_template_keeps_higher_bottom_straight_before_trash(self):
        # Same Sảnh-Đôi-Đôi template has both 7-J and 8-Q straights. The
        # representative must keep the stronger bottom straight instead of
        # moving Q out only as a kicker/trash card.
        codes = [
            "3R", "3B", "KC", "4T", "6R", "6T", "TC",
            "QB", "7R", "8C", "9B", "TB", "JC",
        ]
        arrange_cache_clear()
        suggs = build_suggestions_for_codes("NGU_STRAIGHT_OVERFLOW", codes)
        target = None
        for s in suggs:
            if "Sảnh" in s.get("label", "") and "Đôi" in s.get("label", ""):
                target = s
                break
        self.assertIsNotNone(target)
        chi1 = [Card.from_code(c) for c in target["chi1_codes"]]
        hand_type, detail = evaluate_5cards(chi1)
        self.assertEqual(hand_type, 4)
        self.assertGreaterEqual(detail[0], RANK_ORDER.index("Q"))

    def test_same_template_allows_lower_flush_when_it_improves_top_pair(self):
        # Same Thung-Doi-Doi template has two Q-high flush variants. The
        # representative should allow 5S inside the flush to free TS and improve
        # chi3 from pair 5 to pair T. This is a real hand-rank gain, not trash.
        codes = [
            "5H", "5S", "TD", "2C", "7D", "8H", "9H",
            "9C", "3S", "4S", "6S", "TS", "QS",
        ]
        arrange_cache_clear()
        reps = arrange_13_cards(_cards(codes), max_candidates=None)
        target = None
        for chi1, chi2, chi3 in reps:
            if (
                evaluate_5cards(chi1)[0] == 5
                and evaluate_5cards(chi2)[0] == 1
                and evaluate_3cards(chi3)[0] == 1
            ):
                target = (chi1, chi2, chi3)
                break
        self.assertIsNotNone(target)
        chi1, chi2, chi3 = target
        self.assertIn("5S", [c.code for c in chi1])
        self.assertNotIn("TS", [c.code for c in chi1])
        pair_ranks = [
            evaluate_5cards(chi2)[1][0],
            evaluate_3cards(chi3)[1][0],
        ]
        self.assertIn(RANK_ORDER.index("T"), pair_ranks)

    def test_multi_pair_full_house_line_keeps_live_top_pair(self):
        # Many-pair/xam hands need post-money distribution: keep the full-house
        # anchor, but still preserve a real top pair when available.
        codes = [
            "6R", "AC", "AB", "3T", "4R", "4T", "KR",
            "KB", "5R", "5B", "5T", "8C", "8T",
        ]
        self.assertEqual(_money_types(codes), (6, 2, 1))


if __name__ == "__main__":
    unittest.main()
