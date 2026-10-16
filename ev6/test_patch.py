"""Tests run on every GitHub Actions iteration, before any publishing."""

import tempfile
import unittest
from pathlib import Path

from patch import SAFETY_FILE, VALUES_FILE, _process_files


PY_STOCK = '''class CarControllerParams:
  def __init__(self, CP):
    self.STEER_DELTA_UP = 3
    self.STEER_DELTA_DOWN = 7
    if CP.flags & HyundaiFlags.CANFD:
      self.STEER_MAX = 270
      self.STEER_DRIVER_ALLOWANCE = 250
      self.STEER_DELTA_UP = 2
      self.STEER_DELTA_DOWN = 3

    elif CP.carFingerprint in []:
      self.STEER_MAX = 384
'''

C_STOCK = '''static bool hook(void) {
  const TorqueSteeringLimits HYUNDAI_CANFD_STEERING_LIMITS = {
    .max_torque = 270,
    .max_rt_delta = 112,
    .max_rate_up = 2,
    .max_rate_down = 3,
    .driver_torque_allowance = 250,
  };
}
'''


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        for p, text in [(VALUES_FILE, PY_STOCK), (SAFETY_FILE, C_STOCK)]:
            file = self.root / p
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text)

    def test_expected_change_only(self):
        _process_files(self.root, 'stock')
        _process_files(self.root, 'apply')
        _process_files(self.root, 'verify')
        py = (self.root / VALUES_FILE).read_text()
        c = (self.root / SAFETY_FILE).read_text()
        self.assertIn('self.STEER_MAX = 384', py)
        self.assertIn('self.STEER_DELTA_UP = 3', py)
        self.assertIn('self.STEER_DELTA_DOWN = 7', py)
        self.assertIn('.max_torque = 384,', c)
        self.assertIn('.max_rate_up = 3,', c)
        self.assertIn('.max_rate_down = 7,', c)
        self.assertIn('.max_rt_delta = 112,', c)
        self.assertIn('self.STEER_DRIVER_ALLOWANCE = 250', py)

    def test_upstream_change_blocks_publication(self):
        (self.root / VALUES_FILE).write_text(PY_STOCK.replace('STEER_MAX = 270', 'STEER_MAX = 280'))
        with self.assertRaisesRegex(ValueError, 'Unexpected stock'):
            _process_files(self.root, 'apply')
        self.assertEqual((self.root / SAFETY_FILE).read_text(), C_STOCK)

    def test_wrong_panda_source_blocks_publication(self):
        (self.root / SAFETY_FILE).write_text(C_STOCK.replace('.max_rate_up = 2', '.max_rate_up = 4'))
        with self.assertRaisesRegex(ValueError, 'Unexpected stock'):
            _process_files(self.root, 'apply')
        self.assertEqual((self.root / VALUES_FILE).read_text(), PY_STOCK)

    def test_reapply_fails_instead_of_silent_override(self):
        _process_files(self.root, 'apply')
        with self.assertRaisesRegex(ValueError, 'Unexpected stock'):
            _process_files(self.root, 'apply')


if __name__ == '__main__':
    unittest.main()
