"""
Post to an Instagram Business account via the Instagram Graph API.

Env vars required:
  META_PAGE_ACCESS_TOKEN   (same Page token as Facebook -- IG posting goes
                             through the linked Page's token)
  IG_BUSINESS_ACCOUNT_ID

Usage:
  python post_instagram.py --caption "New dive video!" --media-url https://.../clip.mp4 --media-type reels
  python post_instagram.py --caption "Sunset shot" --media-url https://.../photo.jpg --media-type image

Notes:
  - media-url MUST be a public URL Meta's servers can fetch (see
    docs/META_SETUP.md). Local file paths will not work.
  - Video posts (reels) go through an async container: create -> poll
    status until FINISHED -> publish. This can take anywhere from a few
    seconds to a couple of minutes depending on video length.
"""
import argparse
import time
import requests
from common import env, log

GRAPH_VERSION = "v19.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

POLL_INTERVAL_SECONDS = 5
POLL_MAX_ATTEMPTS = 36  # ~3 minutes


def create_container(ig_user_id, token, caption, media_url, media_type):
    data = {"caption": caption, "access_token": token}
    if media_type == "image":
        data["image_url"] = media_url
    elif media_type == "reels":
        data["media_type"] = "REELS"
        data["video_url"] = media_url
    else:
        raise ValueError(f"Unsupported media_type: {media_type}")

    resp = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media", data=data, timeout=60)
    resp.raise_for_status()
    return resp.json()["id"]


def wait_for_container(container_id, token):
    for attempt in range(POLL_MAX_ATTEMPTS):
        resp = requests.get(
            f"{GRAPH_BASE}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=30,
        )
        resp.raise_for_status()
        info = resp.json()
        status = info.get("status_code")
        log(f"Container {container_id} status: {status} ({info.get('status')})")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Container processing failed: {info}")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Container {container_id} did not finish processing in time")


def publish_container(ig_user_id, token, container_id):
    resp = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=60,
    )
    return resp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--caption", required=True)
    parser.add_argument("--media-url", required=True)
    parser.add_argument("--media-type", choices=["image", "reels"], required=True)
    args = parser.parse_args()

    ig_user_id = env("IG_BUSINESS_ACCOUNT_ID")
    token = env("META_PAGE_ACCESS_TOKEN")

    log(f"Creating {args.media_type} container...")
    container_id = create_container(
        ig_user_id, token, args.caption, args.media_url, args.media_type
    )

    if args.media_type == "reels":
        wait_for_container(container_id, token)

    log("Publishing...")
    resp = publish_container(ig_user_id, token, container_id)

    if resp.status_code >= 300:
        log(f"FAILED ({resp.status_code}): {resp.text}")
        raise SystemExit(1)

    log(f"Success: {resp.json()}")


if __name__ == "__main__":
    main()
