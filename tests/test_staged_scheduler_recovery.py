import queue
import unittest

from ui2.tabs.strategy2.modules.staged_scheduler import StagedScheduler


class _Pipeline:
    def build_snapshot(self, *, codes_slot_order, ngu_codes13):
        snapshot = {
            pid: list(codes)
            for pid, codes in (codes_slot_order or {}).items()
            if len(codes or []) == 13
        }
        if ngu_codes13 and len(ngu_codes13) == 13:
            snapshot["NGU"] = list(ngu_codes13)
        ordered = []
        if "NGU" in snapshot:
            ordered.append("NGU")
        ordered.extend([pid for pid in ("P1", "P2", "P3") if pid in snapshot])
        return type("Snapshot", (), {"snapshot": snapshot, "ordered_keys": ordered})()


class _View:
    def set_p_status(self, _text):
        pass

    def set_ngu_status(self, _text):
        pass

    def set_ngu_labels(self, *_args):
        pass


class _Tab:
    profiles = ["P1", "P2", "P3"]
    active_profile = "P1"
    MAX_UI_NGU_ITEMS = 3

    def __init__(self):
        self._pipeline = _Pipeline()
        self._codes_slot_order = {pid: [] for pid in self.profiles}
        self._ngu_base_codes = []
        self._scheduled_hash = {pid: None for pid in self.profiles + ["NGU"]}
        self._q = queue.Queue()
        self.view = _View()
        self._suggestions = {pid: [] for pid in self.profiles}
        self._suggestions_render = {pid: [] for pid in self.profiles}
        self._selected_index = {pid: 0 for pid in self.profiles}
        self._ngu_suggestions = []
        self._ngu_selected_index = 0

    def _hand_hash(self, codes):
        return "|".join(sorted(codes or []))

    def _derive_ngu_from_3p(self):
        return None

    def build_suggestions_for_codes(self, key, codes):
        return [{"mode": "money", "chi1_codes": codes[:5], "chi2_codes": codes[5:10], "chi3_codes": codes[10:]}]

    def _filter_extras(self, full):
        return list(full or [])

    def _pre_render_profile(self, _key):
        pass

    def _rebuild_ngu_labels_html(self):
        pass

    def _render_ngu(self):
        pass

    def _render_p_active(self):
        pass

    def _maybe_run_auto_play(self):
        pass

    def _is_special_row(self, _s):
        return False

    def _make_split_key(self, _s):
        return "split"

    def pick_default_suggestion(self, suggs):
        return 0 if suggs else -1


def _cards(prefix):
    ranks = "23456789TJQKA"
    suits = "CBRT"
    return [f"{r}{suits[(i + len(prefix)) % 4]}" for i, r in enumerate(ranks)]


class StagedSchedulerRecoveryTests(unittest.TestCase):
    def test_reenqueue_dropped_queued_job_during_ws_burst(self):
        tab = _Tab()
        scheduler = StagedScheduler()
        tab._codes_slot_order["P1"] = _cards("p1")
        tab._codes_slot_order["P2"] = _cards("p2")

        h2 = tab._hand_hash(tab._codes_slot_order["P2"])
        scheduler.job_running = True
        scheduler.job_q.append(("P2", "EXTRA", "ALL", h2, list(tab._codes_slot_order["P2"])))
        tab._scheduled_hash["P1"] = tab._hand_hash(tab._codes_slot_order["P1"])
        tab._scheduled_hash["P2"] = h2

        tab._codes_slot_order["P3"] = _cards("p3")
        scheduler.enqueue_batch_jobs(tab)

        queued_keys = [item[0] for item in scheduler.job_q]
        self.assertIn("P2", queued_keys)
        self.assertIn("P3", queued_keys)

    def test_empty_worker_result_releases_scheduled_hash_for_retry(self):
        tab = _Tab()
        scheduler = StagedScheduler()
        tab._codes_slot_order["P1"] = _cards("p1")
        h1 = tab._hand_hash(tab._codes_slot_order["P1"])
        tab._scheduled_hash["P1"] = h1
        scheduler.job_running = True
        tab._q.put(("P1", None, [], None, "EXTRA", "ALL", h1))

        scheduler.poll_suggest_results(tab)

        self.assertIsNone(tab._scheduled_hash["P1"])


if __name__ == "__main__":
    unittest.main()
