import unittest

from ui2.tabs.strategy2.modules.auto_play_controller import classify_auto_room_context


UIDS = {"P1": "u1", "P2": "u2", "P3": "u3"}


class _RoomEngine:
    def __init__(self, rosters, fresh=True):
        self.rosters = rosters
        self.fresh = fresh

    def get_room_monitor_state(self, profile_id):
        return {
            "profiles": {
                pid: {"uid": uid, "gold": index * 100}
                for index, (pid, uid) in enumerate(UIDS.items(), start=1)
            },
            "room_uids": self.rosters.get(profile_id, []),
            "roster_fresh": self.fresh,
        }


class AutoRoomContextTests(unittest.TestCase):
    def test_three_profiles_same_table_with_opp(self):
        roster = ["u1", "u2", "u3", "opp"]
        context = classify_auto_room_context(
            _RoomEngine({pid: roster for pid in UIDS})
        )
        self.assertEqual(context.kind, "external_opp")

    def test_two_profiles_same_table_and_one_separate(self):
        context = classify_auto_room_context(
            _RoomEngine({"P1": ["u1", "u2"], "P2": ["u1", "u2"], "P3": ["u3"]})
        )
        self.assertEqual(context.kind, "internal_2p")
        self.assertEqual(set(context.controlled_pids), {"P1", "P2"})

    def test_three_profiles_internal_table(self):
        roster = ["u1", "u2", "u3"]
        context = classify_auto_room_context(_RoomEngine({pid: roster for pid in UIDS}))
        self.assertEqual(context.kind, "internal_3p")

    def test_two_profiles_with_guest_falls_back(self):
        context = classify_auto_room_context(
            _RoomEngine(
                {
                    "P1": ["u1", "u2", "guest"],
                    "P2": ["u1", "u2", "guest"],
                    "P3": ["u3"],
                }
            )
        )
        self.assertEqual(context.kind, "unknown")

    def test_three_profiles_with_multiple_guests_falls_back(self):
        roster = ["u1", "u2", "u3", "guest1", "guest2"]
        context = classify_auto_room_context(_RoomEngine({pid: roster for pid in UIDS}))
        self.assertEqual(context.kind, "unknown")

    def test_every_profile_separate_falls_back(self):
        context = classify_auto_room_context(
            _RoomEngine({"P1": ["u1"], "P2": ["u2"], "P3": ["u3"]})
        )
        self.assertEqual(context.kind, "unknown")

    def test_stale_roster_falls_back(self):
        roster = ["u1", "u2", "u3"]
        context = classify_auto_room_context(
            _RoomEngine({pid: roster for pid in UIDS}, fresh=False)
        )
        self.assertEqual(context.kind, "unknown")


if __name__ == "__main__":
    unittest.main()
