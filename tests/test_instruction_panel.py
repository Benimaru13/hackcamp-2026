"""The instruction panel is drawn with numpy/cv2 only, so it can be tested here
without a camera: shape, alpha, and that it draws where it says it does."""
import numpy as np

from calibrate_profile import Profile, TremorProfile
from gesture_cursor import Config
from instruction_panel import draw_instruction_panel, frosted


def _frame(w=1280, h=720):
    """A dark gradient, roughly what a dim room looks like to the camera."""
    y, x = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), np.uint8)
    img[..., 0] = (x * 120 // max(w - 1, 1) + 40).astype(np.uint8)
    img[..., 1] = (y * 110 // max(h - 1, 1) + 35).astype(np.uint8)
    img[..., 2] = 60
    return img


def test_panel_keeps_shape_and_type():
    img = _frame()
    out = draw_instruction_panel(img, None, Config(), 1.0)
    assert out.shape == img.shape
    assert out.dtype == np.uint8


def test_panel_draws_in_the_bottom_left():
    img = _frame()
    out = draw_instruction_panel(img, None, Config(), 1.0)
    h, w = img.shape[:2]
    corner = (slice(h // 2, h), slice(0, w // 2))
    assert np.abs(out[corner].astype(int) - img[corner].astype(int)).sum() > 0
    assert np.array_equal(out[:h // 4, w // 2:], img[:h // 4, w // 2:])


def test_zero_alpha_is_a_no_op():
    img = _frame()
    assert draw_instruction_panel(img, None, Config(), 0.0) is img


def test_partial_alpha_still_draws():
    img = _frame()
    out = draw_instruction_panel(img, None, Config(), 0.4)
    assert np.abs(out.astype(int) - img.astype(int)).sum() > 0


def test_panel_survives_a_tiny_frame():
    img = _frame(320, 180)
    out = draw_instruction_panel(img, None, Config(), 1.0)
    assert out.shape == img.shape


def test_panel_renders_a_measurement_and_a_tremor():
    steady = Profile.from_measurement(palm=0.04, jitter_px=6.0, distance_ft=8.0)
    shaky = Profile.from_measurement(
        palm=0.04, jitter_px=6.0, distance_ft=8.0,
        tremor=TremorProfile(freq_hz=5.0, amplitude_px=6.0, rms_px=6.0, score=37))
    for prof in (steady, shaky):
        out = draw_instruction_panel(_frame(), prof, Config(), 1.0)
        assert out.shape[0] == 720


def test_panel_uses_the_holds_this_run_actually_uses():
    cfg = Config()
    cfg.arm_hold = 1.23
    cfg.dwell_time = 3.21
    cfg.switch_hold = 0.99
    from instruction_panel import _gestures
    holds = [row[2] for row in _gestures(cfg)]
    assert holds[0] == "1.2 s"
    assert holds[2] == "3.2 s"
    assert holds[3] == "1.0 s"


def test_frosted_blurs_the_backdrop_it_covers():
    img = _frame()
    box = (100, 400, 600, 640)
    out = frosted(img.copy(), box, alpha=1.0, blur=25)
    assert not np.array_equal(out[500, 300], img[500, 300])


def test_frosted_leaves_pixels_outside_the_box_alone():
    img = _frame()
    out = frosted(img.copy(), (100, 400, 600, 640), alpha=1.0, blur=25)
    assert np.array_equal(out[:300], img[:300])
