import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from core import config as config_mod


class ConfigAtomicSaveTests(unittest.TestCase):
    def test_atomic_write_uses_unique_temp_file_per_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "config.json")
            real_replace = config_mod.os.replace
            sources = []

            def record_replace(src, dst):
                sources.append(Path(src).name)
                return real_replace(src, dst)

            with mock.patch.object(config_mod.os, "replace", side_effect=record_replace):
                config_mod._atomic_write_json(path, {"value": 1})
                config_mod._atomic_write_json(path, {"value": 2})

            self.assertEqual(len(sources), 2)
            self.assertNotEqual(sources[0], sources[1])
            self.assertEqual(json.loads(Path(path).read_text(encoding="utf-8"))["value"], 2)

    def test_atomic_write_retries_temporary_replace_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "config.json")
            real_replace = config_mod.os.replace
            attempts = {"count": 0}

            def flaky_replace(src, dst):
                attempts["count"] += 1
                if attempts["count"] < 3:
                    err = PermissionError("simulated temporary lock")
                    err.winerror = 32
                    raise err
                return real_replace(src, dst)

            with mock.patch.object(config_mod.os, "replace", side_effect=flaky_replace):
                config_mod._atomic_write_json(path, {"ok": True})

            self.assertEqual(attempts["count"], 3)
            self.assertTrue(json.loads(Path(path).read_text(encoding="utf-8"))["ok"])

    def test_concurrent_save_config_does_not_collide_on_shared_tmp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_dir = str(Path(tmpdir))
            cfg_file = str(Path(tmpdir) / "config.json")

            def save_one(i):
                config_mod.save_config({"idx": i}, slot=1)

            with mock.patch.object(config_mod, "CONFIG_DIR", cfg_dir), mock.patch.object(
                config_mod, "CONFIG_FILE", cfg_file
            ), mock.patch.object(config_mod.log, "error") as log_error:
                threads = [
                    threading.Thread(target=save_one, args=(i,), daemon=True)
                    for i in range(24)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)

                log_error.assert_not_called()

            data = json.loads(Path(cfg_file).read_text(encoding="utf-8"))
            self.assertIn("idx", data)
            self.assertFalse(list(Path(tmpdir).glob(".config.json.*.tmp")))


if __name__ == "__main__":
    unittest.main()
