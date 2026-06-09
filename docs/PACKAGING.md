# Packaging PartyHams Logger

PartyHams ships as a [PyInstaller](https://pyinstaller.org) bundle, wrapped into
the native installer/format for each platform. **PyInstaller cannot
cross-compile** — you must build each artifact on the matching OS (and CPU
architecture). The cleanest path is a CI matrix (one runner per target), but
every target below can also be built by hand.

All `make package*` targets install the `packaging` extra (PyInstaller) into the
dev venv on first use, then run `packaging/partyhams.spec`.

| Target platform        | Build host         | Command                       | Output |
| ---------------------- | ------------------ | ----------------------------- | ------ |
| Windows `.exe`         | Windows            | `make package`                | `dist/PartyHamsLogger/PartyHamsLogger.exe` |
| macOS (Intel)          | Intel Mac          | `make package`                | `dist/PartyHamsLogger.app` |
| macOS (Apple Silicon)  | Apple-Silicon Mac  | `make package`                | `dist/PartyHamsLogger.app` |
| macOS (universal2)     | either Mac¹        | `make package-mac-universal`  | `dist/PartyHamsLogger.app` (Intel + Silicon) |
| Linux AppImage         | Linux (x86_64)     | `make package-appimage`       | `dist/PartyHamsLogger-x86_64.AppImage` |
| Linux `.deb`           | Linux (Debian/Ubuntu) | `make package-deb`         | `dist/partyhams-logger_*.deb` |
| Linux `.rpm`           | Linux (Fedora/RHEL)   | `make package-rpm`         | `dist/partyhams-logger-*.rpm` |

¹ universal2 requires a Python interpreter built as `universal2` (the
python.org installers are; Homebrew's is single-arch).

## Prerequisites

- **All platforms:** Python ≥ 3.12 and the dev venv (`make setup`).
- **macOS:** Xcode command-line tools. For distribution outside your own
  machines you'll also want to **codesign** and **notarize** the `.app`
  (`codesign --deep --options runtime`, then `notarytool`), otherwise Gatekeeper
  blocks it.
- **Linux AppImage:** [`appimagetool`](https://github.com/AppImage/appimagetool)
  (and optionally `linuxdeploy`) on `PATH`.
- **Linux deb/rpm:** [`fpm`](https://fpm.readthedocs.io) (`gem install fpm`).
  Build the `.deb` on Debian/Ubuntu and the `.rpm` on Fedora/RHEL so the
  bundled glibc matches.

## Icons

The app icon is `src/partyhams/ui/assets/icon.svg`. PyInstaller wants a
platform raster icon; drop one next to the spec and it's picked up automatically:

- **Windows:** `packaging/icon.ico`
- **macOS:** `packaging/icon.icns`

Generate them from the SVG, e.g.:

```bash
# PNG master
rsvg-convert -w 1024 -h 1024 src/partyhams/ui/assets/icon.svg -o icon-1024.png
# macOS .icns
mkdir icon.iconset && for s in 16 32 64 128 256 512 1024; do \
  sips -z $s $s icon-1024.png --out icon.iconset/icon_${s}x${s}.png; done
iconset2icns icon.iconset           # or: iconutil -c icns icon.iconset
# Windows .ico (ImageMagick)
magick icon-1024.png -define icon:auto-resize=256,128,64,48,32,16 packaging/icon.ico
```

If no platform icon is present the build still succeeds (it just uses the
default executable icon) and the in-app window icon still comes from the SVG.

## Manual build (any platform)

```bash
make setup
.venv/bin/pip install -e ".[packaging]"
.venv/bin/pyinstaller --noconfirm --clean packaging/partyhams.spec
# -> dist/PartyHamsLogger/ (and dist/PartyHamsLogger.app on macOS)
```

For a Windows single-file `.exe`, change `EXE(... exclude_binaries=True ...)`
plus `COLLECT(...)` in the spec to a one-file `EXE(pyz, a.scripts, a.binaries,
a.datas, ... )` — handy for distribution, slower to start.

## CI suggestion

A GitHub Actions matrix over `windows-latest`, `macos-13` (Intel),
`macos-14` (Apple Silicon), and `ubuntu-latest` running the matching
`make package*` target, then uploading `dist/*` as release assets, gives you
all artifacts from one tag push.

## Publishing a release

To turn a build into a tagged GitHub release (with checksums, uploaded via the
`gh` CLI), use `make release VERSION=v0.1.0` / `scripts/release.sh`. See
[docs/RELEASING.md](RELEASING.md) for the full flow.
