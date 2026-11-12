"""PartyHams Logger — cross-platform, multi-station amateur radio contest logger."""

import concurrent.futures as _futures

__version__ = "0.0.17"

# Python 3.15 declares ``concurrent.futures.ThreadPoolExecutor`` as a lazy import, and
# once PySide6 (6.12) is loaded that lazy attribute never resolves: asyncio's
# run_in_executor then fails with "'lazy_import' object is not callable", which breaks
# every serial CI-V radio. Reading it here, before anything imports Qt, resolves it.
# Harmless on 3.12-3.14, where it's an ordinary attribute.
_futures.ThreadPoolExecutor  # noqa: B018
