"""
EV6 fork: on-device torque tuning for the comma 4 (mici) settings screen.

Mirrors the Torque Settings section of sunnylink's Steering page. Values move in
0.001 steps, so small values like the EV6's stock friction (0.005) fit.
Installed into the staging prebuilt by ev6/patch_torque_card.py.
"""
import math
import pyray as rl
from collections.abc import Callable

from opendbc.car.structs import car
from openpilot.selfdrive.ui.mici.layouts.settings.settings import SettingsBigButton
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigToggle, BigMultiToggle, LABEL_COLOR
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialogBase
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller import NavScroller

ENFORCE = "EnforceTorqueControl"
JERK = "LateralJerkTorqueController"
SELF_TUNE = "LiveTorqueParamsToggle"
RELAXED = "LiveTorqueParamsRelaxedToggle"
CUSTOM = "CustomTorqueParams"
REALTIME = "TorqueParamsOverrideEnabled"
LAT_ACCEL_FACTOR = "TorqueParamsOverrideLatAccelFactor"
FRICTION = "TorqueParamsOverrideFriction"
TUNE_VERSION = "TorqueControlTune"
NNLC = "NeuralNetworkLateralControl"
# every param this card touches; the patcher checks they all still exist upstream
PARAM_KEYS = (ENFORCE, JERK, SELF_TUNE, RELAXED, CUSTOM, REALTIME, LAT_ACCEL_FACTOR, FRICTION, TUNE_VERSION, NNLC)

ICON = "icons_mici/wheel.png"
TUNE_VERSIONS = {"default": None, "v1.0": 1.0, "v0.0": 0.0}
STEPS = (0.001, 0.01, 0.1)
HOLD_DELAY = 0.4  # s before a held -/+ starts repeating
REPEAT_RATE = 12  # hz

# picker layout
VALUE_Y = 100  # center line of the value and the -/+
ZONE_WIDTH = 150
CHIP_WIDTH = 220
CHIP_HEIGHT = 50

GREY = rl.Color(255, 255, 255, int(255 * 0.55))
DISABLED_COLOR = rl.Color(255, 255, 255, int(255 * 0.35))
CHIP_BG = rl.Color(255, 255, 255, int(255 * 0.15))
CHIP_PRESSED_BG = rl.Color(255, 255, 255, int(255 * 0.3))


