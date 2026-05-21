import pytest

from openpilot.sunnypilot.selfdrive.controls.lib.dec.dec import DynamicExperimentalController
from openpilot.sunnypilot.selfdrive.controls.lib.dec.constants import WMACConstants

class MockLeadOne:
  def __init__(self, status=0.0, dRel=0.0, vLead=0.0):
    self.status = status
    self.dRel = dRel
    self.vLead = vLead

class MockRadarState:
  def __init__(self, status=0.0, dRel=0.0, vLead=0.0):
    self.leadOne = MockLeadOne(status=status, dRel=dRel, vLead=vLead)

class MockCarState:
  def __init__(self, vEgo=0.0, vCruise=0.0, standstill=False, gasPressed=False):
    self.vEgo = vEgo
    self.vCruise = vCruise
    self.standstill = standstill
    self.gasPressed = gasPressed

class MockAction:
  def __init__(self, shouldStop=False):
    self.shouldStop = shouldStop

class MockModelData:
  def __init__(self, valid=True, endpoint_x=0.0, shouldStop=False):
    size = 33 if valid else 10
    xs = [0.0] * size
    if valid and size > 0:
      xs[-1] = endpoint_x
    self.position = type("Pos", (), {"x": xs})()
    self.orientation = type("Ori", (), {"x": [0.0] * size})()
    self.action = MockAction(shouldStop=shouldStop)

class MockSelfDriveState:
  def __init__(self, experimentalMode=False):
    self.experimentalMode = experimentalMode

class MockParams:
  def __init__(self, overrides=None):
    self._overrides = overrides or {}
  def get_bool(self, name):
    return self._overrides.get(name, True)

@pytest.fixture
def default_sm():
  sm = {
    'carState': MockCarState(vEgo=10.0, vCruise=20.0),
    'radarState': MockRadarState(status=1.0),
    'modelV2': MockModelData(valid=True),
    'selfdriveState': MockSelfDriveState(experimentalMode=True),
  }
  return sm

@pytest.fixture
def mock_cp():
  class CP:
    radarUnavailable = False
  return CP()

@pytest.fixture
def mock_mpc():
  class MPC:
    crash_cnt = 0
  return MPC()

# Fake Kalman Filter that always returns a given value
class FakeKalman:
  def __init__(self, value=1.0):
    self.value = value
  def add_data(self, v): pass
  def get_value(self): return self.value
  def get_confidence(self): return 1.0
  def reset_data(self): pass

def test_initial_mode_is_acc(mock_cp, mock_mpc):
  controller = DynamicExperimentalController(mock_cp, mock_mpc, params=MockParams())
  assert controller.mode() == "acc"

def test_standstill_triggers_blended(mock_cp, mock_mpc, default_sm):
  controller = DynamicExperimentalController(mock_cp, mock_mpc, params=MockParams())
  default_sm['carState'].standstill = True
  for _ in range(10):
    controller.update(default_sm)
  assert controller.mode() == "blended"

def test_emergency_blended_on_fcw(mock_cp, mock_mpc, default_sm):
  controller = DynamicExperimentalController(mock_cp, mock_mpc, params=MockParams())
  mock_mpc.crash_cnt = 1  # simulate FCW
  for _ in range(2):
    controller.update(default_sm)
  assert controller.mode() == "blended"

def test_radarless_slowdown_triggers_blended(mock_cp, mock_mpc, default_sm):
  mock_cp.radarUnavailable = True
  controller = DynamicExperimentalController(mock_cp, mock_mpc, params=MockParams())

  # Force conditions to simulate slowdown
  controller._slow_down_filter = FakeKalman(value=1.0)  # Ensure urgency triggers slowdown
  controller._v_ego_kph = 35.0
  default_sm['modelV2'] = MockModelData(valid=False)  # Incomplete trajectory

  for _ in range(3):
    controller.update(default_sm)

  assert controller.mode() == "blended"


def _red_light_sm():
  return {
    'carState': MockCarState(vEgo=0.0, vCruise=20.0, standstill=True, gasPressed=False),
    'radarState': MockRadarState(status=0.0),  # no lead
    'modelV2': MockModelData(valid=True, endpoint_x=5.0, shouldStop=True),
    'selfdriveState': MockSelfDriveState(experimentalMode=True),
  }


def test_stop_hold_arms_at_red_light(mock_cp, mock_mpc):
  controller = DynamicExperimentalController(mock_cp, mock_mpc, params=MockParams())
  sm = _red_light_sm()
  for _ in range(WMACConstants.STOP_HOLD_ARM_FRAMES + 5):
    controller.update(sm)
  assert controller.force_stop_hold(), "stop-hold should latch after sustained shouldStop+standstill"
  assert controller.mode() == "blended"


def test_stop_hold_releases_on_gas(mock_cp, mock_mpc):
  controller = DynamicExperimentalController(mock_cp, mock_mpc, params=MockParams())
  sm = _red_light_sm()
  for _ in range(WMACConstants.STOP_HOLD_ARM_FRAMES + 5):
    controller.update(sm)
  assert controller.force_stop_hold()
  sm['carState'].gasPressed = True
  controller.update(sm)
  assert not controller.force_stop_hold()


def test_stop_hold_releases_on_long_trajectory(mock_cp, mock_mpc):
  controller = DynamicExperimentalController(mock_cp, mock_mpc, params=MockParams())
  sm = _red_light_sm()
  for _ in range(WMACConstants.STOP_HOLD_ARM_FRAMES + 5):
    controller.update(sm)
  assert controller.force_stop_hold()
  # Model shows long forward trajectory — green light proxy
  sm['modelV2'] = MockModelData(valid=True,
                                endpoint_x=WMACConstants.STOP_HOLD_RELEASE_TRAJ_X + 10.0,
                                shouldStop=False)
  for _ in range(WMACConstants.STOP_HOLD_RELEASE_TRAJ_FRAMES + 2):
    controller.update(sm)
  assert not controller.force_stop_hold()


def test_stop_hold_not_armed_with_lead(mock_cp, mock_mpc):
  controller = DynamicExperimentalController(mock_cp, mock_mpc, params=MockParams())
  sm = _red_light_sm()
  sm['radarState'] = MockRadarState(status=1.0, dRel=5.0, vLead=0.0)  # stopped lead
  for _ in range(WMACConstants.STOP_HOLD_ARM_FRAMES + 5):
    controller.update(sm)
  assert not controller.force_stop_hold(), "lead present → ACC handles, no stop-hold"


def test_low_speed_min_mode_duration(mock_cp, mock_mpc, default_sm):
  controller = DynamicExperimentalController(mock_cp, mock_mpc, params=MockParams())
  default_sm['carState'].vEgo = 5.0  # 18 kph, below threshold
  controller.update(default_sm)
  assert controller._mode_manager.min_mode_duration == WMACConstants.LOW_SPEED_MIN_MODE_DURATION
  default_sm['carState'].vEgo = 25.0  # 90 kph, above threshold
  controller.update(default_sm)
  assert controller._mode_manager.min_mode_duration == controller._base_min_mode_duration
