"""A trusted CA store for outbound HTTPS that works in packaged builds.

Python's default SSL context verifies against the operating system / Python
trust store. A PyInstaller bundle ships neither, so HTTPS verification fails with
``ssl.SSLCertVerificationError`` (seen first as the QRZ "TLS certificate not
trusted" error). Verifying against :mod:`certifi`'s bundled CA file — which the
build is configured to include — makes HTTPS work everywhere without a per-user
"Install Certificates" step.

Every shipped-app HTTPS caller (``qrz``, ``app.update``, ``contest.pota_api``)
passes :func:`ssl_context` to ``urlopen``.
"""

from __future__ import annotations

import ssl

import certifi


def ssl_context() -> ssl.SSLContext:
    """A default-secure SSL context that trusts certifi's CA bundle."""
    return ssl.create_default_context(cafile=certifi.where())
