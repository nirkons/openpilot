"""Exercise the torque card's logic headlessly against fakes of the mici UI.

The fakes copy the upstream constructor signatures, so wrong keyword arguments
fail here too. Every params access must use a key declared in PARAM_KEYS, which
is the list patch_torque_card.py checks against the upstream params.
"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

CARD = Path(__file__).resolve().parent / "mici" / "torque_tuning.py"
STATE = {"offroad": True, "time": 0.0}
DEFAULTS = {"TorqueParamsOverrideLatAccelFactor": 2.5, "TorqueParamsOverrideFriction": 0.1, "TorqueControlTune": 0.0}


class FakeParams:
    def __init__(self, allowed, values=None):
        self.allowed = allowed
        self.values = dict(values or {})
        # Like the real Params, a write without block=True is only queued, and reads
        # don't see it yet. Here it never lands, so every write must block.
        self.queued = {}

    def _check(self, key):
        assert key in self.allowed, f"{key} is not in PARAM_KEYS"

    def get_bool(self, key, default=False):
        self._check(key)
        return bool(self.values.get(key, default))

    def get(self, key, block=False, return_default=False):
        self._check(key)
        return self.values.get(key, DEFAULTS.get(key) if return_default else None)

    def put(self, key, dat, block=False):
        self._check(key)
        (self.values if block else self.queued)[key] = dat

    def put_bool(self, key, val, block=False):
        self.put(key, val, block)

    def remove(self, key):
        self._check(key)
        self.values.pop(key, None)


class Widget:
    def __init__(self):
        self._enabled = True
        self._is_visible = True
        self._rect = types.SimpleNamespace(x=0, y=0, width=0, height=0)
        self._click_callback = None
        self._children = []
        self.is_pressed = False

    @property
    def enabled(self):
        return self._enabled() if callable(self._enabled) else self._enabled

    def set_enabled(self, enabled):
        self._enabled = enabled

    @property
    def is_visible(self):
        return self._is_visible() if callable(self._is_visible) else self._is_visible

    def set_visible(self, visible):
        self._is_visible = visible

    def set_click_callback(self, click_callback):
        self._click_callback = click_callback

    def _child(self, widget):
        self._children.append(widget)
        return widget

    def show_event(self):
        for child in self._children:
            child.show_event()

    def render(self, rect=None):
        if rect is not None:
            self._rect = rect
        self._update_state()
        if self.is_visible:
            self._render(self._rect)

    def _update_state(self):
        pass

    def _handle_mouse_press(self, mouse_pos, /):
        pass

    def _handle_mouse_release(self, mouse_pos, /):
        if self._click_callback:
            self._click_callback()

    def tap(self):
        # Widget.render only delivers touches to enabled widgets
        assert self.enabled and self.is_visible, "tapped a disabled or hidden widget"
        self._handle_mouse_press(None)
        self._handle_mouse_release(None)


class BigButton(Widget):
    def __init__(self, text, value="", icon=None, scroll=False, *, description="", description_icon=None):
        super().__init__()
        self.text = text
        self.value = value
        self._get_label_font_size()

    def _get_label_font_size(self):
        return 48

    def set_value(self, value):
        self.value = value


class BigToggle(BigButton):
    def __init__(self, text, value="", initial_state=False, toggle_callback=None, *, description="", description_icon=None):
        super().__init__(text, value, "", description=description, description_icon=description_icon)
        self._checked = initial_state
        self._toggle_callback = toggle_callback

    def set_checked(self, checked):
        self._checked = checked

    def _handle_mouse_release(self, mouse_pos, /):
        super()._handle_mouse_release(mouse_pos)
        self._checked = not self._checked
        if self._toggle_callback:
            self._toggle_callback(self._checked)


class BigMultiToggle(BigToggle):
    def __init__(self, text, options, toggle_callback=None, select_callback=None, *, description="", description_icon=None):
        super().__init__(text, "", toggle_callback=toggle_callback, description=description, description_icon=description_icon)
        self._options = options
        self._select_callback = select_callback
        self.set_value(self._options[0])

    def _handle_mouse_release(self, mouse_pos, /):
        super()._handle_mouse_release(mouse_pos)
        self.set_value(self._options[(self._options.index(self.value) + 1) % len(self._options)])
        if self._select_callback:
            self._select_callback(self.value)


class BigDialogBase(Widget):
    is_dismissing = False


class NavScroller(Widget):
    def __init__(self, **kwargs):
        super().__init__()
        self._scroller = types.SimpleNamespace(items=[])
        self._scroller.add_widgets = self._scroller.items.extend


class GuiApp:
    def __init__(self):
        self.pushed = []

    def font(self, font_weight=None):
        return font_weight

    def texture(self, asset_path, width=None, height=None):
        return asset_path

    def push_widget(self, widget):
        self.pushed.append(widget)
        widget.show_event()


gui_app = GuiApp()
ui_state = types.SimpleNamespace(params=None, CP=None, is_offroad=lambda: STATE["offroad"],
                                 add_offroad_transition_callback=lambda callback: None)
SteerControlType = types.SimpleNamespace(angle="angle", torque="torque")


def ev6_cp(steer_control_type="torque"):
    torque = types.SimpleNamespace(latAccelFactor=3.2, friction=0.005)
    return types.SimpleNamespace(steerControlType=steer_control_type,
                                 lateralTuning=types.SimpleNamespace(which=lambda: "torque", torque=torque))


def load_card():
    rl = types.ModuleType("pyray")
    rl.__getattr__ = lambda name: (lambda *args, **kwargs: types.SimpleNamespace(x=0, y=0, width=0, height=0))
    rl.get_time = lambda: STATE["time"]
    leaves = {
        "pyray": rl,
        "opendbc.car.structs": {"car": types.SimpleNamespace(CarParams=types.SimpleNamespace(SteerControlType=SteerControlType))},
        "openpilot.selfdrive.ui.mici.layouts.settings.settings": {"SettingsBigButton": type("SettingsBigButton", (BigButton,), {})},
        "openpilot.selfdrive.ui.mici.widgets.button": {"BigButton": BigButton, "BigToggle": BigToggle,
                                                       "BigMultiToggle": BigMultiToggle, "LABEL_COLOR": None},
        "openpilot.selfdrive.ui.mici.widgets.dialog": {"BigDialogBase": BigDialogBase},
        "openpilot.selfdrive.ui.ui_state": {"ui_state": ui_state},
        "openpilot.system.ui.lib.application": {"gui_app": gui_app, "FONT_SCALE": 1.16,
                                                "FontWeight": types.SimpleNamespace(BOLD="bold", MEDIUM="medium")},
        "openpilot.system.ui.lib.text_measure": {"measure_text_cached": lambda *args: types.SimpleNamespace(x=0, y=0)},
        "openpilot.system.ui.widgets": {"Widget": Widget},
        "openpilot.system.ui.widgets.scroller": {"NavScroller": NavScroller},
    }
    modules = {}
    for name, contents in leaves.items():
        # parent packages too, so nothing real is imported from the checkout
        for i in range(1, name.count(".") + 1):
            modules.setdefault(name.rsplit(".", i)[0], types.ModuleType(name.rsplit(".", i)[0]))
        modules[name] = contents if isinstance(contents, types.ModuleType) else types.ModuleType(name)
        modules[name].__dict__.update({} if isinstance(contents, types.ModuleType) else contents)

    spec = importlib.util.spec_from_file_location("ev6_torque_tuning", CARD)
    card = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, modules):
        spec.loader.exec_module(card)
    return card


class TorqueTuningCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.card = load_card()

    def setUp(self):
        STATE.update(offroad=True, time=0.0)
        gui_app.pushed.clear()
        ui_state.CP = ev6_cp()
        self.params = ui_state.params = FakeParams(self.card.PARAM_KEYS)
        self.addCleanup(lambda: self.assertEqual(self.params.queued, {}, "a write didn't block"))

    def open_panel(self, **values):
        self.params.values.update(values)
        self.card.TorqueTuningBigButton().tap()
        return gui_app.pushed[-1]

    def visible(self, panel):
        return [item.text for item in panel._scroller.items if item.is_visible]

    def test_nudge_lands_on_step_multiples(self):
        nudge = self.card.nudge
        self.assertEqual(nudge(2347, 10, 1), 2350)
        self.assertEqual(nudge(2347, 10, -1), 2340)
        self.assertEqual(nudge(2350, 10, -1), 2340)
        self.assertEqual(nudge(2350, 100, 1), 2400)
        self.assertEqual(nudge(5, 1, -1), 4)

    def test_settings_reveal_like_sunnylink(self):
        panel = self.open_panel()
        self.assertEqual(self.visible(panel), ["enforce torque control"])
        panel._enforce.tap()
        self.assertEqual(self.visible(panel), ["enforce torque control", "custom tuning", "self-tune",
                                               "lateral jerk controller", "tune version"])
        panel._toggles["CustomTorqueParams"].tap()
        panel._toggles["LiveTorqueParamsToggle"].tap()
        self.assertEqual(self.visible(panel), ["enforce torque control", "custom tuning", "real-time tuning",
                                               "lat accel factor", "friction", "self-tune", "relaxed self-tune",
                                               "lateral jerk controller", "tune version"])
        self.assertTrue(self.params.values["EnforceTorqueControl"])
        self.assertTrue(self.params.values["CustomTorqueParams"])

    def test_lat_accel_factor_steps_and_clamps(self):
        panel = self.open_panel(EnforceTorqueControl=True, CustomTorqueParams=True, TorqueParamsOverrideLatAccelFactor=3.2)
        panel._lat_accel.tap()
        picker = gui_app.pushed[-1]
        picker._plus.tap()
        self.assertEqual(self.params.values["TorqueParamsOverrideLatAccelFactor"], 3.21)
        self.assertEqual(panel._lat_accel.value, "3.210  next drive")
        picker._step_chip.tap()  # 0.01 -> 0.1
        for _ in range(40):
            picker._minus.tap()
        self.assertEqual(self.params.values["TorqueParamsOverrideLatAccelFactor"], 0.1)
        picker._step_chip.tap()  # 0.1 -> 0.001
        picker._plus.tap()
        self.assertEqual(self.params.values["TorqueParamsOverrideLatAccelFactor"], 0.101)

    def test_car_chip_restores_ev6_stock_values(self):
        panel = self.open_panel(EnforceTorqueControl=True, CustomTorqueParams=True)
        panel._friction.tap()
        picker = gui_app.pushed[-1]
        self.assertTrue(picker._car_chip.is_visible)
        picker._car_chip.tap()
        self.assertEqual(self.params.values["TorqueParamsOverrideFriction"], 0.005)
        picker._minus.tap()  # friction starts on the 0.001 step
        self.assertEqual(self.params.values["TorqueParamsOverrideFriction"], 0.004)
        panel._lat_accel.tap()
        gui_app.pushed[-1]._car_chip.tap()
        self.assertEqual(self.params.values["TorqueParamsOverrideLatAccelFactor"], 3.2)

    def test_hold_repeats_without_extra_step_on_release(self):
        panel = self.open_panel(EnforceTorqueControl=True, CustomTorqueParams=True, TorqueParamsOverrideFriction=0.005)
        panel._friction.tap()
        plus = gui_app.pushed[-1]._plus
        plus._handle_mouse_press(None)
        plus.is_pressed = True
        for t in (0.1, 0.4, 0.4 + 1 / 12):
            STATE["time"] = t
            plus.render()
        plus.is_pressed = False
        plus._handle_mouse_release(None)
        self.assertEqual(self.params.values["TorqueParamsOverrideFriction"], 0.007)
        plus.tap()  # a plain tap after a hold still counts
        self.assertEqual(self.params.values["TorqueParamsOverrideFriction"], 0.008)

    def test_onroad_values_need_real_time_tuning(self):
        panel = self.open_panel(EnforceTorqueControl=True, CustomTorqueParams=True)
        STATE["offroad"] = False
        self.assertFalse(panel._lat_accel.enabled)
        self.assertFalse(panel._toggles["CustomTorqueParams"].enabled)
        self.assertFalse(panel._enforce.enabled)

        STATE["offroad"] = True
        panel._toggles["TorqueParamsOverrideEnabled"].tap()
        STATE["offroad"] = False
        self.assertTrue(panel._lat_accel.enabled)
        self.assertEqual(panel._lat_accel.value, "2.500  live")
        panel._lat_accel.tap()
        self.assertTrue(gui_app.pushed[-1]._plus.enabled)

    def test_self_tune_off_clears_relaxed(self):
        panel = self.open_panel(EnforceTorqueControl=True, LiveTorqueParamsToggle=True, LiveTorqueParamsRelaxedToggle=True)
        panel._toggles["LiveTorqueParamsToggle"].tap()
        self.assertNotIn("LiveTorqueParamsRelaxedToggle", self.params.values)
        self.assertNotIn("relaxed self-tune", self.visible(panel))

    def test_enforce_explains_why_it_is_disabled(self):
        panel = self.open_panel(NeuralNetworkLateralControl=True)
        self.assertFalse(panel._enforce.enabled)
        self.assertEqual(panel._enforce.value, "turn off NNLC first")

        ui_state.CP = None
        panel.show_event()
        self.assertEqual(panel._enforce.value, "start the car once")

        ui_state.CP = ev6_cp("angle")
        self.params.values.pop("NeuralNetworkLateralControl")
        panel.show_event()
        self.assertFalse(panel._enforce.enabled)
        self.assertEqual(panel._enforce.value, "not for this car")

    def test_tune_version_cycles_like_sunnylink(self):
        panel = self.open_panel(EnforceTorqueControl=True, TorqueControlTune=0.0)
        self.assertEqual(panel._version.value, "v0.0")
        panel._version.tap()
        self.assertEqual(panel._version.value, "default")
        self.assertNotIn("TorqueControlTune", self.params.values)
        panel._version.tap()
        self.assertEqual(self.params.values["TorqueControlTune"], 1.0)
        panel._version.tap()
        self.assertEqual(self.params.values["TorqueControlTune"], 0.0)


if __name__ == "__main__":
    unittest.main()
