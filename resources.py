"""resources.py -- where AirTrack's read-only assets live, in source or bundled.

The app reads three things that are not Python: the MediaPipe hand model, the
spoken cue WAVs, and (optionally) a saved calibration profile. In a source
checkout they sit next to this file. Inside a PyInstaller ``.app`` the same files
are copied into the bundle while the modules that load them live in
``Contents/Frameworks``, so ``Path(__file__).parent`` points at the wrong place.

Every path decision goes through this module so there is a single answer to
"where is the model / the sounds / the profile?":

* **frozen** -- search the bundle roots. PyInstaller has used both
  ``sys._MEIPASS`` (``Contents/Frameworks``) and ``Contents/Resources`` for data
  files across versions, so both are checked, in that order.
* **source** -- the repository root, exactly as before.

Only ``profile.json`` is ever written. A ``.app`` can be read-only -- and macOS
App Translocation runs a quarantined app from a random read-only path -- so a
packaged app saves per-user data under Application Support instead.

Standard library only, on purpose: ``tracker.py``, ``voice.py`` and
``calibrate_profile.py`` all import this, and the tests run without any of the
app's third-party dependencies installed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than a checkout."""
    return bool(getattr(sys, "frozen", False))


def source_root() -> Path:
    """The directory holding the Python modules (the repo root in development)."""
    return Path(__file__).resolve().parent


def _bundle_roots() -> list[Path]:
    """Candidate directories that can hold bundled data, most specific first.

    PyInstaller sets ``sys._MEIPASS`` to ``Contents/Frameworks`` for a macOS app
    bundle; ``datas`` end up in ``Contents/Resources``. Which one a given
    PyInstaller version uses has changed before, so both are searched instead of
    relying on one. ``Contents/MacOS`` is the executable's own directory and is
    the last resort.
    """
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))

    executable = Path(sys.executable).resolve()
    contents = executable.parent.parent          # .../Contents/MacOS/AirTrack -> .../Contents
    roots.extend([contents / "Resources", contents / "Frameworks", executable.parent])

    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def resource_path(*parts: str) -> Path:
    """Absolute path to a bundled asset, e.g. ``resource_path("sounds")``.

    In development this is simply ``<repo>/<parts>``. In a bundle the first
    existing candidate wins. If none exists, the first candidate is returned so a
    caller's error message names a real, inspectable location.
    """
    if not is_frozen():
        return source_root().joinpath(*parts)

    roots = _bundle_roots()
    for root in roots:
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate
    return roots[0].joinpath(*parts)


def user_data_dir(name: str = "AirTrack") -> Path:
    """Writable per-user directory for the profile and crash logs.

    macOS: ``~/Library/Application Support/AirTrack`` -- the conventional place
    for an app's own data, and never inside the app bundle.
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    path = base / name
    path.mkdir(parents=True, exist_ok=True)
    return path
