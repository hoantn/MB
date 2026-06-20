import unittest

from ui2.tabs.strategy2.modules.auto_plan_worker import (
    AutoOppPlanSnapshot,
    run_auto_opp_plan_snapshot,
)
from ui2.tabs.strategy2.modules.auto_play_controller import PROFILES, build_auto_play_plan


def _sug(c1, c2, c3, *, auto=False):
    item = {
        "mode": "money" if auto else "normal",
        "chi1_codes": list(c1),
        "chi2_codes": list(c2),
        "chi3_codes": list(c3),
    }
    if auto:
        item["_auto_profile_money"] = True
    return item


P_SUGGESTIONS = {
    "P1": _sug(
        ["TB", "JB", "QB", "KB", "AB"],
        ["KC", "KR", "2C", "3R", "4T"],
        ["QC", "QR", "5B"],
        auto=True,
    ),
    "P2": _sug(
        ["KC", "KR", "2T", "3T", "4T"],
        ["QC", "QR", "5T", "6T", "7T"],
        ["JC", "JR", "8T"],
        auto=True,
    ),
    "P3": _sug(
        ["9B", "9C", "2R", "3C", "4B"],
        ["8B", "8C", "5R", "6C", "7B"],
        ["AC", "AR", "2C"],
        auto=True,
    ),
}

OPP = _sug(
    ["KC", "KR", "KB", "QC", "QR"],
    ["QB", "JC", "JR", "JT", "TC"],
    ["AC", "AR", "2C"],
)
OPP["_auto_opp_money"] = True


class _SyncTab:
    def __init__(self, *, applied_keys=()):
        self._suggestions = {pid: [dict(P_SUGGESTIONS[pid])] for pid in PROFILES}
        self._suggestions_render = {pid: [] for pid in PROFILES}
        self._codes_slot_order = {
            pid: (
                self._suggestions[pid][0]["chi1_codes"]
                + self._suggestions[pid][0]["chi2_codes"]
                + self._suggestions[pid][0]["chi3_codes"]
            )
            for pid in PROFILES
        }
        self._hand_generation = {pid: 1 for pid in PROFILES}
        self._ngu_suggestions = [dict(OPP)]
        self._auto_play_applied_profile_keys = set(applied_keys)
        self._anti_sap_enabled = False

    def _is_special_row(self, _item):
        return False

    def _auto_profile_apply_key(self, pid):
        cards = list(self._codes_slot_order.get(pid) or [])
        generation = int(self._hand_generation.get(pid, 0) or 0)
        return f"{pid}:g{generation}:{','.join(sorted(map(str, cards)))}"

    def _build_render_suggestions(self, base_suggs, _opp):
        return list(base_suggs or [])


def _snapshot(tab, *, applied_keys=()):
    return AutoOppPlanSnapshot(
        request_id=1,
        signature=("sig",),
        session=7,
        hand_key="hand",
        room_context_key="room",
        suggestions={pid: [dict(tab._suggestions[pid][0])] for pid in PROFILES},
        suggestions_render={pid: [] for pid in PROFILES},
        codes_slot_order={pid: list(tab._codes_slot_order[pid]) for pid in PROFILES},
        hand_generation=dict(tab._hand_generation),
        ngu_suggestions=[dict(OPP)],
        applied_profile_keys=tuple(applied_keys),
        anti_sap_enabled=False,
        allow_intentional_foul=False,
        special_mode="__special13__",
    )


class AutoPlanWorkerTests(unittest.TestCase):
    def test_external_opp_worker_matches_sync_plan(self):
        tab = _SyncTab()
        expected = build_auto_play_plan(tab, allow_intentional_foul=False)

        result = run_auto_opp_plan_snapshot(_snapshot(tab))

        self.assertIsNone(result.error)
        self.assertIsNotNone(result.plan)
        self.assertEqual(result.plan.kind, expected.kind)
        self.assertEqual(result.plan.score, expected.score)
        self.assertEqual(result.plan.selected_index, expected.selected_index)
        self.assertEqual(set(result.plan.suggestions), set(expected.suggestions))
        for pid in PROFILES:
            self.assertEqual(
                result.plan.suggestions[pid]["chi1_codes"],
                expected.suggestions[pid]["chi1_codes"],
            )

    def test_external_opp_worker_respects_applied_profile_keys(self):
        tab = _SyncTab()
        applied = (tab._auto_profile_apply_key("P1"),)
        tab = _SyncTab(applied_keys=applied)

        result = run_auto_opp_plan_snapshot(_snapshot(tab, applied_keys=applied))

        self.assertIsNone(result.error)
        self.assertIsNotNone(result.plan)
        self.assertEqual(result.plan.kind, "partial")
        self.assertNotIn("P1", result.plan.suggestions)
        self.assertIn("P2", result.plan.suggestions)
        self.assertIn("P3", result.plan.suggestions)


if __name__ == "__main__":
    unittest.main()
