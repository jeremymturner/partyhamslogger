"""``python -m partyhams`` / the ``partyhams`` console script entry point."""

from __future__ import annotations

import sys


def main() -> int:
    # Imported lazily so the headless core stays importable without PySide6.
    try:
        from partyhams.ui.app import run
    except ImportError as exc:  # pragma: no cover
        print(
            "PartyHams needs PySide6 to launch the UI. Install dev/runtime deps:\n"
            "  uv pip install -e .\n"
            f"(import error: {exc})",
            file=sys.stderr,
        )
        return 1
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
