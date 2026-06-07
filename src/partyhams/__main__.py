"""``python -m partyhams`` / the ``partyhams`` console script entry point."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


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

    try:
        return run()
    except Exception:  # noqa: BLE001 - top-level crash reporter
        report = traceback.format_exc()
        log_path = Path.cwd() / "partyhams-error.log"
        try:
            log_path.write_text(report)
        except OSError:
            log_path = None
        print("\n" + "=" * 70, file=sys.stderr)
        print("PartyHams hit an error and had to stop. Please share this:", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print(report, file=sys.stderr)
        if log_path is not None:
            print(f"(also saved to {log_path})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
