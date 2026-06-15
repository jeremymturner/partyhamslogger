#!/usr/bin/env python3
"""Announce a GitHub release to Discord (run from the release workflow).

Reads the release for a tag from the GitHub API and posts an embed to a Discord
incoming webhook. Configuration comes from CLI flags or, in CI, the standard
environment:

    DISCORD_WEBHOOK_URL   the webhook to post to (required; if unset we skip)
    DISCORD_MENTION       optional content to ping, e.g. "<@&ROLEID>" / "@everyone"
    GITHUB_REPOSITORY     "owner/name"   (set automatically by GitHub Actions)
    GITHUB_REF_NAME       the tag        (set automatically on a tag push)
    GITHUB_TOKEN          token to read the release via the API

Usage:
    python3 scripts/notify_discord.py --repo owner/name --tag v1.2.3
    python3 scripts/notify_discord.py --tag v1.2.3 --dry-run   # print, don't post

Notification failures never fail the build — the release is already published, so
this exits 0 with a warning if Discord/GitHub is unreachable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Run straight from a checkout without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from partyhams.notify.discord import (  # noqa: E402
    announce_release,
    build_payload,
    fetch_release,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Announce a GitHub release to Discord.")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME"))
    parser.add_argument("--webhook", default=os.environ.get("DISCORD_WEBHOOK_URL"))
    parser.add_argument("--mention", default=os.environ.get("DISCORD_MENTION", ""))
    parser.add_argument(
        "--dry-run", action="store_true", help="print the payload instead of posting"
    )
    args = parser.parse_args(argv)

    if not args.webhook and not args.dry_run:
        print("DISCORD_WEBHOOK_URL not set — skipping Discord announcement.")
        return 0
    if not (args.repo and args.tag):
        print(
            "ERROR: need --repo and --tag (or GITHUB_REPOSITORY / GITHUB_REF_NAME).",
            file=sys.stderr,
        )
        return 2

    token = os.environ.get("GITHUB_TOKEN")
    try:
        if args.dry_run:
            try:
                release = fetch_release(args.repo, args.tag, token=token)
            except Exception as exc:  # noqa: BLE001 - offline preview falls back to a stub
                print(f"(could not fetch release, previewing from the tag: {exc})", file=sys.stderr)
                release = {"tag_name": args.tag}
            print(json.dumps(build_payload(release, args.repo, args.mention), indent=2))
            return 0

        status = announce_release(
            args.webhook, args.repo, args.tag, token=token, mention=args.mention
        )
        print(f"Posted Discord announcement for {args.tag} (HTTP {status}).")
        return 0
    except Exception as exc:  # noqa: BLE001 - a notification hiccup must not fail the release
        print(f"WARNING: Discord announcement failed: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
