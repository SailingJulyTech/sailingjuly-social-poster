"""
Post to TikTok via the Content Posting API (v2), pulling the video from a
public URL (PULL_FROM_URL upload mode).

Env vars required:
  TIKTOK_CLIENT_KEY
  TIKTOK_CLIENT_SECRET
  TIKTOK_REFRESH_TOKEN

Usage:
  python post_tiktok.py --caption "Dive day!" --media-url https://.../clip.mp4

IMPORTANT: until your TikTok app has passed the Content Posting API audit,
posts will land as private/draft content for the creator to review and
publish manually in the TikTok app -- not auto-published to the public
feed. See docs/TIKTOK_SETUP.md.
"""
import argparse
import time
import requests
from common import env, log

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
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


def init_post(access_token, caption, media_url, privacy_level):
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
        INIT_URL,
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

    log(f"Initiating post (privacy_level={args.privacy_level})...")
    init_resp = init_post(access_token, args.caption, args.media_url, args.privacy_level)
    publish_id = init_resp.get("data", {}).get("publish_id")
    if not publish_id:
        log(f"FAILED to init post: {init_resp}")
        raise SystemExit(1)

    log(f"Polling for completion (publish_id={publish_id})...")
    result = poll_status(access_token, publish_id)
    log(f"Success: {result}")


if __name__ == "__main__":
    main()
