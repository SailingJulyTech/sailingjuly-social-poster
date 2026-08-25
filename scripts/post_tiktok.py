"""
Post to TikTok via the Content Posting API (v2), pulling the video from a
public URL (PULL_FROM_URL upload mode).

Env vars required:
  TIKTOK_CLIENT_KEY
  TIKTOK_CLIENT_SECRET
  TIKTOK_REFRESH_TOKEN

Usage:
  python post_tiktok.py --caption "Dive day!" --media-url https://.../clip.mp4

TikTok has two separate posting endpoints gated by two separate scopes:
  - `video.upload` (granted pre-audit) -> the inbox/Upload API. The video
    lands as a draft in the creator's TikTok inbox for them to caption and
    publish manually. --caption is ignored here since the API takes none.
  - `video.publish` (granted only after the Content Posting API audit) ->
    Direct Post, which actually goes live with the given privacy_level and
    caption, no manual step. `creator_info` also requires this scope.
This script uses inbox/Upload automatically for --privacy-level SELF_ONLY
(the default) and Direct Post for anything else. See docs/TIKTOK_SETUP.md.
"""
import argparse
import time
import requests
from common import env, log

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
INBOX_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
DIRECT_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

POLL_INTERVAL_SECONDS = 5
POLL_MAX_ATTEMPTS = 24  # ~2 minutes


def refresh_access_token(client_key, client_secret, refresh_token):
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "access_token" not in payload:
        raise RuntimeError(f"Token refresh failed: {payload}")
    return payload["access_token"]


def get_creator_info(access_token):
    """Query the connected creator's profile + posting options.

    Required by TikTok's Content Posting API guidelines: the creator's
    username/avatar must be shown before a post is published, and audit
    reviewers check for this step in the demo video. Also confirms which
    privacy_level values this account is actually allowed to use.
    """
    resp = requests.post(
        CREATOR_INFO_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data", {})
    if not data:
        raise RuntimeError(f"creator_info query failed: {payload}")
    log(
        f"Posting as @{data.get('creator_username')} "
        f"({data.get('creator_nickname')}) -- avatar: {data.get('creator_avatar_url')}"
    )
    log(f"Allowed privacy levels for this account: {data.get('privacy_level_options')}")
    return data


def init_post_inbox(access_token, media_url):
    """Upload API (video.upload scope) -- delivers as a draft to the
    creator's TikTok inbox. Takes no caption/privacy_level; the creator
    sets those manually before publishing from the app."""
    body = {"source_info": {"source": "PULL_FROM_URL", "video_url": media_url}}
    resp = requests.post(
        INBOX_INIT_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json=body,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def init_post_direct(access_token, caption, media_url, privacy_level):
    """Direct Post (video.publish scope, requires a passed audit) --
    publishes live with the given caption/privacy_level, no manual step."""
    body = {
        "post_info": {
            "title": caption,
            "privacy_level": privacy_level,
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "video_url": media_url,
        },
    }
    resp = requests.post(
        DIRECT_INIT_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json=body,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def poll_status(access_token, publish_id):
    for attempt in range(POLL_MAX_ATTEMPTS):
        resp = requests.post(
            STATUS_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={"publish_id": publish_id},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        status = data.get("status")
        log(f"Publish {publish_id} status: {status}")
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            return data
        if status == "FAILED":
            raise RuntimeError(f"TikTok publish failed: {data}")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Publish {publish_id} did not complete in time")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--caption", required=True)
    parser.add_argument("--media-url", required=True)
    parser.add_argument(
        "--privacy-level",
        default="SELF_ONLY",
        choices=["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"],
        help="PUBLIC_TO_EVERYONE requires an audited app -- see docs/TIKTOK_SETUP.md",
    )
    args = parser.parse_args()

    client_key = env("TIKTOK_CLIENT_KEY")
    client_secret = env("TIKTOK_CLIENT_SECRET")
    refresh_token = env("TIKTOK_REFRESH_TOKEN")

    log("Refreshing TikTok access token...")
    access_token = refresh_access_token(client_key, client_secret, refresh_token)

    if args.privacy_level == "SELF_ONLY":
        log("Using Upload API (inbox) -- video.publish scope not granted until the app is "
            "audited, so this lands as a draft in the creator's TikTok inbox, not a live post. "
            "--caption is ignored; the creator captions it manually before publishing.")
        init_resp = init_post_inbox(access_token, args.media_url)
    else:
        creator_info = get_creator_info(access_token)
        allowed = creator_info.get("privacy_level_options") or []
        if allowed and args.privacy_level not in allowed:
            log(f"FAILED: privacy_level {args.privacy_level} not in allowed options {allowed}")
            raise SystemExit(1)
        log(f"Initiating direct post (privacy_level={args.privacy_level})...")
        init_resp = init_post_direct(access_token, args.caption, args.media_url, args.privacy_level)

    publish_id = init_resp.get("data", {}).get("publish_id")
    if not publish_id:
        log(f"FAILED to init post: {init_resp}")
        raise SystemExit(1)

    log(f"Polling for completion (publish_id={publish_id})...")
    result = poll_status(access_token, publish_id)
    log(f"Success: {result}")


if __name__ == "__main__":
    main()
