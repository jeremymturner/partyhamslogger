"""Make ``src/`` importable so tests run without an editable install."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Import the package before any test module imports PySide6, so its Python 3.15
# lazy-import workaround (see partyhams/__init__.py) runs first.
import partyhams  # noqa: E402, F401
