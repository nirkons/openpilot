"""Verify Sunnylink precision is patched without changing unrelated schema fields."""

import json
import tempfile
import unittest
from pathlib import Path

from patch_sunnylink import YAML_FILE, JSON_FILE, process, SETTING

YAML_SAMPLE = """id: steering
sections:
- id: torque
  sub_panels:
  - id: torque_settings
    items:
    - key: TorqueParamsOverrideLatAccelFactor
      widget: option
      title: Lateral Acceleration Factor
      min: 0.1
      max: 5.0
      step: 0.1
      unit: m/s²
      enablement:
      - type: param
        key: CustomTorqueParams
        equals: true
    - key: TorqueParamsOverrideFriction
      widget: option
      min: 0.0
      max: 1.0
      step: 0.01
"""

SCHEMA = {"panels": [{"sections": [{"sub_panels": [{"items": [
    {"key": SETTING, "widget": "option", "min": 0.1, "max": 5.0,
     "step": 0.1, "unit": "m/s²",
     "enablement": [{"type": "param", "key": "CustomTorqueParams"}]},
    {"key": "TorqueParamsOverrideFriction", "step": 0.01}
]}]}]}]}


class SunnylinkStepTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for file in (YAML_FILE, JSON_FILE):
            (self.root / file).parent.mkdir(parents=True, exist_ok=True)
        (self.root / YAML_FILE).write_text(YAML_SAMPLE, encoding="utf-8")
        (self.root / JSON_FILE).write_text(
            json.dumps(SCHEMA, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def test_patches_only_lateral_acceleration_step(self):
        process(self.root, "stock")
        process(self.root, "apply")
        process(self.root, "verify")
        y = (self.root / YAML_FILE).read_text(encoding="utf-8")
        d = json.loads((self.root / JSON_FILE).read_text(encoding="utf-8"))
        self.assertEqual(y.count("step: 0.001"), 1)
        self.assertIn("step: 0.01", y)  # Friction unmodified
        self.assertEqual(d["panels"][0]["sections"][0]["sub_panels"][0]["items"][0]["step"], 0.001)
        self.assertEqual(d["panels"][0]["sections"][0]["sub_panels"][0]["items"][1]["step"], 0.01)

    def test_drift_in_yaml_fails_before_any_write(self):
        yaml_path = self.root / YAML_FILE
        yaml_path.write_text(YAML_SAMPLE.replace("step: 0.1", "step: 0.2"), encoding="utf-8")
        original_json = (self.root / JSON_FILE).read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unexpected YAML"):
            process(self.root, "apply")
        self.assertEqual((self.root / JSON_FILE).read_text(encoding="utf-8"), original_json)

    def test_drift_in_json_fails_before_any_write(self):
        json_path = self.root / JSON_FILE
        json_path.write_text(json_path.read_text(encoding="utf-8").replace('"step": 0.1', '"step": 0.2'), encoding="utf-8")
        original_yaml = (self.root / YAML_FILE).read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unexpected JSON"):
            process(self.root, "apply")
        self.assertEqual((self.root / YAML_FILE).read_text(encoding="utf-8"), original_yaml)

    def test_reapply_fails_instead_of_silent_override(self):
        process(self.root, "apply")
        with self.assertRaisesRegex(ValueError, "Unexpected YAML"):
            process(self.root, "apply")


if __name__ == "__main__":
    unittest.main()
