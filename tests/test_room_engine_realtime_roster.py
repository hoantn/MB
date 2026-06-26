import time
import unittest

import ui2.main  # noqa: F401 - initialize ui2/engine import cycle like the app
from engine.room_engine import RoomEngine
from ui2.tabs.strategy2.modules.auto_play_controller import classify_auto_room_context


UIDS = {"P1": "u1", "P2": "u2", "P3": "u3"}
ROSTER = {"u1", "u2", "u3", "opp"}


def _room_engine_with_external_opp():
    engine = RoomEngine.__new__(RoomEngine)
    engine._self_uid_by_profile = dict(UIDS)
    engine._self_uid_all = set(UIDS.values())
    engine._gold_by_uid = {}
    engine._room_uids_by_profile = {pid: set(ROSTER) for pid in UIDS}
    now = time.monotonic()
    engine._room_roster_updated_at = {pid: now for pid in UIDS}
    engine._room_roster_reliable = {pid: True for pid in UIDS}
    engine._last_snapshot = {pid: None for pid in UIDS}
    return engine


class RoomEngineRealtimeRosterTests(unittest.TestCase):
    def test_initial_room_snapshot_does_not_emit_session_change(self):
        engine = _room_engine_with_external_opp()
        emitted = []

        class _Signal:
            def emit(self, *args):
                emitted.append(args)

        engine.sig_profile_room_session_changed = _Signal()

        engine._emit_room_session_changed_if_needed("P1", None, ("room-a", 1, "u1"), "room_snapshot")
        self.assertEqual(emitted, [])

        engine._emit_room_session_changed_if_needed(
            "P1",
            ("room-a", 1, "u1"),
            ("room-b", 1, "u1"),
            "room_snapshot",
        )
        self.assertEqual(emitted, [("P1", "room_snapshot")])

    def test_empty_cmd600_lpi_does_not_clear_valid_roster(self):
        engine = _room_engine_with_external_opp()

        self.assertEqual(classify_auto_room_context(engine).kind, "external_opp")

        engine.on_room_roster("P1", [])

        self.assertEqual(engine._room_uids_by_profile["P1"], ROSTER)
        self.assertTrue(engine._room_roster_reliable["P1"])
        self.assertEqual(classify_auto_room_context(engine).kind, "external_opp")

    def test_cmd600_lpi_dict_roster_normalizes_uids(self):
        engine = _room_engine_with_external_opp()

        engine.on_room_roster(
            "P1",
            [{"uid": "u1"}, {"uid": "u2"}, {"uid": "u3"}, {"uid": "opp"}],
        )

        self.assertEqual(engine._room_uids_by_profile["P1"], ROSTER)
        self.assertTrue(engine._room_roster_reliable["P1"])
        self.assertEqual(classify_auto_room_context(engine).kind, "external_opp")

    def test_empty_cmd205_ps_does_not_clear_valid_roster(self):
        engine = _room_engine_with_external_opp()

        self.assertEqual(classify_auto_room_context(engine).kind, "external_opp")

        engine.on_room_balance_205("P2", {"cmd": 205, "ps": []})

        self.assertEqual(engine._room_uids_by_profile["P2"], ROSTER)
        self.assertTrue(engine._room_roster_reliable["P2"])
        self.assertEqual(classify_auto_room_context(engine).kind, "external_opp")


if __name__ == "__main__":
    unittest.main()
