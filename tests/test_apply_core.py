import json
import random
import unittest
from unittest.mock import patch

from browser.devtools import DevToolsClient
from engine.action import apply_arrangement, compute_drag_settle_s, compute_moves


def _apply_moves(codes, moves):
    result = list(codes)
    for src, dst in moves:
        result[src], result[dst] = result[dst], result[src]
    return result


def _same_groups(left, right):
    return all(
        set(left[start:end]) == set(right[start:end])
        for start, end in ((0, 3), (3, 8), (8, 13))
    )


class _FakeWebSocket:
    def __init__(self, error_id=None):
        self.sent = []
        self.error_id = error_id

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def recv(self):
        command = self.sent.pop(0)
        command_id = command["id"]
        if command_id == self.error_id:
            return json.dumps({"id": command_id, "error": {"message": "rejected"}})
        return json.dumps({"id": command_id, "result": {}})

    def close(self):
        return None


class ComputeMovesTests(unittest.TestCase):
    def test_random_group_permutations_are_closed_in_one_pass(self):
        rng = random.Random(20260607)
        base = [f"C{i}" for i in range(13)]

        for _ in range(20_000):
            current = list(base)
            target = list(base)
            rng.shuffle(current)
            rng.shuffle(target)

            moves = compute_moves(current, target)
            self.assertLessEqual(len(moves), 13)
            self.assertTrue(_same_groups(_apply_moves(current, moves), target))

    def test_three_group_cycle_is_closed(self):
        current = [f"C{i}" for i in range(13)]
        target = list(current)
        target[0], target[3], target[8] = current[8], current[0], current[3]

        moves = compute_moves(current, target)

        self.assertEqual(len(moves), 2)
        self.assertTrue(_same_groups(_apply_moves(current, moves), target))

    def test_copy_style_preserves_legacy_drag_direction(self):
        current = [f"C{i}" for i in range(13)]
        target = list(current)
        target[0], target[3], target[8] = current[8], current[0], current[3]

        moves = compute_moves(current, target, copy_style=True)

        self.assertEqual(moves, [(0, 3), (8, 0)])
        self.assertTrue(_same_groups(_apply_moves(current, moves), target))


class DragSettleTests(unittest.TestCase):
    def test_settle_uses_configured_delay_without_hidden_minimums(self):
        independent, independent_touches = compute_drag_settle_s(0.02, (4, 8), (0, 3))
        dependent, dependent_touches = compute_drag_settle_s(0.02, (0, 9), (0, 3))

        self.assertFalse(independent_touches)
        self.assertTrue(dependent_touches)
        self.assertEqual(independent, 0.02)
        self.assertEqual(dependent, 0.02)

    def test_user_configured_longer_settle_is_preserved(self):
        settle, _ = compute_drag_settle_s(0.5, (0, 9), (0, 3))
        self.assertEqual(settle, 0.5)


class ApplyArrangementTimingTests(unittest.TestCase):
    def test_auto_drag_uses_manual_shape_and_full_configured_settle(self):
        current = [f"C{i}" for i in range(13)]
        moves = [(0, 1), (1, 2)]
        slots = {
            str(i): {"x": i * 10, "y": 0, "width": 10, "height": 10}
            for i in range(1, 14)
        }
        sleeps = []

        class _DevTools:
            def __init__(self):
                self.calls = []

            def mouse_drag(self, *args, **kwargs):
                self.calls.append((args, kwargs))

        class _Browser:
            _slot = 1

            def __init__(self):
                self.devtools = _DevTools()

            def get_active_tab(self, _pid):
                return self

        browser = _Browser()

        with patch("engine.action.load_config", return_value={"ui": {"apply": {"drag_duration_ms": 60}}}):
            with patch("engine.action.get_game_region", return_value={"x": 0, "y": 0}):
                with patch("engine.action.get_slots", return_value=slots):
                    with patch("engine.action.validate_runtime_coordinates", return_value=(True, "")):
                        with patch("engine.action.compute_target_codes", return_value=list(current)):
                            with patch("engine.action.compute_moves", return_value=list(moves)):
                                with patch("engine.action.time.sleep", side_effect=lambda s: sleeps.append(float(s))):
                                    apply_arrangement(
                                        "P1",
                                        browser,
                                        list(current),
                                        [],
                                        [],
                                        [],
                                        delay_s=0.025,
                                        use_fast_drag=True,
                                    )

        self.assertEqual(len(browser.devtools.calls), len(moves))
        for _args, kwargs in browser.devtools.calls:
            self.assertNotIn("steps", kwargs)
            self.assertNotIn("duration_s", kwargs)
            self.assertIs(kwargs.get("wait_ack"), True)
        self.assertEqual(len(sleeps), 2)
        for sleep_s in sleeps:
            self.assertAlmostEqual(sleep_s, 0.085)


class DevToolsAcknowledgementTests(unittest.TestCase):
    def test_mouse_commands_wait_for_all_acknowledgements(self):
        client = DevToolsClient("P1", 9222)
        socket = _FakeWebSocket()
        client._open_ws = lambda: socket

        client._dispatch_mouse_events(
            [{"type": "mouseMoved", "x": 1, "y": 2, "button": "none"}]
        )

        self.assertEqual(socket.sent, [])

    def test_mouse_command_error_is_not_hidden(self):
        client = DevToolsClient("P1", 9222)
        client._open_ws = lambda: _FakeWebSocket(error_id=2)

        with self.assertRaises(RuntimeError):
            client._dispatch_mouse_events(
                [{"type": "mouseMoved", "x": 1, "y": 2, "button": "none"}]
            )


if __name__ == "__main__":
    unittest.main()
