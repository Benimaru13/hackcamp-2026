# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a self-contained macOS AirTrack.app.

Why PyInstaller (and onedir):
  * AirTrack is a plain Python desktop app with OpenCV windows and PyObjC, not a
    web app and not a CLI, so it needs a real .app bundle that TCC (macOS
    permissions) can attribute Camera and Accessibility grants to.
  * The app loads a 7.8 MB hand model and three WAV files at runtime. A onefile
    build would unpack those into a temporary directory on every launch, so the
    first start would be slower and App Translocation would keep re-extracting
    it. COLLECT (onedir) keeps the model where MediaPipe expects it.
  * PyInstaller is the only packager here that needs no extra toolchain beyond a
    Python interpreter; briefcase/py2app add project metadata or dependencies
    without solving anything this app needs.

The bundle is single-architecture, matching the machine it is built on. The
native wheels pinned in requirements.txt are arm64-only on macOS, so a universal
build is not possible without different dependencies; build once per
architecture instead.

Result: dist/AirTrack.app
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

APP_NAME = "AirTrack"
APP_VERSION = "0.1.0"

REPO_ROOT = Path(SPECPATH).resolve().parent
ENTRY_POINT = REPO_ROOT / "packaging" / "airtrack_entry.py"

datas = [
    # Bundled so a tester never needs the network on first launch. models/ is
    # git-ignored in development; build_macos.sh fetches it before this runs.
    (str(REPO_ROOT / "models" / "hand_landmarker.task"), "models"),
    # The three spoken cues voice.py plays (start_message, activated, released).
    (str(REPO_ROOT / "sounds"), "sounds"),
]
binaries = []
hiddenimports = [
    # Imported lazily or via attribute access inside the app, so PyInstaller's
    # static analysis may miss them.
    "mediapipe.tasks.python.vision",
    "mediapipe.tasks.python.vision.hand_landmarker",
    "objc",
    "Foundation",
    "CoreFoundation",
    "AppKit",
    "Quartz",
    "pyscreeze",
    "pyperclip",
    "pymsgbox",
    "pytweening",
    "mouseinfo",
]

# mediapipe ships .dylibs and data files next to its Python modules; cv2 is a
# package with an extension module and config data; AppKit/Quartz are PyObjC
# packages with their own binaries. collect_all is the reliable way to keep all
# of that, and --self-check verifies the result at runtime.
for package in ("mediapipe", "cv2", "AppKit", "Quartz", "pyautogui"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

analysis = Analysis(
    [str(ENTRY_POINT)],
    pathex=[str(REPO_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Not reachable from the entry point. Excluding them keeps stray development
    # files (the unfinished deepspace demo, the test suite) out of the bundle.
    excludes=["tests", "pytest", "deepspace_app", "ds_intg", "generate_sounds"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # a double-clicked app must not open a terminal
    target_arch=None,       # single-arch build, matching the build machine
    codesign_identity=None, # unsigned test build; see packaging/README.md
    entitlements_file=None,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

app = BUNDLE(
    collection,
    name=f"{APP_NAME}.app",
    icon=None,
    bundle_identifier="com.airtrack.airtrack",
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "CFBundlePackageType": "APPL",
        # The native wheels in requirements.txt are built for macOS 13 (OpenCV)
        # and macOS 14 (NumPy), so this is the real floor, not a guess.
        "LSMinimumSystemVersion": "14.0",
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHighResolutionCapable": True,
        # Without this key macOS terminates the app the first time it opens the
        # camera instead of showing a permission prompt. Wording is what the
        # tester sees, so it says plainly that video stays on the Mac.
        "NSCameraUsageDescription": (
            "AirTrack uses the camera to find your hand and move the pointer. "
            "Video is processed on this Mac and never saved or sent anywhere."
        ),
    },
)
