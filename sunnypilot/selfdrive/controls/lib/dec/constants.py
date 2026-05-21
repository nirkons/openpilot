class WMACConstants:
  # Lead detection parameters
  LEAD_WINDOW_SIZE = 6  # Stable detection window
  LEAD_PROB = 0.45  # Balanced threshold for lead detection

  # Slow down detection parameters
  SLOW_DOWN_WINDOW_SIZE = 5  # Responsive but stable
  SLOW_DOWN_PROB = 0.3  # Balanced threshold for slow down scenarios

  # Optimized slow down distance curve - smooth and progressive
  SLOW_DOWN_BP = [0., 10., 20., 30., 40., 50., 55., 60.]
  SLOW_DOWN_DIST = [32., 46., 64., 86., 108., 130., 145., 165.]

  # Slowness detection parameters
  SLOWNESS_WINDOW_SIZE = 10  # Stable slowness detection
  SLOWNESS_PROB = 0.55  # Clear threshold for slowness
  SLOWNESS_CRUISE_OFFSET = 1.025  # Conservative cruise speed offset

  URGENCY_CRITICAL_BOOST_MAX = 1.5

  STOP_HOLD_ARM_FRAMES = 10
  STOP_HOLD_RELEASE_TRAJ_X = 60.0
  STOP_HOLD_RELEASE_TRAJ_FRAMES = 20

  LOW_SPEED_THRESHOLD_KPH = 30.0
  LOW_SPEED_MIN_MODE_DURATION = 20