def nudge(milli: int, step: int, direction: int) -> int:
  """One step up or down, landing on a multiple of the step (2.347 + 0.01 -> 2.350)."""
  if direction > 0:
    return (milli // step + 1) * step
  return (-(-milli // step) - 1) * step


def torque_allowed() -> bool:
  CP = ui_state.CP
  return CP is not None and CP.steerControlType != car.CarParams.SteerControlType.angle


def car_value(attr: str) -> float | None:
  """The car's own torque value from opendbc, which custom tuning replaces."""
  CP = ui_state.CP
  if CP is None or CP.lateralTuning.which() != 'torque':
    return None
  return getattr(CP.lateralTuning.torque, attr)


def draw_centered(text: str, font: rl.Font, font_size: int, center_x: float, center_y: float, color: rl.Color):
  width = measure_text_cached(font, text, font_size).x
  rl.draw_text_ex(font, text, rl.Vector2(center_x - width / 2, center_y - font_size * FONT_SCALE / 2), font_size, 0, color)


class NudgeZone(Widget):
  """Tap to nudge once, hold to keep nudging."""

  def __init__(self, glyph: str, on_nudge: Callable[[], None]):
    super().__init__()
    self._glyph = glyph
    self._on_nudge = on_nudge
    self._font = gui_app.font(FontWeight.BOLD)
    self._next_repeat: float | None = None
    self._repeated = False
    self.set_click_callback(self._on_click)

  def _handle_mouse_press(self, mouse_pos):
    super()._handle_mouse_press(mouse_pos)
    self._next_repeat = rl.get_time() + HOLD_DELAY
    self._repeated = False

  def _on_click(self):
    # a hold already nudged, so its release shouldn't nudge again
    if not self._repeated:
      self._on_nudge()

  def _update_state(self):
    super()._update_state()
    if not self.is_pressed:
      self._next_repeat = None
    elif self._next_repeat is not None and rl.get_time() >= self._next_repeat:
      self._on_nudge()
      self._repeated = True
      self._next_repeat += 1 / REPEAT_RATE

  def _render(self, rect):
    if self.is_pressed and self.enabled:
      rl.draw_rectangle_rounded(rl.Rectangle(rect.x + 20, rect.y, rect.width - 40, rect.height), 0.3, 10, CHIP_BG)
    draw_centered(self._glyph, self._font, 96, rect.x + rect.width / 2, rect.y + rect.height / 2,
                  LABEL_COLOR if self.enabled else DISABLED_COLOR)


class Chip(Widget):
  def __init__(self, on_click: Callable[[], None]):
    super().__init__()
    self.text = ""
    self._font = gui_app.font(FontWeight.MEDIUM)
    self.set_click_callback(on_click)

  def _render(self, rect):
    rl.draw_rectangle_rounded(rect, 1.0, 10, CHIP_PRESSED_BG if self.is_pressed and self.enabled else CHIP_BG)
    draw_centered(self.text, self._font, 32, rect.x + rect.width / 2, rect.y + rect.height / 2,
                  LABEL_COLOR if self.enabled else DISABLED_COLOR)


class TorqueValuePicker(BigDialogBase):
  """Full screen -/+ editor. Every change is written to params right away."""

  def __init__(self, title: str, key: str, car_attr: str, min_value: float, max_value: float, step: float,
               editable: Callable[[], bool], change_callback: Callable[[], None]):
    super().__init__()
    self._title = title
    self._key = key
    self._car_attr = car_attr
    # whole thousandths, so repeated steps never drift
    self._min = round(min_value * 1000)
    self._max = round(max_value * 1000)
    self._milli = self._min
    self._car_milli: int | None = None
    self._step_idx = STEPS.index(step)
    self._editable = editable
    self._change_callback = change_callback
    self._title_font = gui_app.font(FontWeight.MEDIUM)
    self._value_font = gui_app.font(FontWeight.BOLD)

    self._minus = self._child(NudgeZone("-", lambda: self._nudge(-1)))
    self._plus = self._child(NudgeZone("+", lambda: self._nudge(1)))
    self._step_chip = self._child(Chip(self._cycle_step))
    self._car_chip = self._child(Chip(lambda: self._set(self._car_milli)))
    self._car_chip.set_visible(lambda: self._car_milli is not None)
    for widget in (self._minus, self._plus, self._step_chip, self._car_chip):
      widget.set_enabled(lambda: self.enabled and not self.is_dismissing and self._editable())

  def show_event(self):
    super().show_event()
    self._milli = round(float(ui_state.params.get(self._key, return_default=True)) * 1000)
    car_val = car_value(self._car_attr)
    self._car_milli = None if car_val is None else round(car_val * 1000)

  def _set(self, milli: int | None):
    if milli is None:
      return
    milli = max(self._min, min(self._max, milli))
    if milli != self._milli:
      self._milli = milli
      # block: the card re-reads it right away, and a queued write isn't on disk yet
      ui_state.params.put(self._key, milli / 1000, block=True)
      self._change_callback()

  def _nudge(self, direction: int):
    self._set(nudge(self._milli, round(STEPS[self._step_idx] * 1000), direction))

  def _cycle_step(self):
    self._step_idx = (self._step_idx + 1) % len(STEPS)

  def _render(self, rect):
    center_x = rect.x + rect.width / 2
    draw_centered(self._title, self._title_font, 32, center_x, rect.y + 36, GREY)
    draw_centered(f"{self._milli / 1000:.3f}", self._value_font, 90, center_x, rect.y + VALUE_Y,
                  LABEL_COLOR if self._editable() else DISABLED_COLOR)

    zone_y = rect.y + VALUE_Y - 70
    self._minus.render(rl.Rectangle(rect.x, zone_y, ZONE_WIDTH, 140))
    self._plus.render(rl.Rectangle(rect.x + rect.width - ZONE_WIDTH, zone_y, ZONE_WIDTH, 140))

    chip_y = rect.y + rect.height - CHIP_HEIGHT - 10
    self._step_chip.text = f"step {STEPS[self._step_idx]:g}"
    if self._car_chip.is_visible:
      self._car_chip.text = f"car {self._car_milli / 1000:.3f}"
      self._step_chip.render(rl.Rectangle(center_x - CHIP_WIDTH - 10, chip_y, CHIP_WIDTH, CHIP_HEIGHT))
      self._car_chip.render(rl.Rectangle(center_x + 10, chip_y, CHIP_WIDTH, CHIP_HEIGHT))
    else:
      self._step_chip.render(rl.Rectangle(center_x - CHIP_WIDTH / 2, chip_y, CHIP_WIDTH, CHIP_HEIGHT))


class TorqueValueButton(BigButton):
  def __init__(self, title: str, key: str, car_attr: str, min_value: float, max_value: float, step: float,
               editable: Callable[[], bool], description: str):
    super().__init__(title, " ", description=description)
    self._key = key
    self._picker = TorqueValuePicker(title, key, car_attr, min_value, max_value, step, editable, self.refresh)
    self.set_click_callback(lambda: gui_app.push_widget(self._picker))

  def _get_label_font_size(self):
    return 42

  def refresh(self):
    value = float(ui_state.params.get(self._key, return_default=True))
    applies = "live" if ui_state.params.get_bool(REALTIME) else "next drive"
    self.set_value(f"{value:.3f}  {applies}")


class TorqueTuningLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._on: dict[str, bool] = {}
    self._toggles: dict[str, BigToggle] = {}

    self._enforce = self._toggle("enforce torque control", ENFORCE,
                                 "Steer with the torque lateral controller. Every other setting here needs it. Applies on the next drive.")
    custom = self._toggle("custom tuning", CUSTOM,
                          "Use the lateral acceleration factor and friction set here instead of the car's values from opendbc.")
    realtime = self._toggle("real-time tuning", REALTIME,
                            "Apply lateral acceleration factor and friction while driving, overriding Self-Tune. " +
                            "Otherwise they apply on the next drive.")
    editable = lambda: self._on.get(REALTIME, False) or ui_state.is_offroad()
    self._lat_accel = TorqueValueButton("lat accel factor", LAT_ACCEL_FACTOR, "latAccelFactor", 0.1, 5.0, 0.01, editable,
                                        "Lateral acceleration per unit of steering torque. Lower values steer harder.")
    self._friction = TorqueValueButton("friction", FRICTION, "friction", 0.0, 1.0, 0.001, editable,
                                       "Extra torque to overcome steering friction. Too much can make the wheel ping-pong.")
    self_tune = self._toggle("self-tune", SELF_TUNE,
                             "Enables self-tune for Torque lateral control for platforms that do not use Torque lateral control by default.")
    relaxed = self._toggle("relaxed self-tune", RELAXED,
                           "Less strict settings when using Self-Tune. This allows torqued to be more forgiving when learning values.")
    jerk = self._toggle("lateral jerk controller", JERK,
                        "Looks ahead at planned steering to reduce sudden corrections, so the wheel moves more smoothly through turns.")
    self._version = BigMultiToggle("tune version", list(TUNE_VERSIONS), select_callback=self._on_version,
                                   description="Select the version of Torque Control Tune to use.")

    def when(*keys: str) -> Callable[[], bool]:
      return lambda: all(self._on.get(key, False) for key in keys)

    # like sunnylink: everything past "enforce" needs it, and conditional items appear right of what reveals them
    for item in (custom, self_tune, jerk, self._version):
      item.set_visible(when(ENFORCE))
    for item in (realtime, self._lat_accel, self._friction):
      item.set_visible(when(ENFORCE, CUSTOM))
    relaxed.set_visible(when(ENFORCE, SELF_TUNE))

    self._enforce.set_enabled(lambda: ui_state.is_offroad() and torque_allowed() and not self._on.get(NNLC, False))
    jerk.set_enabled(lambda: ui_state.is_offroad() and not self._on.get(NNLC, False))
    for item in (custom, realtime, self_tune, relaxed, self._version):
      item.set_enabled(ui_state.is_offroad)
    self._lat_accel.set_enabled(editable)
    self._friction.set_enabled(editable)

    self._scroller.add_widgets([
      self._enforce,
      custom,
      realtime,
      self._lat_accel,
      self._friction,
      self_tune,
      relaxed,
      jerk,
      self._version,
    ])

    ui_state.add_offroad_transition_callback(self._refresh)

  def _toggle(self, title: str, key: str, description: str) -> BigToggle:
    toggle = BigToggle(title, toggle_callback=lambda checked: self._on_toggle(key, checked), description=description)
    self._toggles[key] = toggle
    return toggle

  def show_event(self):
    super().show_event()
    self._refresh()

  def _on_toggle(self, key: str, checked: bool):
    ui_state.params.put_bool(key, checked, block=True)
    if key == SELF_TUNE and not checked:
      ui_state.params.remove(RELAXED)
    self._refresh()

  def _on_version(self, label: str):
    version = TUNE_VERSIONS[label]
    if version is None:
      ui_state.params.remove(TUNE_VERSION)
    else:
      ui_state.params.put(TUNE_VERSION, version, block=True)

  def _refresh(self):
    params = ui_state.params
    self._on = {key: params.get_bool(key) for key in (*self._toggles, NNLC)}
    for key, toggle in self._toggles.items():
      toggle.set_checked(self._on[key])
    self._enforce.set_value(self._enforce_hint())
    self._lat_accel.refresh()
    self._friction.refresh()

    current = params.get(TUNE_VERSION)
    self._version.set_value(next((label for label, version in TUNE_VERSIONS.items()
                                  if version is not None and current is not None and math.isclose(version, current)), "default"))

  def _enforce_hint(self) -> str:
    if ui_state.CP is None:
      return "start the car once"
    if not torque_allowed():
      return "not for this car"
    if self._on[NNLC]:
      return "turn off NNLC first"
    return ""


class TorqueTuningBigButton(SettingsBigButton):
  def __init__(self):
    super().__init__("torque", "", gui_app.texture(ICON, 64, 64))
    self._panel = TorqueTuningLayoutMici()
    self.set_click_callback(lambda: gui_app.push_widget(self._panel))
