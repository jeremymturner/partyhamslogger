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


# --- interval clamp, asset URL detection ---------------------------------------


def test_clamp_interval_hours():
    from partyhams.app.update import clamp_interval_hours

    assert clamp_interval_hours(1) == 1
    assert clamp_interval_hours(0) == 1  # floor: 1 hour
    assert clamp_interval_hours(9999) == 168  # ceiling: 7 days
    assert clamp_interval_hours(24) == 24


def test_is_asset_url():
    from partyhams.app.update import is_asset_url

    assert is_asset_url("https://x/PartyHamsLogger-v1-windows-x64.zip")
    assert is_asset_url("https://x/PartyHamsLogger-v1-linux-x64.tar.gz")
    assert not is_asset_url("https://github.com/o/r/releases/tag/v1")


# --- streaming download --------------------------------------------------------


class _FakeResp:
    def __init__(self, data: bytes, total: int | None = None):
        self._chunks = [data[i : i + 3] for i in range(0, len(data), 3)]
        self.headers = {"Content-Length": str(len(data) if total is None else total)}

    def read(self, _n):
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_download_asset_streams_and_reports_progress(tmp_path):
    from partyhams.app.update import download_asset

    seen = []
    out = download_asset(
        "https://x/PartyHamsLogger-v1-linux-x64.tar.gz",
        tmp_path,
        progress=lambda r, t: seen.append((r, t)),
        opener=lambda _u: _FakeResp(b"abcdefg"),
    )
    assert out.read_bytes() == b"abcdefg"
    assert out.name.endswith("linux-x64.tar.gz")
    assert seen[-1] == (7, 7)  # final progress = full size


# --- archive extraction --------------------------------------------------------


def test_extract_bundle_zip_and_targz(tmp_path):
    import tarfile
    import zipfile

    from partyhams.app.update import extract_bundle

    zpath = tmp_path / "win.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("PartyHamsLogger/PartyHamsLogger.exe", b"binary")
        zf.writestr("PartyHamsLogger/data.txt", b"x")
    bundle = extract_bundle(zpath, tmp_path / "z")
    assert bundle == tmp_path / "z" / "PartyHamsLogger"
    assert (bundle / "PartyHamsLogger.exe").exists()

    src = tmp_path / "PartyHamsLogger"
    (src).mkdir()
    (src / "PartyHamsLogger").write_bytes(b"binary")
    tpath = tmp_path / "linux.tar.gz"
    with tarfile.open(tpath, "w:gz") as tf:
        tf.add(src, arcname="PartyHamsLogger")
    bundle2 = extract_bundle(tpath, tmp_path / "t")
    assert bundle2 == tmp_path / "t" / "PartyHamsLogger"
    assert (bundle2 / "PartyHamsLogger").exists()


# --- install location, relaunch command, swap script --------------------------


def test_install_root_per_platform():
    from pathlib import Path

    from partyhams.app.update import install_root

    mac = install_root("/Applications/PartyHamsLogger.app/Contents/MacOS/PartyHamsLogger", "Darwin")
    assert mac == Path("/Applications/PartyHamsLogger.app")
    linux = install_root("/opt/PartyHamsLogger/PartyHamsLogger", "Linux")
    assert linux == Path("/opt/PartyHamsLogger")


def test_relaunch_command_per_platform():
    from partyhams.app.update import relaunch_command

    assert relaunch_command("/A/Foo.app", "Darwin") == ["open", "/A/Foo.app"]
    assert relaunch_command("/opt/PartyHamsLogger", "Linux")[0].endswith("PartyHamsLogger")
    assert relaunch_command("C:/app", "Windows")[0].endswith("PartyHamsLogger.exe")


def test_swap_script_unix_and_windows():
    from partyhams.app.update import swap_script

    suffix, text = swap_script("linux", 4242, "/opt/app", "/tmp/new", ["/opt/app/PartyHamsLogger"])
    assert suffix == ".sh"
    assert "kill -0 4242" in text and 'rm -rf "/opt/app"' in text and 'mv "/tmp/new"' in text

    suffix, text = swap_script(
        "windows", 99, r"C:\app", r"C:\tmp\new", [r"C:\app\PartyHamsLogger.exe"]
    )
    assert suffix == ".bat"
    assert "tasklist" in text and "rmdir /s /q" in text and "move" in text and "start" in text


def test_apply_update_writes_script_and_invokes_runner(tmp_path):
    from partyhams.app.update import apply_update

    captured = {}

    def fake_runner(system, script_path):
        captured["system"] = system
        captured["script"] = script_path

    apply_update(
        tmp_path / "new-bundle",
        app_root=tmp_path / "installed",
        pid=1234,
        system="linux",
        runner=fake_runner,
    )
    assert captured["system"] == "linux"
    body = open(captured["script"]).read()
    assert "kill -0 1234" in body
    assert str(tmp_path / "installed") in body
