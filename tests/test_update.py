"""Update check: version parsing, asset selection, and the GitHub lookup (offline)."""

from __future__ import annotations

from partyhams.app.update import (
    asset_for_platform,
    check_for_update,
    is_newer,
    parse_version,
)

RELEASE = {
    "tag_name": "v0.1.0",
    "name": "PartyHams Logger v0.1.0",
    "html_url": "https://github.com/jeremymturner/partyhamslogger/releases/tag/v0.1.0",
    "body": "## What's Changed\n* stuff",
    "assets": [
        {
            "name": "PartyHamsLogger-v0.1.0-windows-x64.zip",
            "browser_download_url": "https://example.invalid/win.zip",
        },
        {
            "name": "PartyHamsLogger-v0.1.0-macos-arm64.zip",
            "browser_download_url": "https://example.invalid/mac.zip",
        },
        {
            "name": "PartyHamsLogger-v0.1.0-linux-x64.tar.gz",
            "browser_download_url": "https://example.invalid/linux.tgz",
        },
        {"name": "SHA256SUMS", "browser_download_url": "https://example.invalid/sums"},
    ],
}


def test_parse_version_tolerant():
    assert parse_version("v0.0.4") == (0, 0, 4)
    assert parse_version("0.1") == (0, 1)
    assert parse_version("1.2.0-rc1") == (1, 2, 0)  # stops at the non-numeric suffix
    assert parse_version("garbage") == ()


def test_is_newer():
    assert is_newer("v0.1.0", "0.0.4") is True
    assert is_newer("0.0.5", "0.0.4") is True
    assert is_newer("0.0.4", "0.0.4") is False  # equal is not newer
    assert is_newer("0.0.3", "0.0.4") is False  # older
    assert is_newer("v0.0.10", "v0.0.9") is True  # numeric, not lexical


def test_asset_for_platform_matches_os_and_arch():
    a = RELEASE["assets"]
    assert asset_for_platform(a, "Windows", "AMD64").endswith("win.zip")
    assert asset_for_platform(a, "Darwin", "arm64").endswith("mac.zip")
    assert asset_for_platform(a, "Linux", "x86_64").endswith("linux.tgz")
    # Intel mac with no x64 asset falls back to the generic macOS build…
    assert asset_for_platform(a, "Darwin", "x86_64").endswith("mac.zip")
    # …and an unknown OS matches nothing.
    assert asset_for_platform(a, "Plan9", "pdp11") is None


def test_check_for_update_returns_info_when_newer():
    seen = {}

    def fake_fetch(url, headers):
        seen["url"] = url
        return RELEASE

    info = check_for_update("0.0.4", fetch=fake_fetch, system="Windows", machine="AMD64")
    assert info is not None
    assert info.version == "0.1.0" and info.tag == "v0.1.0"
    assert info.url.endswith("win.zip")  # the platform asset, not the release page
    assert seen["url"].endswith("/releases/latest")


def test_check_for_update_none_when_current_or_older():
    fetch = lambda *_: RELEASE  # noqa: E731
    assert check_for_update("0.1.0", fetch=fetch, system="Linux") is None  # equal
    assert check_for_update("0.2.0", fetch=fetch, system="Linux") is None  # ahead of release


def test_check_for_update_falls_back_to_release_page_without_matching_asset():
    rel = {**RELEASE, "assets": [RELEASE["assets"][-1]]}  # only SHA256SUMS, no platform build
    info = check_for_update("0.0.4", fetch=lambda *_: rel, system="Windows")
    assert info is not None
    assert info.url == rel["html_url"]
