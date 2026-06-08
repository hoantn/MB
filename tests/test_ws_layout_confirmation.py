import threading
import time
import unittest

from engine.ws_card_mapping import ws_codes_to_cards, ws_codes_to_tool_slot_order
from ui2.bridge.ws_layout_store import WSLayoutStore, layout606_to_slot_order
from ui2.tabs.strategy2.modules.apply_confirmation import confirm_and_repair_layout


class WSLayoutStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = WSLayoutStore()
        self.original = list(range(13))
        self.store.begin_hand("P1", self.original)

    def test_rejects_layout_from_another_hand(self):
        self.assertIsNone(self.store.update_layout("P1", list(range(13, 26))))

    def test_stale_snapshot_cannot_confirm_new_drag(self):
        old = self.store.update_layout("P1", self.original, event_at=10.0)
        self.assertIsNotNone(old)
        self.assertIsNone(
            self.store.wait_for_newer(
                "P1",
                after_sequence=old.sequence,
                after_event_at=11.0,
                timeout_s=0.01,
            )
        )

    def test_snapshot_during_drag_cannot_confirm_after_drag(self):
        during_drag = self.store.update_layout("P1", self.original, event_at=10.0)
        self.assertIsNone(
            self.store.wait_for_newer(
                "P1",
                after_sequence=0,
                after_event_at=11.0,
                timeout_s=0.01,
            )
        )
        self.assertIsNotNone(during_drag)

    def test_same_layout_new_heartbeat_can_confirm(self):
        old = self.store.update_layout("P1", self.original, event_at=10.0)
        new = self.store.update_layout("P1", self.original, event_at=12.0)
        found = self.store.wait_for_newer(
            "P1",
            after_sequence=old.sequence,
            after_event_at=11.0,
            timeout_s=0.01,
        )
        self.assertEqual(found.sequence, new.sequence)

    def test_new_hand_cancels_wait_for_old_generation(self):
        generation = self.store.hand_generation("P1")
        self.store.begin_hand("P1", list(range(13, 26)))
        started = time.monotonic()
        self.assertIsNone(
            self.store.wait_for_newer(
                "P1",
                after_sequence=0,
                after_event_at=0.0,
                timeout_s=1.0,
                expected_hand_generation=generation,
            )
        )
        self.assertLess(time.monotonic() - started, 0.1)

    def test_profiles_are_independent(self):
        p2 = list(range(13, 26))
        self.store.begin_hand("P2", p2)
        snap1 = self.store.update_layout("P1", self.original)
        snap2 = self.store.update_layout("P2", p2)
        self.assertNotEqual(snap1.sequence, snap2.sequence)
        self.assertEqual(self.store.latest_sequence("P1"), snap1.sequence)
        self.assertEqual(self.store.latest_sequence("P2"), snap2.sequence)

    def test_ready_snapshot_requires_current_hand_606(self):
        self.assertIsNone(self.store.ready_snapshot("P1", layout606_to_slot_order(self.original)))
        snapshot = self.store.update_layout("P1", self.original)
        self.assertEqual(
            self.store.ready_snapshot("P1", layout606_to_slot_order(self.original)),
            snapshot,
        )
        self.store.begin_hand("P1", list(range(13, 26)))
        self.assertIsNone(self.store.ready_snapshot("P1", layout606_to_slot_order(self.original)))

    def test_extension_ready_version_is_stored(self):
        self.store.mark_extension_ready("P1", "0.2.0")
        self.assertEqual(self.store.extension_version("P1"), "0.2.0")

    def test_cmd606_uses_same_raw_mapping_as_cmd600(self):
        raw = list(range(13))
        self.assertEqual(
            layout606_to_slot_order(raw),
            ws_codes_to_tool_slot_order(raw),
        )
        self.assertEqual(
            layout606_to_slot_order(raw),
            list(reversed(ws_codes_to_cards(raw))),
        )


class ApplyConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.store = WSLayoutStore()
        self.original = list(range(13))
        self.target = layout606_to_slot_order(self.original)
        self.store.begin_hand("P1", self.original)

    def _publish(self, codes, delay=0.01):
        def worker():
            time.sleep(delay)
            self.store.update_layout("P1", codes, event_at=time.time())

        threading.Thread(target=worker, daemon=True).start()

    def test_correct_new_606_confirms_without_repair(self):
        self._publish(self.original)
        result = confirm_and_repair_layout(
            "P1",
            self.target,
            after_sequence=0,
            drag_finished_at=time.time() - 0.01,
            repair=lambda _actual: time.time(),
            store=self.store,
            timeout_s=0.2,
            first_snapshot_timeout_s=0.2,
        )
        self.assertTrue(result.confirmed)
        self.assertEqual(result.repair_attempts, 0)

    def test_mismatch_repairs_then_waits_for_newer_606(self):
        mismatch = list(self.original)
        mismatch[0], mismatch[5] = mismatch[5], mismatch[0]
        calls = []

        def repair(_actual):
            calls.append(True)
            self._publish(self.original)
            return time.time() - 0.001

        self._publish(mismatch)
        result = confirm_and_repair_layout(
            "P1",
            self.target,
            after_sequence=0,
            drag_finished_at=time.time() - 0.01,
            repair=repair,
            store=self.store,
            timeout_s=0.3,
            first_snapshot_timeout_s=0.3,
        )
        self.assertTrue(result.confirmed)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.repair_attempts, 1)

    def test_timeout_fails_closed(self):
        result = confirm_and_repair_layout(
            "P1",
            self.target,
            after_sequence=0,
            drag_finished_at=time.time(),
            repair=lambda _actual: time.time(),
            store=self.store,
            timeout_s=0.01,
            first_snapshot_timeout_s=0.01,
        )
        self.assertFalse(result.confirmed)
        self.assertEqual(result.reason, "timeout")

    def test_timeout_retry_can_confirm_late_606(self):
        self._publish(self.original, delay=0.03)
        result = confirm_and_repair_layout(
            "P1",
            self.target,
            after_sequence=0,
            drag_finished_at=time.time() - 0.01,
            repair=lambda _actual: time.time(),
            store=self.store,
            timeout_s=0.01,
            first_snapshot_timeout_s=0.01,
            timeout_retry_count=1,
            timeout_retry_s=0.12,
        )
        self.assertTrue(result.confirmed)
        self.assertEqual(result.repair_attempts, 0)

    def test_new_hand_while_waiting_reports_hand_changed(self):
        generation = self.store.hand_generation("P1")
        threading.Timer(
            0.01,
            lambda: self.store.begin_hand("P1", list(range(13, 26))),
        ).start()
        result = confirm_and_repair_layout(
            "P1",
            self.target,
            after_sequence=0,
            drag_finished_at=time.time(),
            repair=lambda _actual: time.time(),
            store=self.store,
            timeout_s=0.2,
            first_snapshot_timeout_s=0.2,
            expected_hand_generation=generation,
        )
        self.assertFalse(result.confirmed)
        self.assertEqual(result.reason, "hand_changed")


if __name__ == "__main__":
    unittest.main()
