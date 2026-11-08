"""edge_glow.py -- full-screen state border for AirTrack (macOS).

The preview window's border only tells you the state while you are looking at
the preview. This draws a transparent, click-through, always-on-top border
around every screen instead, so ACTIVE (green) is visible from across the room
even when the browser or another app is in front.

macOS only. It uses PyObjC (AppKit + Quartz), which is already installed in the
project venv. On other platforms, or if PyObjC is missing, EdgeGlow silently
does nothing and the app keeps working with the preview border.
"""
from __future__ import annotations

import math
import sys


class EdgeGlow:
    """A hollow border around every screen, driven by the control state."""

    def __init__(self, enabled=True, width=10.0, radius=18.0):
        self.enabled = bool(enabled)
        self.available = False
        self._windows = []
        self._layers = []
        self._state = None
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
        from Quartz import CATransaction, CGSizeMake

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
            layer = view.layer()
            if layer is None:                     # older AppKit: make one
                from Quartz import CALayer
                layer = CALayer.layer()
                layer.setFrame_(view.bounds())
                view.setLayer_(layer)
            layer.setBorderWidth_(width)
            layer.setCornerRadius_(radius)
            layer.setShadowColor_(self._colors["active"].CGColor())
            layer.setShadowOpacity_(0.0)
            layer.setShadowRadius_(24.0)
            layer.setShadowOffset_(CGSizeMake(0.0, 0.0))
            layer.setMasksToBounds_(False)
            layer.setOpacity_(0.0)
            self._layers.append(layer)
            window.orderFrontRegardless()

    # ----------------------------------------------------------------- update
    def update(self, state, now=None):
        """state is the ControlState value: "off", "armed" or "active"."""
        if not self.available:
            return
        if state == "off":
            if self._state is not None:
                self.hide()
            return
        if state not in self._colors:
            return
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
        self._state = None
        self.available = False
