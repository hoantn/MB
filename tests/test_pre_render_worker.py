import unittest

from ui2.tabs.strategy2.modules.pre_render_worker import (
    PreRenderSnapshot,
    apply_auto_mark_plan,
    run_pre_render_snapshot,
)


def _money_suggestion():
    return {
        "mode": "money",
        "chi1_codes": ["2T", "3T", "4T", "5T", "6T"],
        "chi2_codes": ["7B", "8B", "9B", "TB", "JB"],
        "chi3_codes": ["QC", "KC", "AC"],
    }


class PreRenderWorkerTests(unittest.TestCase):
    def test_worker_marks_auto_and_builds_label_html(self):
        snapshot = PreRenderSnapshot(
            pid="P1",
            request_id=1,
            signature=("sig",),
            profiles=("P1", "P2", "P3"),
            suggestions={"P1": [_money_suggestion()], "P2": [], "P3": []},
            suggestions_render={"P1": [], "P2": [], "P3": []},
            selected_index={"P1": 0, "P2": 0, "P3": 0},
            codes_slot_order={"P1": [], "P2": [], "P3": []},
            ngu_suggestions=[],
            ngu_selected_index=0,
            ngu_clicked_once=False,
            anti_sap_enabled=False,
            max_ui_p_items=12,
            special_mode="__special13__",
        )

        result = run_pre_render_snapshot(snapshot)

        self.assertIsNone(result.error)
        self.assertEqual(result.selected_index, 0)
        self.assertEqual(len(result.suggestions_render), 1)
        self.assertTrue(result.suggestions_render[0].get("_auto_profile_money"))
        self.assertIn("[auto]", result.suggestions_render[0].get("label_html", ""))

    def test_commit_plan_marks_base_without_recomputing_picker(self):
        base = [_money_suggestion()]
        snapshot = PreRenderSnapshot(
            pid="P1",
            request_id=1,
            signature=("sig",),
            profiles=("P1", "P2", "P3"),
            suggestions={"P1": [_money_suggestion()], "P2": [], "P3": []},
            suggestions_render={"P1": [], "P2": [], "P3": []},
            selected_index={"P1": 0, "P2": 0, "P3": 0},
            codes_slot_order={"P1": [], "P2": [], "P3": []},
            ngu_suggestions=[],
            ngu_selected_index=0,
            ngu_clicked_once=False,
            anti_sap_enabled=False,
            max_ui_p_items=12,
            special_mode="__special13__",
        )
        result = run_pre_render_snapshot(snapshot)
        final = [dict(item) for item in result.suggestions_render]

        idx = apply_auto_mark_plan(base, final, result.auto_mark_plan)

        self.assertEqual(idx, 0)
        self.assertTrue(base[0].get("_auto_profile_money"))
        self.assertTrue(final[0].get("_auto_profile_money"))
        self.assertEqual(final[0].get("_auto_choice_source"), "engine_money")


if __name__ == "__main__":
    unittest.main()
