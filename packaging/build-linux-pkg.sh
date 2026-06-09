#!/usr/bin/env bash
# Build a .deb or .rpm from the PyInstaller onedir build using fpm.
#
# Usage:   packaging/build-linux-pkg.sh deb     (or rpm)
# Needs:   fpm  (https://fpm.readthedocs.io)  — gem install fpm
#          and the binary built first:  make package
#
# Layout installed on the target system:
#   /opt/partyhams-logger/        <- the PyInstaller bundle
#   /usr/bin/partyhams-logger     <- launcher symlink
#   /usr/share/applications/...   <- desktop entry
set -euo pipefail

FORMAT="${1:?usage: build-linux-pkg.sh deb|rpm}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DIST="$ROOT/dist/PartyHamsLogger"
VERSION="$(cd "$ROOT" && "$ROOT/.venv/bin/python" -c 'import partyhams; print(partyhams.__version__)' 2>/dev/null || echo 0.0.1)"

[ -d "$DIST" ] || { echo "ERROR: $DIST not found — run 'make package' first."; exit 1; }
command -v fpm >/dev/null || { echo "ERROR: fpm not on PATH (gem install fpm)"; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/opt/partyhams-logger" "$STAGE/usr/bin" "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/scalable/apps"
cp -a "$DIST/." "$STAGE/opt/partyhams-logger/"
ln -s "/opt/partyhams-logger/PartyHamsLogger" "$STAGE/usr/bin/partyhams-logger"
install -m644 "$HERE/linux/partyhams.desktop" "$STAGE/usr/share/applications/partyhams.desktop"
install -m644 "$ROOT/src/partyhams/ui/assets/icon.svg" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps/partyhams.svg"

echo ">> building $FORMAT (v$VERSION)"
( cd "$ROOT/dist" && fpm -s dir -t "$FORMAT" \
    -n partyhams-logger -v "$VERSION" \
    --description "Keyboard-first amateur-radio contest logger" \
    --license MIT --maintainer "Jeremy Turner" \
    --url "https://github.com/" \
    -C "$STAGE" . )
echo ">> wrote dist/partyhams-logger*.$FORMAT"
