import copy
import unittest
from unittest.mock import patch

from core import proxyno1_provider


def _cfg(api_key):
    return {
        "profiles": {
            "P1": {
                "proxy": {
                    "provider": "proxyno1",
                    "proxyno1_api_key": api_key,
                    "host": "",
                    "port": 0,
                    "username": "",
                    "password": "",
                }
            }
        }
    }


class _FakeProxyno1Client:
    seen_keys = []

    def __init__(self, api_key, settings=None):
        self.api_key = api_key
        self.settings = settings
        self.seen_keys.append(api_key)

    def get_key_status(self):
        return {
            "status": 0,
            "message": "OK",
            "data": {
                "authentication": "user2:pass2",
                "http": "slot2.proxy.local:2222:user2:pass2",
                "sock5": "",
            },
        }

    def change_ip(self):
        return {"status": 0, "message": f"changed:{self.api_key}"}


class TestProxyno1SlotIsolation(unittest.TestCase):
    def test_get_proxy_info_uses_and_saves_requested_slot(self):
        configs = {
            1: _cfg("TOOL1_KEY"),
            2: _cfg("TOOL2_KEY"),
        }
        saved = []

        def fake_load_config(slot=1):
            return copy.deepcopy(configs[slot])

        def fake_save_config(cfg, slot=1):
            saved.append((slot, cfg))

        _FakeProxyno1Client.seen_keys = []
        with patch.object(proxyno1_provider, "load_config", side_effect=fake_load_config), patch.object(
            proxyno1_provider, "save_config", side_effect=fake_save_config
        ), patch.object(proxyno1_provider, "Proxyno1Client", _FakeProxyno1Client):
            ok, msg, info = proxyno1_provider.proxyno1_get_proxy_info_for_profile("P1", slot=2)

        self.assertTrue(ok, msg)
        self.assertEqual(info["host"], "slot2.proxy.local")
        self.assertEqual(info["http_port"], 2222)
        self.assertEqual(_FakeProxyno1Client.seen_keys, ["TOOL2_KEY"])
        self.assertEqual([slot for slot, _ in saved], [2])

    def test_change_ip_uses_and_saves_requested_slot(self):
        configs = {
            1: _cfg("TOOL1_KEY"),
            2: _cfg("TOOL2_KEY"),
        }
        saved = []

        def fake_load_config(slot=1):
            return copy.deepcopy(configs[slot])

        def fake_save_config(cfg, slot=1):
            saved.append((slot, cfg))

        _FakeProxyno1Client.seen_keys = []
        with patch.object(proxyno1_provider, "load_config", side_effect=fake_load_config), patch.object(
            proxyno1_provider, "save_config", side_effect=fake_save_config
        ), patch.object(proxyno1_provider, "Proxyno1Client", _FakeProxyno1Client):
            ok, msg = proxyno1_provider.proxyno1_change_ip_for_profile("P1", slot=2)

        self.assertTrue(ok, msg)
        self.assertIn("changed:TOOL2_KEY", msg)
        self.assertEqual(_FakeProxyno1Client.seen_keys, ["TOOL2_KEY"])
        self.assertEqual([slot for slot, _ in saved], [2])
        self.assertEqual(
            saved[0][1]["profiles"]["P1"]["proxy"]["proxyno1_last_message"],
            "changed:TOOL2_KEY",
        )


if __name__ == "__main__":
    unittest.main()
