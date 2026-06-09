# PyInstaller build spec for PartyHams Logger.
#
# Builds a self-contained app for the platform it runs on:
#   - Windows  -> dist/PartyHamsLogger/PartyHamsLogger.exe
#   - macOS    -> dist/PartyHamsLogger.app  (+ dist/PartyHamsLogger/)
#   - Linux    -> dist/PartyHamsLogger/PartyHamsLogger
#
# Run from the repo root:  pyinstaller --noconfirm --clean packaging/partyhams.spec
# (the Makefile `package*` targets wrap this). PyInstaller must run on the SAME
# OS/arch you're targeting — there is no cross-compilation.

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))  # noqa: F821 (SPECPATH injected)
SRC = os.path.join(ROOT, "src")

APP_NAME = "PartyHamsLogger"
ICON_SVG = os.path.join(SRC, "partyhams", "ui", "assets", "icon.svg")

# Use a platform icon next to this spec if present (icon.icns on macOS, icon.ico
# on Windows) — see docs/PACKAGING.md for how to generate them from icon.svg.
icon_file = None
for cand in ("icon.icns", "icon.ico"):
    candidate = os.path.join(SPECPATH, cand)  # noqa: F821
    if os.path.exists(candidate):
        icon_file = candidate
        break

# Bundle the app icon (loaded at runtime via Path(__file__).parent in ui/style.py)
# and make sure the self-registering radio/contest backends are pulled in.
datas = [(ICON_SVG, os.path.join("partyhams", "ui", "assets"))]
hiddenimports = (
    collect_submodules("partyhams.radio")
    + collect_submodules("partyhams.contest")
    + ["PySide6.QtMultimedia"]  # imported lazily for voice macros
)

a = Analysis(
    [os.path.join(SRC, "partyhams", "__main__.py")],
    pathex=[SRC],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,  # GUI app — no console window on Windows
    icon=icon_file,
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)  # noqa: F821

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name=f"{APP_NAME}.app",
        icon=icon_file,
        bundle_identifier="com.jeremymturner.partyhams",
    )
