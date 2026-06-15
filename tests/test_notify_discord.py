"""Discord release-announcement payload + orchestration (pure, offline)."""

from __future__ import annotations

from partyhams.notify.discord import (
    announce_release,
    build_payload,
    build_post_request,
    fetch_release,
)

REPO = "jeremymturner/partyhamslogger"

SAMPLE_RELEASE = {
    "tag_name": "v0.0.4",
    "name": "PartyHams Logger v0.0.4",
    "html_url": "https://github.com/jeremymturner/partyhamslogger/releases/tag/v0.0.4",
    "body": "## What's Changed\n* Call history import by @jeremymturner",
    "published_at": "2026-06-15T19:25:00Z",
    "assets": [
        {
            "name": "PartyHamsLogger-v0.0.4-windows-x64.zip",
            "browser_download_url": "https://example.invalid/win.zip",
        },
        {
            "name": "SHA256SUMS",
            "browser_download_url": "https://example.invalid/SHA256SUMS",
        },
    ],
}


def test_build_payload_embed_basics():
    payload = build_payload(SAMPLE_RELEASE, REPO)
    embed = payload["embeds"][0]
    assert "v0.0.4" in embed["title"]
    assert embed["url"].endswith("/v0.0.4")
    assert "Call history import" in embed["description"]
    assert embed["timestamp"] == "2026-06-15T19:25:00Z"
    assert embed["footer"]["text"] == REPO
    # Assets become a Downloads field with markdown links.
    field = embed["fields"][0]
    assert field["name"] == "Downloads"
    assert "windows-x64.zip" in field["value"]
    assert "SHA256SUMS" in field["value"]
    # No mention -> no top-level content ping.
    assert "content" not in payload


def test_build_payload_truncates_a_long_body():
    payload = build_payload({**SAMPLE_RELEASE, "body": "x" * 9000}, REPO)
    description = payload["embeds"][0]["description"]
    assert len(description) <= 4096
    assert "read the full notes" in description


def test_build_payload_mention_sets_content():
    payload = build_payload(SAMPLE_RELEASE, REPO, mention="<@&12345>")
    assert payload["content"] == "<@&12345>"


def test_build_payload_falls_back_without_body_or_url_or_assets():
    payload = build_payload({"tag_name": "v1.2.3"}, "owner/repo")
    embed = payload["embeds"][0]
    assert embed["url"] == "https://github.com/owner/repo/releases/tag/v1.2.3"
    assert "v1.2.3" in embed["title"]
    assert "available" in embed["description"]  # generic fallback text
    assert "fields" not in embed  # no assets -> no Downloads field
    assert "timestamp" not in embed


def test_fetch_release_builds_authorized_api_url():
    seen = {}

    def fake_fetch(url, headers):
        seen["url"] = url
        seen["headers"] = headers
        return SAMPLE_RELEASE

    fetch_release(REPO, "v0.0.4", token="t0ken", fetch=fake_fetch)
    assert seen["url"] == f"https://api.github.com/repos/{REPO}/releases/tags/v0.0.4"
    assert seen["headers"]["Authorization"] == "Bearer t0ken"


def test_announce_release_fetches_then_posts():
    calls = {}

    def fake_fetch(url, headers):
        calls["fetch_url"] = url
        return SAMPLE_RELEASE

    def fake_post(url, payload):
        calls["post_url"] = url
        calls["payload"] = payload
        return 204

    status = announce_release(
        "https://discord.invalid/webhook",
        REPO,
        "v0.0.4",
        token="t0ken",
        mention="@everyone",
        fetch=fake_fetch,
        post=fake_post,
    )
    assert status == 204
    assert calls["fetch_url"].endswith("/releases/tags/v0.0.4")
    assert calls["post_url"] == "https://discord.invalid/webhook"
    assert calls["payload"]["content"] == "@everyone"
    assert "v0.0.4" in calls["payload"]["embeds"][0]["title"]


def test_build_post_request_sets_user_agent_to_dodge_cloudflare_403():
    # discord.com is behind Cloudflare, which 403s the default Python-urllib agent.
    req = build_post_request("https://discord.invalid/webhook", {"content": "hi"})
    assert req.get_method() == "POST"
    assert req.get_header("User-agent")  # must be present and non-empty
    assert "python-urllib" not in req.get_header("User-agent").lower()
    assert req.get_header("Content-type") == "application/json"
    assert b'"content"' in req.data
