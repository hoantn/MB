import unittest

from ui2.tabs.strategy2.modules.auto_play_controller import (
    AutoPlayPlan,
    _build_intentional_foul_plan,
    _opp_has_bonus_line,
)


PROFILES = ("P1", "P2", "P3")


def _sug(c1, c2, c3, *, money=False):
    out = {
        "mode": "money" if money else "normal",
        "chi1_codes": list(c1),
        "chi2_codes": list(c2),
        "chi3_codes": list(c3),
    }
    if money:
        out["_auto_profile_money"] = True
    return out


WEAK_SWEPT = _sug(
    ["KC", "KR", "2T", "3T", "4T"],
    ["QC", "QR", "5T", "6T", "7T"],
    ["JC", "JR", "8T"],
    money=True,
)

ESCAPES = _sug(
    ["TB", "JB", "QB", "KB", "AB"],
    ["KC", "KR", "2C", "3R", "4T"],
    ["QC", "QR", "5B"],
    money=True,
)

OPP_WITH_BONUS = _sug(
    ["9B", "TB", "JB", "QB", "KB"],  # straight flush
    ["7C", "7R", "7B", "7T", "2C"],  # quads
    ["AC", "AR", "AB"],  # trips on top
)

OPP_NO_BONUS = _sug(
    ["KC", "KR", "KB", "QC", "QR"],  # full house
    ["QB", "JC", "JR", "JT", "TC"],  # full house
    ["AC", "AR", "2C"],  # pair
)


class _Tab:
    def __init__(self, suggestions):
        self._suggestions = {
            pid: [dict(suggestions.get(pid, WEAK_SWEPT))]
            for pid in PROFILES
        }
        self._codes_slot_order = {
            pid: (
                self._suggestions[pid][0]["chi1_codes"]
                + self._suggestions[pid][0]["chi2_codes"]
                + self._suggestions[pid][0]["chi3_codes"]
            )
            for pid in PROFILES
        }

    def _is_special_row(self, _sug):
        return False


def _normal_plan(suggestions):
    return AutoPlayPlan(
        kind="normal",
        opp_index=0,
        score=(0, 0, 0, 0),
        selected_index={pid: 0 for pid in PROFILES},
        suggestions={pid: dict(suggestions.get(pid, WEAK_SWEPT)) for pid in PROFILES},
    )


class AutoIntentionalFoulPlanTests(unittest.TestCase):
    def test_detects_opp_bonus_lines(self):
        self.assertTrue(_opp_has_bonus_line(OPP_WITH_BONUS))
        self.assertFalse(_opp_has_bonus_line(OPP_NO_BONUS))

    def test_bonus_opp_fouls_only_profiles_that_cannot_escape(self):
        suggestions = {"P1": WEAK_SWEPT, "P2": WEAK_SWEPT, "P3": ESCAPES}
        plan = _build_intentional_foul_plan(
            _Tab(suggestions),
            opp_index=0,
            opp=OPP_WITH_BONUS,
            normal_plan=_normal_plan(suggestions),
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan.kind, "intentional_foul")
        self.assertEqual(set(plan.report_binh_pids), {"P1", "P2"})
        self.assertTrue(plan.suggestions["P1"].get("_auto_intentional_foul"))
        self.assertTrue(plan.suggestions["P2"].get("_auto_intentional_foul"))
        self.assertFalse(plan.suggestions["P3"].get("_auto_intentional_foul", False))
        self.assertEqual(plan.suggestions["P3"]["chi1_codes"], ESCAPES["chi1_codes"])

    def test_no_bonus_opp_does_not_foul_partial_sweep(self):
        suggestions = {"P1": WEAK_SWEPT, "P2": WEAK_SWEPT, "P3": ESCAPES}
        plan = _build_intentional_foul_plan(
            _Tab(suggestions),
            opp_index=0,
            opp=OPP_NO_BONUS,
            normal_plan=_normal_plan(suggestions),
        )
        self.assertIsNone(plan)

    def test_all_profiles_swept_fouls_all_even_without_bonus(self):
        suggestions = {"P1": WEAK_SWEPT, "P2": WEAK_SWEPT, "P3": WEAK_SWEPT}
        plan = _build_intentional_foul_plan(
            _Tab(suggestions),
            opp_index=0,
            opp=OPP_NO_BONUS,
            normal_plan=_normal_plan(suggestions),
        )

        self.assertIsNotNone(plan)
        self.assertEqual(set(plan.report_binh_pids), set(PROFILES))
        self.assertTrue(all(plan.suggestions[pid].get("_auto_intentional_foul") for pid in PROFILES))


if __name__ == "__main__":
    unittest.main()
