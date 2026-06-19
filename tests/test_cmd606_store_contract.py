import unittest
from unittest.mock import patch


class _FakeCardStore:
    def __init__(self):
        self.calls = []
        self.last = {}

    def update_cards(self, profile_id, ws_codes):
        self.calls.append((str(profile_id), list(ws_codes)))
        self.last[str(profile_id)] = list(ws_codes)
        return list(ws_codes)

    def get_last_cards(self, profile_id):
        value = self.last.get(str(profile_id))
        return list(value) if value is not None else None


class _FakeLayoutStore:
    def __init__(self):
        self.begin_calls = []
        self.layout_calls = []

    def begin_hand(self, profile_id, ws_codes):
        self.begin_calls.append((str(profile_id), list(ws_codes)))

    def update_layout(self, profile_id, ws_codes, *, event_at=None):
        self.layout_calls.append((str(profile_id), list(ws_codes), event_at))
        return object()

    def mark_extension_ready(self, profile_id, version):
        return None


class Cmd606StoreContractTests(unittest.TestCase):
    def test_tool_context_606_updates_layout_store_only(self):
        from core.tool_context import ToolContext

        ctx = ToolContext.__new__(ToolContext)
        ctx.slot = 2
        ctx.card_store = _FakeCardStore()
        ctx.layout_store = _FakeLayoutStore()
        ctx.room_engine = None
        ctx.xao_vang_tab = None

        original = list(range(13))
        layout = list(reversed(original))

        ctx.dispatch_event({"profile_id": "P1", "payload": {"cmd": 600, "cs": original}})
        self.assertEqual(ctx.card_store.get_last_cards("P1"), original)
        self.assertEqual(ctx.layout_store.begin_calls, [("P1", original)])

        ctx.dispatch_event({
            "kind": "layout_snapshot",
            "profile_id": "P1",
            "payload": {"cmd": 606, "cs": layout},
            "sent_at_ms": 123000,
        })

        self.assertEqual(ctx.card_store.get_last_cards("P1"), original)
        self.assertEqual(ctx.card_store.calls, [("P1", original)])
        self.assertEqual(ctx.layout_store.layout_calls, [("P1", layout, 123.0)])

    def test_main_window_606_updates_layout_store_only(self):
        import ui2.main as main_mod
        from ui2.main import MainWindow

        window = MainWindow.__new__(MainWindow)
        window._app_inited = True
        window.room_engine = None
        window.auto_four_tool_tab = None

        card_store = _FakeCardStore()
        layout_store = _FakeLayoutStore()
        original = list(range(13))
        layout = list(reversed(original))

        with patch.object(main_mod, "ws_card_store", card_store):
            with patch("ui2.bridge.ws_layout_store.ws_layout_store", layout_store):
                window._handle_bridge_event({
                    "profile_id": "P1",
                    "payload": {"cmd": 600, "cs": original},
                })
                self.assertEqual(card_store.get_last_cards("P1"), original)
                self.assertEqual(layout_store.begin_calls, [("P1", original)])

                window._handle_bridge_event({
                    "kind": "layout_snapshot",
                    "profile_id": "P1",
                    "payload": {"cmd": 606, "cs": layout},
                    "sent_at_ms": 456000,
                })

        self.assertEqual(card_store.get_last_cards("P1"), original)
        self.assertEqual(card_store.calls, [("P1", original)])
        self.assertEqual(layout_store.layout_calls, [("P1", layout, 456.0)])


if __name__ == "__main__":
    unittest.main()
