#!/usr/bin/env bash
# Wrap the PyInstaller onedir build (dist/PartyHamsLogger/) into an AppImage.
#
# Prerequisites on PATH (https://github.com/linuxdeploy / appimagetool):
#   - linuxdeploy-x86_64.AppImage  (as `linuxdeploy`)
#   - appimagetool-x86_64.AppImage (as `appimagetool`)
# Build the binary first:  make package   (or pyinstaller packaging/partyhams.spec)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DIST="$ROOT/dist/PartyHamsLogger"
APPDIR="$ROOT/dist/PartyHamsLogger.AppDir"

[ -d "$DIST" ] || { echo "ERROR: $DIST not found — run 'make package' first."; exit 1; }
command -v appimagetool >/dev/null || { echo "ERROR: appimagetool not on PATH"; exit 1; }

echo ">> assembling AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps"

cp -a "$DIST/." "$APPDIR/usr/bin/"
# AppRun -> our executable
ln -sf "usr/bin/PartyHamsLogger" "$APPDIR/AppRun"

# Desktop entry + icon (top-level copies are required by the AppImage spec).
install -m644 "$HERE/linux/partyhams.desktop" "$APPDIR/usr/share/applications/partyhams.desktop"
cp "$HERE/linux/partyhams.desktop" "$APPDIR/partyhams.desktop"
install -m644 "$ROOT/src/partyhams/ui/assets/icon.svg" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps/partyhams.svg"
cp "$ROOT/src/partyhams/ui/assets/icon.svg" "$APPDIR/partyhams.svg"

echo ">> building AppImage"
( cd "$ROOT/dist" && ARCH="${ARCH:-x86_64}" appimagetool "PartyHamsLogger.AppDir" "PartyHamsLogger-x86_64.AppImage" )
echo ">> wrote dist/PartyHamsLogger-x86_64.AppImage"
