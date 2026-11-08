"""overlay.py -- the full-screen state halo.

The state cue has to be readable when you are 10 ft from the laptop and looking at
the desktop, so the real cue is a glowing border around the whole screen. The
border inside the camera preview stays only as a fallback and as a debugging aid.

Why a separate Qt window: OpenCV's HighGUI and tkinter cannot make a window that is
transparent, always on top *and* click-through, which is what this needs -- the
border must never eat a click or take keyboard focus. Qt can:

    FramelessWindowHint | WindowStaysOnTopHint | WindowDoesNotAcceptFocus
    | WindowTransparentForInput   -> mouse and keyboard go to the app underneath
    WA_TranslucentBackground      -> only the painted border is visible
    WA_ShowWithoutActivating      -> appearing never steals focus

The window covers the union of every attached display and paints one border per
display, so a multi-monitor demo is framed too.

Nothing here is required: if PySide6 is missing or Qt cannot open a window,
``ScreenGlow.enabled`` stays False, ``reason`` explains why, and app.py keeps
drawing the glow inside the preview. Every method is safe to call when disabled.
"""
from __future__ import annotations

# RGB (the preview HUD uses BGR), matching COLORS in app.py.
STATE_RGB = {
    "off": (120, 120, 120),
    "armed": (255, 176, 0),      # amber
    "active": (90, 255, 120),    # green
}

# (inset from the screen edge, stroke width, alpha): wide and faint further in,
# brightest at the very edge. Reads as a glow without a real blur pass, which
# would cost a full-screen image filter every frame.
BANDS = ((0, 7, 0.80), (8, 12, 0.38), (22, 18, 0.16), (42, 26, 0.07))


def _window_class():
    """Import Qt lazily and build the widget class, so this module stays
    importable on a machine that never installed PySide6."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
    from PySide6.QtWidgets import QWidget

    class GlowWindow(QWidget):
        def __init__(self):
            super().__init__(None,
                             Qt.FramelessWindowHint
                             | Qt.WindowStaysOnTopHint
                             | Qt.WindowDoesNotAcceptFocus
                             | Qt.WindowTransparentForInput
                             | Qt.NoDropShadowWindowHint)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.setFocusPolicy(Qt.NoFocus)
            self.color = QColor(*STATE_RGB["armed"])
            self.strength = 0.0
            self._rects = []
            self.retarget()
            self.hide()

        def retarget(self):
            """Cover every display; keep one local rect per display for painting."""
            screens = QGuiApplication.screens()
            rects = [s.geometry() for s in screens] or [QRect(0, 0, 1440, 900)]
            union = QRect(rects[0])
            for r in rects[1:]:
                union = union.united(r)
            self._rects = [r.translated(-union.topLeft()) for r in rects]
            self.setGeometry(union)

        def repaint_state(self, key, strength):
            self.color = QColor(*STATE_RGB.get(key, STATE_RGB["off"]))
            self.strength = max(0.0, min(1.0, float(strength)))
            self.update()

        def paintEvent(self, _event):        # noqa: N802  (Qt's name)
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setBrush(Qt.NoBrush)
            for inset, width, alpha in BANDS:
                c = QColor(self.color)
                c.setAlphaF(max(0.0, min(1.0, alpha * self.strength)))
                p.setPen(QPen(c, width))
                for r in self._rects:
                    rr = r.adjusted(inset, inset, -inset, -inset)
                    if rr.width() > 2 and rr.height() > 2:
                        p.drawRect(rr)
            p.end()

    return GlowWindow


class ScreenGlow:
    """Owns the QApplication and the halo window. Never raises when drawing."""

    def __init__(self):
        self.enabled = False
        self.reason = ""
        self._app = None
        self._win = None
        self._key = None
        self._strength = -1.0
        try:
            from PySide6.QtWidgets import QApplication
            cls = _window_class()
        except Exception as exc:        # missing PySide6, no display, ...
            self.reason = f"PySide6/Qt unavailable ({exc})"
            return
        try:
            self._app = QApplication.instance() or QApplication([])
            self._win = cls()
        except Exception as exc:        # pragma: no cover - platform dependent
            self.reason = f"Qt could not create the window ({exc})"
            self._app = None
            return
        self.enabled = True

    def show_state(self, state, strength=1.0):
        """Draw the halo for ``state`` (a ControlState or its string value)."""
        if not self.enabled:
            return
        key = getattr(state, "value", str(state))
        if key == "off":
            if self._key != "off":
                self._win.hide()        # OFF: no cue on screen at all
                self._key = "off"
                self.pump()
            return
        if self._key in (None, "off"):
            self._win.show()
            self._win.raise_()
        strength = max(0.0, min(1.0, float(strength)))
        if key != self._key or abs(strength - self._strength) >= 0.02:
            self._key, self._strength = key, strength
            self._win.repaint_state(key, strength)
        self.pump()

    def pump(self):
        """Let Qt repaint while our own frame loop owns the thread."""
        if self._app is not None:
            self._app.processEvents()

    def close(self):
        self.enabled = False
        if self._win is not None:
            try:
                self._win.hide()
                self._win.deleteLater()
            except Exception:
                pass
            self._win = None
        self.pump()
