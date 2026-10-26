"""Verify the torque card installs exactly once and refuses drifted upstream trees."""

import ast
import tempfile
import textwrap
import unittest
from pathlib import Path

import patch_torque_card as p

SETTINGS_SAMPLE = """class SettingsLayoutSP(OP.SettingsLayout):
  def __init__(self):
    items = self._scroller._items.copy()

    items.insert(1, models_btn)
    items.insert(5, sunnylink_btn)

    # front slots (only one ever visible at a time): exit-always-offroad, then enable-onroad
    items.insert(0, self._enable_offroad_btn_onroad)
"""


class TorqueCardPatchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        card = ast.parse(p.CARD_SOURCE.read_text(encoding="utf-8"))
        block = ast.parse(textwrap.dedent(p.BLOCK))

        # A minimal upstream tree providing exactly what the card imports.
        self.stubs = {}
        for tree in (card, block):
            for module, names in p.upstream_imports(tree).items():
                if module != p.CARD_MODULE:
                    self.stubs.setdefault(module, set()).update(names)
        for module, names in self.stubs.items():
            self._write_module(module, names)
        self._write(p.SETTINGS_FILE, SETTINGS_SAMPLE)
        self._write(p.PARAMS_FILE, "".join(f'    {{"{k}", {{PERSISTENT, BOOL}}}},\n' for k in p.param_keys(card)))
        self._write(p.ASSETS_DIR / "icons_mici/wheel.png", "png")

    def _write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def _write_module(self, module, names):
        top, *parts = module.split(".")
        self._write((p.PACKAGE_ROOTS[top] / Path(*parts)).with_suffix(".py"), "".join(f"{n} = None\n" for n in sorted(names)))

    def _settings(self):
        return (self.root / p.SETTINGS_FILE).read_text(encoding="utf-8")

    def test_installs_card_and_one_settings_block(self):
        p.process(self.root, "stock")
        p.process(self.root, "apply")
        p.process(self.root, "verify")
        installed = (self.root / p.CARD_FILE).read_bytes()
        self.assertEqual(installed, p.CARD_SOURCE.read_text(encoding="utf-8").encode("utf-8"))
        self.assertNotIn(b"\r\n", installed)
        settings = self._settings()
        self.assertEqual(settings.count("TorqueTuningBigButton()"), 1)
        self.assertLess(settings.index("insert(5, sunnylink_btn)"), settings.index("insert(2, TorqueTuningBigButton())"))
        self.assertLess(settings.index("TorqueTuningBigButton()"), settings.index("# front slots"))

    def test_reapply_fails_instead_of_double_install(self):
        p.process(self.root, "apply")
        with self.assertRaisesRegex(ValueError, "already installed"):
            p.process(self.root, "apply")

    def test_moved_anchor_fails_before_any_write(self):
        self._write(p.SETTINGS_FILE, SETTINGS_SAMPLE.replace("insert(5, sunnylink_btn)", "insert(6, sunnylink_btn)"))
        with self.assertRaisesRegex(ValueError, "anchor"):
            p.process(self.root, "apply")
        self.assertFalse((self.root / p.CARD_FILE).exists())

    def test_renamed_upstream_widget_fails_before_any_write(self):
        module = "openpilot.selfdrive.ui.mici.widgets.button"
        self._write_module(module, self.stubs[module] - {"BigMultiToggle"})
        with self.assertRaisesRegex(ValueError, "BigMultiToggle"):
            p.process(self.root, "apply")
        self.assertFalse((self.root / p.CARD_FILE).exists())
        self.assertEqual(self._settings(), SETTINGS_SAMPLE)

    def test_removed_upstream_module_fails(self):
        (self.root / "opendbc_repo/opendbc/car/structs.py").unlink()
        with self.assertRaisesRegex(ValueError, "opendbc.car.structs no longer exists"):
            p.process(self.root, "stock")

    def test_removed_param_fails(self):
        params = (self.root / p.PARAMS_FILE).read_text(encoding="utf-8")
        self._write(p.PARAMS_FILE, params.replace('"LateralJerkTorqueController"', '"SomethingElse"'))
        with self.assertRaisesRegex(ValueError, "LateralJerkTorqueController"):
            p.process(self.root, "apply")
        self.assertFalse((self.root / p.CARD_FILE).exists())

    def test_missing_icon_fails(self):
        (self.root / p.ASSETS_DIR / "icons_mici/wheel.png").unlink()
        with self.assertRaisesRegex(ValueError, "icon"):
            p.process(self.root, "stock")

    def test_verify_catches_edited_card(self):
        p.process(self.root, "apply")
        card = self.root / p.CARD_FILE
        card.write_bytes(card.read_bytes().replace(b"0.001", b"0.002"))
        with self.assertRaisesRegex(ValueError, "differs"):
            p.process(self.root, "verify")


if __name__ == "__main__":
    unittest.main()
