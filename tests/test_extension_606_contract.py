import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Extension606ContractTests(unittest.TestCase):
    def test_all_extensions_have_ready_version_and_layout_forwarding(self):
        manifests = sorted((ROOT / "chrome_ext").rglob("manifest.json"))
        backgrounds = sorted((ROOT / "chrome_ext").rglob("background.js"))
        self.assertEqual(len(manifests), 33)
        self.assertEqual(len(backgrounds), 33)

        for manifest in manifests:
            with self.subTest(manifest=str(manifest)):
                data = json.loads(manifest.read_text(encoding="utf-8"))
                self.assertEqual(data.get("version"), "0.2.0")

        for background in backgrounds:
            with self.subTest(background=str(background)):
                text = background.read_text(encoding="utf-8")
                self.assertEqual(text.count('kind: "layout_snapshot"'), 1)
                self.assertEqual(text.count('kind: "extension_ready"'), 1)
                self.assertIn('const EXTENSION_VERSION = "0.2.0"', text)


if __name__ == "__main__":
    unittest.main()
