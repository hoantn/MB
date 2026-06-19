import unittest

from ui2.tabs.strategy2.strategy_tab import StrategyTab


class _ExplodingIngest:
    def poll(self, **_kwargs):
        raise AssertionError("disabled StrategyTab must not poll WS")


class StrategyWsDisabledTests(unittest.TestCase):
    def test_poll_ws_returns_without_touching_ingest_when_disabled(self):
        tab = StrategyTab.__new__(StrategyTab)
        tab._ws_enabled = False
        tab._ws_ingest = _ExplodingIngest()

        StrategyTab._poll_ws(tab)


if __name__ == "__main__":
    unittest.main()
