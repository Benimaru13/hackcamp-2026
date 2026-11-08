"""The instruction panel is drawn with numpy/cv2 only, so it can be tested here
without a camera: content, placement, alpha, and that it survives odd sizes."""
import numpy as np

from calibrate_profile import Profile, TremorProfile
from gesture_cursor import Config
from instruction_panel import (_gestures, _states, _summary, draw_instruction_panel,
                               draw_manual, frosted, in_rect)


def _frame(w=1280, h=720):
    """A dark gradient, roughly what a dim room looks like to the camera."""
    y, x = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), np.uint8)
    img[..., 0] = (x * 120 // max(w - 1, 1) + 40).astype(np.uint8)
    img[..., 1] = (y * 110 // max(h - 1, 1) + 35).astype(np.uint8)
    img[..., 2] = 60
    return img


# --- content: the panel has to actually teach the app ------------------------
def test_states_explain_armed_and_active():
    states = {name: meaning for name, _color, meaning in _states()}
    assert set(states) == {"ARMED", "ACTIVE"}
    assert "untouched" in states["ARMED"]
    assert "computer" in states["ACTIVE"]


def test_every_gesture_says_what_it_does():
    rows = _gestures(Config())
    assert len(rows) >= 6
    for num, gesture, _hold, effect in rows:
        assert num and gesture and effect, f"incomplete row: {num} {gesture} {effect}"
    effects = " ".join(row[3] for row in rows)
    for expected in ("take control", "cursor", "click", "scroll", "switch space",
                     "release"):
        assert expected in effects


def test_gesture_holds_come_from_the_config_this_run_uses():
    cfg = Config()
    cfg.arm_hold = 1.23
    cfg.dwell_time = 3.21
    cfg.switch_hold = 0.99
    rows = _gestures(cfg)
    assert "1.2" in rows[0][2]
    assert "3.2" in rows[2][2]
    assert "1.0" in rows[4][2]


def test_summary_reports_a_measurement_and_a_bare_default():
    steady = Profile.from_measurement(palm=0.04, jitter_px=6.0, distance_ft=8.0)
    shaky = Profile.from_measurement(
        palm=0.04, jitter_px=6.0, distance_ft=8.0,
        tremor=TremorProfile(freq_hz=5.0, amplitude_px=6.0, rms_px=6.0, score=37))
    assert "5.0 Hz" in _summary(shaky)
    assert "shake" in _summary(steady) and "Hz" not in _summary(steady)
    assert _summary(None)


# --- drawing ---------------------------------------------------------------
def test_panel_keeps_shape_and_type():
    img = _frame()
    out = draw_instruction_panel(img, None, Config(), 1.0)
    assert out.shape == img.shape
    assert out.dtype == np.uint8


def test_panel_sits_in_the_bottom_band():
    img = _frame()
    out = draw_instruction_panel(img, None, Config(), 1.0)
    h = img.shape[0]
    assert np.abs(out[h // 2:].astype(int) - img[h // 2:].astype(int)).sum() > 0
    assert np.array_equal(out[:h // 4], img[:h // 4])


def test_centred_corner_is_used_by_the_calibration_card():
    img = _frame()
    out = draw_instruction_panel(img, None, Config(), 1.0, corner="center")
    assert np.abs(out.astype(int) - img.astype(int)).sum() > 0


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


def test_panel_renders_a_measurement():
    prof = Profile.from_measurement(palm=0.04, jitter_px=6.0, distance_ft=8.0)
    assert draw_instruction_panel(_frame(), prof, Config(), 1.0).shape[0] == 720


def test_frosted_blurs_the_backdrop_it_covers():
    img = _frame()
    out = frosted(img.copy(), (100, 400, 600, 640), alpha=1.0, blur=25)
    assert not np.array_equal(out[500, 300], img[500, 300])
    assert np.array_equal(out[:300], img[:300])


# --- the popup manual ------------------------------------------------------
def test_manual_returns_an_ok_button_inside_the_frame():
    img = _frame()
    out, ok = draw_manual(img, None, Config())
    assert out.shape == img.shape
    assert 0 <= ok[0] < ok[2] <= img.shape[1]
    assert 0 <= ok[1] < ok[3] <= img.shape[0]
    assert (ok[2] - ok[0]) > 40 and (ok[3] - ok[1]) > 20


def test_manual_dims_the_feed_behind_the_card():
    img = _frame()
    out, _ = draw_manual(img, None, Config())
    assert int(out[0, 0].sum()) < int(img[0, 0].sum())


def test_manual_hover_lights_the_button():
    img = _frame()
    plain, ok = draw_manual(img, None, Config(), hover=False)
    hot, ok_hot = draw_manual(img, None, Config(), hover=True)
    assert ok == ok_hot, "the button must not move under the pointer"
    x0, y0, x1, y1 = ok
    box = (slice(y0 + 4, y1 - 4), slice(x0 + 6, x1 - 6))
    assert np.abs(hot[box].astype(int) - plain[box].astype(int)).sum() > 0


def test_in_rect_is_the_hit_test_the_click_uses():
    rect = (10, 20, 110, 70)
    assert in_rect(rect, 60, 40)
    assert not in_rect(rect, 5, 40)
    assert not in_rect(rect, 60, 75)


def test_footer_text_never_touches_the_ok_button():
    """The hint line must clear the button by a real gap at any frame size.

    The button is drawn shifted down for the measurement: its own antialiased
    rim sits a pixel above `ok[1]`, which would otherwise be counted as text.
    """
    import numpy as _np
    from gesture_cursor import Config as _Config
    import instruction_panel as ip
    real = ip._ok_button
    try:
        for h, w in ((720, 1280), (1080, 1920)):
            s = h / 720.0
            frame = _np.full((h, w, 3), 40, _np.uint8)
            ip._ok_button = lambda img, r, _s, hover: real(
                img, (r[0], r[1] + 80, r[2], r[3] + 80), _s, hover)
            out, ok = ip.draw_manual(frame, None, _Config(), hover=False)
            rows = _np.where((out[:ok[1], :, :].mean(axis=2) > 140).any(axis=1))[0]
            assert len(rows), f"{w}x{h}: the footer did not render"
            gap = ok[1] - int(rows.max()) - 1
            assert gap >= int(20 * s), f"{w}x{h}: only {gap} px between footer and button"
    finally:
        ip._ok_button = real
