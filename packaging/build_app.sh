#!/bin/zsh
# Build MetalMate.app (Apple Silicon) into dist/.
#   --install  also copy it to /Applications
#   --dmg      also make dist/MetalMate-<version>.dmg for downloading
# The app is built with a Python made for older macOS too (not Homebrew's): the standalone build in
# .toolchain/python if it's there, else python.org's, and the exact library versions in
# packaging/requirements-release.txt. Set METALMATE_PYTHON to use another Python.
set -e
cd "$(dirname "$0")/.."
APP_ID="com.ranbirdhall.metalmate"
APP="dist/MetalMate.app"
MIN_MACOS="12.0"
PY="${METALMATE_PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in .toolchain/python/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do
    [ -x "$candidate" ] && PY="$candidate" && break
  done
fi
VENV=".venv-release"

if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  echo "No Python 3.13 for building. Install it from https://www.python.org/downloads/macos/," \
       "unpack a python-build-standalone build into .toolchain/python, or set METALMATE_PYTHON." >&2
  exit 1
fi
if [ ! -x "$VENV/bin/python" ]; then
  "$PY" -m venv "$VENV"
fi
# Download wheels for the oldest supported macOS rather than the newest this Mac accepts.
"$VENV/bin/python" -m pip install -q --upgrade pip
"$VENV/bin/python" -m pip download -q --only-binary=:all: --dest build/wheels \
  --platform "macosx_${MIN_MACOS/./_}_arm64" --platform "macosx_${MIN_MACOS/./_}_universal2" \
  --python-version 3.13 --implementation cp -r packaging/requirements-release.txt
"$VENV/bin/python" -m pip install -q --no-index --find-links build/wheels -r packaging/requirements-release.txt
"$VENV/bin/python" packaging/make_icon.py >/dev/null
"$VENV/bin/python" packaging/make_notices.py >/dev/null
"$VENV/bin/python" -m PyInstaller --noconfirm --clean --log-level WARN \
  --distpath dist --workpath build packaging/metalmate.spec

# The licence and the third-party notices travel with the app.
cp LICENSE THIRD_PARTY_NOTICES.txt "$APP/Contents/Resources/"
rm -rf "$APP/Contents/Resources/licenses"
cp -R licenses "$APP/Contents/Resources/licenses"

# The on-board guides run in a helper process. Launching the main executable a second time would
# give it its own Dock icon, so the helper is a tiny app bundle marked LSUIElement (no Dock icon,
# no menu bar) that shares the main app's code and libraries through symlinks.
HELPER="$APP/Contents/Helpers/MetalMate Guides.app"
rm -rf "$APP/Contents/Helpers"
mkdir -p "$HELPER/Contents/MacOS"
cp "$APP/Contents/MacOS/MetalMate" "$HELPER/Contents/MacOS/MetalMate Guides"
ln -s ../../../Frameworks "$HELPER/Contents/Frameworks"
ln -s ../../../Resources "$HELPER/Contents/Resources"
VERSION=$(/usr/libexec/PlistBuddy -c "Print CFBundleShortVersionString" "$APP/Contents/Info.plist")
cat > "$HELPER/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>MetalMate Guides</string>
  <key>CFBundleIdentifier</key><string>$APP_ID.guides</string>
  <key>CFBundleName</key><string>MetalMate Guides</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>$MIN_MACOS</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# Ad-hoc signatures normally pin an app to its exact build (cdhash), so macOS would forget the
# Screen Recording permission on every rebuild. Requiring only the bundle identifier keeps it.
codesign --force --sign - --identifier "$APP_ID.guides" "$HELPER/Contents/MacOS/MetalMate Guides"
codesign --force --sign - --identifier "$APP_ID" \
  --requirements "=designated => identifier \"$APP_ID\"" "$APP"
codesign --verify --strict "$APP"

# Every binary inside must be Apple Silicon and run on MIN_MACOS.
"$VENV/bin/python" - "$APP" "$MIN_MACOS" <<'PYCHECK'
import subprocess, sys
from pathlib import Path
app, floor = Path(sys.argv[1]), tuple(int(x) for x in sys.argv[2].split("."))
bad, n = [], 0
for f in app.rglob("*"):
    if f.is_symlink() or not f.is_file():
        continue
    with open(f, "rb") as fh:
        magic = fh.read(4)
    if magic not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
        continue
    n += 1
    out = subprocess.run(["vtool", "-arch", "arm64", "-show-build", str(f)], capture_output=True, text=True).stdout
    mins = [l.split()[1] for l in out.splitlines() if l.strip().startswith("minos")]
    if not mins:
        bad.append(f"{f}: no arm64 build info")
    elif tuple(int(x) for x in mins[0].split(".")[:2]) > floor:
        bad.append(f"{f}: needs macOS {mins[0]}")
if bad:
    sys.exit("Binaries that won't run on the oldest supported macOS:\n  " + "\n  ".join(bad[:20]))
print(f"Checked {n} binaries: all arm64, all run on macOS {sys.argv[2]}+")
PYCHECK
echo "Built: $(pwd)/$APP"

if [[ " $* " == *" --install "* ]]; then
  # Quit a running copy first (TERM lets it save and stop the engine).
  pkill -TERM -f "/Applications/MetalMate.app/Contents/MacOS/MetalMate" || true
  for i in $(seq 1 20); do pgrep -f "/Applications/MetalMate.app" >/dev/null || break; sleep 0.25; done
  rm -rf "/Applications/MetalMate.app"
  cp -R "$APP" /Applications/
  echo "Installed: /Applications/MetalMate.app"
fi

if [[ " $* " == *" --dmg "* ]]; then
  DMG="dist/MetalMate-$VERSION.dmg"
  STAGE="build/dmg"
  rm -rf "$STAGE" "$DMG"
  mkdir -p "$STAGE"
  cp -R "$APP" "$STAGE/"
  ln -s /Applications "$STAGE/Applications"
  cp LICENSE "$STAGE/License.txt"
  cat > "$STAGE/Read Me First.txt" <<README
MetalMate $VERSION, by Ranbir Dhall
https://github.com/Ranbo-codez/MetalMate

1. Drag MetalMate into the Applications folder.
2. Open MetalMate. The first time, macOS says it can't check the app for malicious software
   (it isn't notarised by Apple yet). Click Done, then open System Settings > Privacy & Security,
   scroll down and click "Open Anyway" next to MetalMate, and confirm.
3. Allow MetalMate under Screen & System Audio Recording when asked, then quit and reopen it.

MetalMate is free for non-commercial use under the PolyForm Noncommercial License 1.0.0
(License.txt). For practice, analysis and games against bots, never against people.
README
  hdiutil create -quiet -volname "MetalMate $VERSION" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG"
  rm -rf "$STAGE"
  echo "DMG: $(pwd)/$DMG ($(du -h "$DMG" | cut -f1))"
fi
