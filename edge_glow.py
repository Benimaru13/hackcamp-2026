"""edge_glow.py -- full-screen state border for AirTrack (macOS).

The preview window's border only tells you the state while you are looking at
the preview. This draws a transparent, click-through, always-on-top border
around every screen instead, so ACTIVE (green) is visible from across the room
even when the browser or another app is in front.

The border carries one label in its top-right corner: AUDIO GUIDE ACTIVE or
AUDIO GUIDE MUTED. Whether the app will talk to you is part of the same state --
the rock sign toggles it -- and this halo is the only cue that survives another
app being in front, so the label lives here rather than only in the preview.

macOS only. It uses PyObjC (AppKit + Quartz), which is already installed in the
project venv. On other platforms, or if PyObjC is missing, EdgeGlow silently
does nothing and the app keeps working with the preview border.
"""
from __future__ import annotations

import math
import sys


class EdgeGlow:
    """A hollow border around every screen, driven by the control state."""

    BADGE_ON = "AUDIO GUIDE ACTIVE"
    BADGE_OFF = "AUDIO GUIDE MUTED"

    def __init__(self, enabled=True, width=10.0, radius=18.0):
        self.enabled = bool(enabled)
        self.available = False
        self._windows = []
        self._layers = []          # the pulsing border, one per screen
        self._badges = []          # (pill layer, text layer), one per screen
        self._badge_font = None
        self._state = None
        self._audio = True
        self._colors = {}
        self._CATransaction = None
        if not self.enabled or sys.platform != "darwin":
            return
        try:
            self._setup(width, radius)
            self.available = True
        except Exception as exc:          # never take the app down for a glow
            print(f"[glow] full-screen border unavailable: {exc}")
            self.close()

    # ------------------------------------------------------------------ setup
    def _setup(self, width, radius):
        from AppKit import (
            NSApplication, NSApplicationActivationPolicyAccessory,
            NSBackingStoreBuffered, NSBorderlessWindowMask, NSColor, NSScreen,
            NSScreenSaverWindowLevel, NSView, NSWindow,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorStationary, NSMakeRect,
        )
        from Quartz import CATransaction, CGSizeMake, CALayer

        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        self._CATransaction = CATransaction
        self._colors = {
            "active": NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.33, 1.0, 0.47, 1.0),
            "armed": NSColor.colorWithCalibratedRed_green_blue_alpha_(
                1.0, 0.69, 0.0, 1.0),
        }

        behavior = (NSWindowCollectionBehaviorCanJoinAllSpaces
                    | NSWindowCollectionBehaviorStationary
                    | NSWindowCollectionBehaviorFullScreenAuxiliary)

        for screen in NSScreen.screens():
            frame = screen.frame()
            scale = float(screen.backingScaleFactor())
            window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                frame, NSBorderlessWindowMask, NSBackingStoreBuffered, False)
            self._windows.append(window)
            window.setLevel_(NSScreenSaverWindowLevel)
            window.setOpaque_(False)
            window.setBackgroundColor_(NSColor.clearColor())
            window.setIgnoresMouseEvents_(True)
            window.setHasShadow_(False)
            window.setHidesOnDeactivate_(False)
            window.setCanHide_(False)
            window.setReleasedWhenClosed_(False)
            window.setCollectionBehavior_(behavior)

            view = NSView.alloc().initWithFrame_(
                NSMakeRect(0.0, 0.0, frame.size.width, frame.size.height))
            window.setContentView_(view)
            view.setWantsLayer_(True)
            container = view.layer()
            if container is None:                 # older AppKit: make one
                container = CALayer.layer()
                container.setFrame_(view.bounds())
                view.setLayer_(container)
            container.setMasksToBounds_(False)

            # The border is its own layer inside the window's layer. The audio
            # badge has to stay readable while the border pulses and dims in
            # ARMED, and a child of the border would inherit that opacity -- so
            # the two are siblings and only the border animates.
            layer = CALayer.layer()
            layer.setFrame_(view.bounds())
            layer.setBorderWidth_(width)
            layer.setCornerRadius_(radius)
            layer.setShadowColor_(self._colors["active"].CGColor())
            layer.setShadowOpacity_(0.0)
            layer.setShadowRadius_(24.0)
            layer.setShadowOffset_(CGSizeMake(0.0, 0.0))
            layer.setMasksToBounds_(False)
            layer.setOpacity_(0.0)
            layer.setContentsScale_(scale)
            container.addSublayer_(layer)
            self._layers.append(layer)
            self._badges.append(self._audio_badge(
                container, frame.size.width, frame.size.height, scale))
            window.orderFrontRegardless()

    def _audio_badge(self, parent, width, height, scale):
        """The AUDIO GUIDE pill in the top-right corner of one screen.

        Fixed width so flipping the text does not jiggle the pill, and drawn in
        layers like the border, which needs no run loop and never takes focus.
        """
        from AppKit import (NSAttributedString, NSColor, NSFont,
                            NSFontAttributeName, NSMakeRect)
        from Quartz import CALayer, CATextLayer

        font = NSFont.boldSystemFontOfSize_(15.0)
        self._badge_font = font

        def measure(text):
            return float(NSAttributedString.alloc()
                         .initWithString_attributes_(
                             text, {NSFontAttributeName: font}).size().width)

        pad_x, badge_h, inset = 18.0, 34.0, 26.0
        badge_w = math.ceil(max(measure(self.BADGE_ON),
                                measure(self.BADGE_OFF))) + 2 * pad_x
        # 44 px down from the top edge keeps clear of the macOS menu bar.
        x = max(inset, width - badge_w - inset)
        y = max(inset, height - badge_h - 44.0)

        badge = CALayer.layer()
        badge.setFrame_(NSMakeRect(x, y, badge_w, badge_h))
        badge.setCornerRadius_(badge_h / 2.0)
        badge.setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.05, 0.82).CGColor())
        badge.setBorderWidth_(1.5)
        badge.setBorderColor_(self._colors["active"].CGColor())
        badge.setContentsScale_(scale)
        badge.setOpacity_(0.0)               # visible with the border, not before
        parent.addSublayer_(badge)

        text = CATextLayer.layer()
        text.setContentsScale_(scale)
        text.setAlignmentMode_("center")
        # CATextLayer draws from the top of its frame, so the frame is one line
        # tall and centred in the pill instead of filling it.
        text.setFrame_(NSMakeRect(0.0, (badge_h - 20.0) / 2.0, badge_w, 20.0))
        text.setString_(self._attributed(self.BADGE_ON,
                                        color=self._colors["active"]))
        badge.addSublayer_(text)
        return badge, text

    def _attributed(self, text, color=None):
        from AppKit import (NSAttributedString, NSFontAttributeName,
                            NSForegroundColorAttributeName)
        attributes = {NSFontAttributeName: self._badge_font,
                      NSForegroundColorAttributeName: color or self._colors["active"]}
        return NSAttributedString.alloc().initWithString_attributes_(text, attributes)

    # ----------------------------------------------------------------- update
    def update(self, state, now=None, audio=None):
        """state is the ControlState value: "off", "armed" or "active".
        `audio` is whether the spoken cues are on; None leaves the badge alone.
        """
        if not self.available:
            return
        if state == "off":
            if self._state is not None:
                self.hide()
            return
        if state not in self._colors:
            return
        if audio is not None:
            self._apply_audio(bool(audio))
        if now is None:
            now = 0.0

        pulse = 0.75 + 0.25 * math.sin(now * 5.0)
        alpha = (1.0 if state == "active" else 0.5) * pulse
        changed = state != self._state

        ct = self._CATransaction
        ct.begin()
        ct.setDisableActions_(True)
        try:
            if changed:
                color = self._colors[state].CGColor()
                for layer in self._layers:
                    layer.setBorderColor_(color)
                    layer.setShadowColor_(color)
                self._state = state
            for layer in self._layers:
                layer.setOpacity_(alpha)
                layer.setShadowOpacity_(0.75 * alpha)
            for badge, _text in self._badges:
                badge.setOpacity_(1.0)
        finally:
            ct.commit()

    def _apply_audio(self, enabled):
        """Flip the badge between AUDIO GUIDE ACTIVE and AUDIO GUIDE MUTED."""
        if not self.available or enabled == self._audio:
            return
        color = self._colors["active"] if enabled else self._colors["armed"]
        text = self._attributed(self.BADGE_ON if enabled else self.BADGE_OFF,
                                color)
        ct = self._CATransaction
        ct.begin()
        ct.setDisableActions_(True)
        try:
            for badge, label in self._badges:
                badge.setBorderColor_(color.CGColor())
                label.setString_(text)
            self._audio = enabled
        finally:
            ct.commit()

    def hide(self):
        if not self.available:
            return
        ct = self._CATransaction
        ct.begin()
        ct.setDisableActions_(True)
        try:
            for layer in self._layers:
                layer.setOpacity_(0.0)
            for badge, _text in self._badges:
                badge.setOpacity_(0.0)
        finally:
            ct.commit()
        self._state = None

    def close(self):
        for window in self._windows:
            try:
                window.orderOut_(None)
                window.close()
            except Exception:
                pass
        self._windows = []
        self._layers = []
        self._badges = []
        self._state = None
        self._audio = True
        self.available = False
