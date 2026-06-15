"""Announce a new GitHub release to a Discord channel via an incoming webhook.

Split the way the rest of the codebase splits integrations: a **pure** payload
builder (:func:`build_payload`) and an orchestrator (:func:`announce_release`)
that takes injectable ``fetch``/``post`` callables, so everything is testable
offline. The default callables are thin ``urllib`` wrappers (stdlib only — no
third-party deps), used by ``scripts/notify_discord.py`` in CI.

Flow: read the release from the GitHub API by tag, format a Discord embed, POST
it to the webhook. Designed to run as the last step of the release workflow
(a release created by ``GITHUB_TOKEN`` does not itself trigger an ``on: release``
workflow, so the announcement must piggy-back on the build job).
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable

#: Discord limits — an embed description is 4096 chars, a field value 1024.
_DESCRIPTION_LIMIT = 4096
_FIELD_LIMIT = 1024
_EMBED_COLOR = 0x2ECC71  # green

#: Discord sits behind Cloudflare, which 403s the default ``Python-urllib`` agent —
#: we must send an explicit, identifying User-Agent on the webhook POST.
_USER_AGENT = "PartyHamsLogger-release-notifier (+https://github.com/jeremymturner/partyhamslogger)"

#: A ``fetch`` takes ``(url, headers)`` and returns the decoded JSON object.
Fetch = Callable[[str, dict[str, str]], dict]
#: A ``post`` takes ``(url, json_payload)`` and returns the HTTP status code.
Post = Callable[[str, dict], int]


def _truncate(text: str, limit: int, more_url: str | None = None) -> str:
    """Return ``text`` shortened to at most ``limit`` chars, with a link to the
    full content appended when it had to be cut."""
    if len(text) <= limit:
        return text
    suffix = f"\n\n… [read the full notes]({more_url})" if more_url else "\n\n…"
    keep = max(0, limit - len(suffix))
    return text[:keep].rstrip() + suffix


def build_payload(release: dict, repo: str, mention: str = "") -> dict:
    """Build the Discord webhook payload (an embed) for a GitHub ``release`` dict.

    Pure and offline. ``repo`` is ``"owner/name"`` (used for the footer and to
    synthesize a release URL if the API object lacks one). ``mention`` — e.g.
    ``"<@&ROLE_ID>"`` or ``"@everyone"`` — becomes the message ``content`` so the
    channel/role is pinged above the embed.
    """
    tag = release.get("tag_name") or "new release"
    name = release.get("name") or tag
    url = release.get("html_url") or f"https://github.com/{repo}/releases/tag/{tag}"
    project = repo.split("/")[-1] if repo else "the app"

    body = (release.get("body") or "").strip()
    description = (
        _truncate(body, _DESCRIPTION_LIMIT, url)
        if body
        else f"A new version of {project} is available — grab it from the release page."
    )

    embed: dict = {
        "title": f"🎉 {name}",
        "url": url,
        "description": description,
        "color": _EMBED_COLOR,
        "footer": {"text": repo or "GitHub"},
    }
    if release.get("published_at"):
        embed["timestamp"] = release["published_at"]

    links = [
        f"• [{a['name']}]({a['browser_download_url']})"
        for a in release.get("assets") or []
        if a.get("name") and a.get("browser_download_url")
    ]
    if links:
        embed["fields"] = [
            {"name": "Downloads", "value": _truncate("\n".join(links), _FIELD_LIMIT, url)}
        ]

    payload: dict = {"embeds": [embed]}
    if mention:
        payload["content"] = mention
    return payload


# --- default transports (stdlib urllib) ----------------------------------- #
def _http_get_json(url: str, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (trusted GitHub URL)
        return json.loads(resp.read().decode())


def build_post_request(url: str, payload: dict) -> urllib.request.Request:
    """Build the Discord webhook POST request. Sets an explicit User-Agent —
    without it Cloudflare (in front of discord.com) rejects the default
    ``Python-urllib`` agent with HTTP 403."""
    return urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
        method="POST",
    )


def _http_post_json(url: str, payload: dict) -> int:
    req = build_post_request(url, payload)
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (trusted webhook URL)
        return resp.status


def fetch_release(
    repo: str, tag: str, *, token: str | None = None, fetch: Fetch = _http_get_json
) -> dict:
    """Fetch the GitHub release object for ``tag`` in ``repo`` (``owner/name``)."""
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "partyhams-release-notifier",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return fetch(url, headers)


def announce_release(
    webhook_url: str,
    repo: str,
    tag: str,
    *,
    token: str | None = None,
    mention: str = "",
    fetch: Fetch = _http_get_json,
    post: Post = _http_post_json,
) -> int:
    """Look up ``tag``'s release and post a Discord announcement. Returns the
    webhook's HTTP status (Discord replies 204 on success)."""
    release = fetch_release(repo, tag, token=token, fetch=fetch)
    payload = build_payload(release, repo, mention)
    return post(webhook_url, payload)
