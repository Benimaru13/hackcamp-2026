#!/usr/bin/env bash
# build_macos.sh -- build a self-contained, unsigned AirTrack.app and its
# tester-facing .zip archive.
#
# What it does, in order:
#   1. creates (or reuses) a dedicated build venv so the developer's own
#      .venv is never modified;
#   2. installs requirements.txt plus a pinned PyInstaller;
#   3. downloads the 7.8 MB hand model into git-ignored models/ if missing;
#   4. runs PyInstaller with packaging/airtrack.spec;
#   5. checks the bundle's architecture and assets, and runs the app's own
#      --self-check and a camera-free --simulate calibration;
#   6. writes dist/AirTrack-<version>-macos-<arch>.zip with ditto, which keeps
#      the bundle's permissions and extended attributes intact.
#
# Usage:
#   packaging/build_macos.sh                 # python3.14 if available
#   PYTHON=/opt/homebrew/bin/python3.15 packaging/build_macos.sh
#
# This script does not sign, notarise, publish or upload anything. The build is
# single-architecture: run it on the architecture you want to support (Apple
# Silicon here, an Intel Mac for an Intel build).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="0.1.0"
PYINSTALLER_VERSION="6.22.3"
VENV="$ROOT/build/packaging-venv"
DIST="$ROOT/dist"
APP="$DIST/AirTrack.app"
ARCH="$(uname -m)"

cd "$ROOT"

# Pick a modern interpreter: the app's pinned wheels need 3.14+ on this project,
# and the system python3 is too old. An explicit PYTHON=... always wins.
if [ -z "${PYTHON:-}" ]; then
  for candidate in python3.14 python3.15 python3.13; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON="$candidate"
      break
    fi
  done
fi
if [ -z "${PYTHON:-}" ] || ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "error: no suitable Python found. Set PYTHON=/path/to/python3.14" >&2
  exit 1
fi

echo "== AirTrack $VERSION / macOS-$ARCH =="
echo "Python: $("$PYTHON" -VV)"

if [ ! -x "$VENV/bin/python" ]; then
  echo "-- creating build venv: build/packaging-venv"
  "$PYTHON" -m venv "$VENV"
fi

echo "-- installing pinned developer/build dependencies"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r requirements.txt "pyinstaller==$PYINSTALLER_VERSION"

echo "-- ensuring the hand model is present (7.8 MB, git-ignored)"
"$VENV/bin/python" - <<'PY'
from tracker import ensure_model

print(ensure_model())
PY

echo "-- running PyInstaller"
rm -rf "$APP"
"$VENV/bin/python" -m PyInstaller \
  --noconfirm --clean \
  --distpath "$DIST" \
  --workpath "$ROOT/build/pyinstaller" \
  "$ROOT/packaging/airtrack.spec"

# PyInstaller also leaves the intermediate onedir collection in dist/. The .app
# is the artifact that ships, so keep the folder tidy and unambiguous.
rm -rf "$DIST/AirTrack"

if [ ! -x "$APP/Contents/MacOS/AirTrack" ]; then
  echo "error: expected executable missing at $APP/Contents/MacOS/AirTrack" >&2
  exit 1
fi

echo "-- built: $APP ($(du -sh "$APP" | cut -f1))"
echo "-- executable architecture: $(lipo -archs "$APP/Contents/MacOS/AirTrack")"

# PyInstaller's BUNDLE step left an ad-hoc signature with no sealed resources
# ("Sealed Resources=none"), which makes a downloaded copy fail codesign
# verification and can show up as "damaged" instead of the expected
# unidentified-developer prompt. Re-signing the finished bundle writes
# Contents/_CodeSignature and binds Info.plist. Still ad-hoc: Gatekeeper will
# ask the tester to right-click > Open, but the app is intact.
echo "-- ad-hoc signing in a clean staging directory"
# Two reasons this happens outside the project folder:
#   * codesign refuses a bundle carrying Finder/resource-fork detritus, and this
#     checkout lives under iCloud-managed Documents, whose file provider keeps
#     re-attaching those attributes even after `xattr -cr`;
#   * PyInstaller's own BUNDLE signature ends up with Sealed Resources=none, so
#     the finished bundle has to be signed again.
# Staging in the temp directory, clearing xattrs and signing there produces a
# bundle whose signature verifies. The signed copy is then put back into dist
# for review; the tester archive is built from the staged copy.
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/airtrack-sign.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/AirTrack.app"
xattr -cr "$STAGE/AirTrack.app"
codesign --force --deep --sign - "$STAGE/AirTrack.app"
codesign --verify --deep --strict "$STAGE/AirTrack.app"

rm -rf "$APP"
cp -R "$STAGE/AirTrack.app" "$APP"
codesign --verify --deep --strict "$APP"

# The app must not contain a native library for a different architecture: that
# would mean the "Apple Silicon" build silently fails on the tester's Mac.
echo "-- checking every Mach-O file is $ARCH"
mismatched=0
while IFS= read -r -d '' file; do
  if file "$file" | grep -q "Mach-O"; then
    archs="$(lipo -archs "$file" 2>/dev/null || true)"
    case " $archs " in
      *" $ARCH "*) ;;
      *)
        echo "   not $ARCH: $file ($archs)"
        mismatched=$((mismatched + 1))
        ;;
    esac
  fi
done < <(find "$APP/Contents" -type f -print0)
if [ "$mismatched" -ne 0 ]; then
  echo "error: $mismatched Mach-O file(s) do not match $ARCH" >&2
  exit 1
fi

echo "-- archiving for testers"
ZIP="$DIST/AirTrack-$VERSION-macos-$ARCH.zip"
rm -f "$ZIP"
ditto -c -k --keepParent "$STAGE/AirTrack.app" "$ZIP"

# Verify the artifact a tester actually receives, not just the build output:
# extract the zip, check the signature survived archiving, then run the bundle's
# own checks from the extracted copy.
echo "-- verifying the archive round-trip"
UNPACK="$(mktemp -d "${TMPDIR:-/tmp}/airtrack-verify.XXXXXX")"
trap 'rm -rf "$STAGE" "$UNPACK"' EXIT
ditto -x -k "$ZIP" "$UNPACK"
codesign --verify --deep --strict "$UNPACK/AirTrack.app"

if [ "$UNPACK" = "" ]; then
  echo "error: archive did not extract" >&2
  exit 1
fi

SMOKE="$UNPACK/AirTrack.app/Contents/MacOS/AirTrack"
if [ ! -x "$SMOKE" ]; then
  echo "error: no executable after extracting the archive" >&2
  exit 1
fi

echo "-- bundle self-check (model, sounds, imports, writable profile folder)"
"$SMOKE" --self-check

echo "-- packaged smoke test: simulated calibration, no camera, no pointer"
# --skip-permission-check keeps a build from opening System Settings panes.
"$SMOKE" --skip-permission-check --simulate

echo
echo "Build complete:"
echo "  app:     $APP"
echo "  archive: $ZIP"
echo "  sha256:  $(shasum -a 256 "$ZIP" | cut -d' ' -f1)"
echo
echo "The archive is unsigned and un-notarised. Testers must use"
echo "right-click > Open (or allow it once in System Settings > Privacy &"
echo "Security). See packaging/TESTER_GUIDE.md."
