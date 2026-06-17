"""The shared HTTPS CA context (issue #26: TLS fails in packaged builds)."""

from __future__ import annotations

import ssl
from pathlib import Path

import certifi

from partyhams.core.certs import ssl_context


def test_ssl_context_uses_certifi_bundle():
    ctx = ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    # Verification is on (this is a verifying context, not an unverified one).
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    # The certifi CA file it trusts actually exists and contains certificates.
    bundle = Path(certifi.where())
    assert bundle.is_file()
    assert ctx.cert_store_stats()["x509_ca"] > 0  # CAs were loaded
