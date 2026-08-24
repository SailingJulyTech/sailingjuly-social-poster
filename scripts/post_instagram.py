"""
Post to an Instagram professional account via the Instagram Graph API
(Instagram Business Login flow -- a standalone Instagram token, not the
Facebook Page token).

Env vars required:
  IG_ACCESS_TOKEN
  IG_USER_ID

Usage:
  python post_instagram.py --caption "New dive video!" --media-path ./clip.mp4 --media-type reels
  python post_instagram.py --caption "New dive video!" --media-url https://.../clip.mp4 --media-type reels
  python post_instagram.py --caption "Sunset shot" --media-url https://.../photo.jpg --media-type image

Notes:
  - Images (--media-type image) MUST be a public URL Meta's servers can
    fetch -- Instagram's API has no direct-upload path for images.
  - Reels (--media-type reels) support --media-path: the local video file
    is uploaded directly to Meta via the resumable upload protocol
    (rupload.facebook.com), so no public hosting is needed. --media-url
    also works for reels if you'd rather host it yourself.
  - Video posts (reels) go through an async container: create -> upload
    (if local) -> poll status until FINISHED -> publish. This can take
    anywhere from a few seconds to a couple of minutes depending on video
    length.
"""
import argparse
import os
import time
import requests
from common import env, log

GRAPH_VERSION = "v19.0"
GRAPH_BASE = f"https://graph.instagram.com/{GRAPH_VERSION}"

POLL_INTERVAL_SECONDS = 5
POLL_MAX_ATTEMPTS = 60  # ~5 minutes


def create_hosted_container(ig_user_id, token, caption, media_url, media_type):
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


def create_resumable_container(ig_user_id, token, caption):
    data = {
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": caption,
        "access_token": token,
    }
    resp = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media", data=data, timeout=60)
    resp.raise_for_status()
    j = resp.json()
    return j["id"], j["uri"]


def upload_video_bytes(uri, token, media_path):
    file_size = os.path.getsize(media_path)
    with open(media_path, "rb") as f:
        video_bytes = f.read()
    headers = {
        "Authorization": f"OAuth {token}",
        "offset": "0",
        "file_size": str(file_size),
    }
    resp = requests.post(uri, headers=headers, data=video_bytes, timeout=600)
    resp.raise_for_status()
    j = resp.json()
    if not j.get("success"):
        raise RuntimeError(f"Resumable upload failed: {j}")


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
    parser.add_argument("--media-url", default=None, help="Public URL for Meta to fetch")
    parser.add_argument("--media-path", default=None, help="Local video file (reels only)")
    parser.add_argument("--media-type", choices=["image", "reels"], required=True)
    args = parser.parse_args()

    if args.media_url and args.media_path:
        raise SystemExit("pass only one of --media-url or --media-path")
    if not args.media_url and not args.media_path:
        raise SystemExit("one of --media-url or --media-path is required")
    if args.media_path and args.media_type != "reels":
        raise SystemExit("--media-path (local upload) is only supported for --media-type reels")

    ig_user_id = env("IG_USER_ID")
    token = env("IG_ACCESS_TOKEN")

    if args.media_path:
        log(f"Creating resumable reels container and uploading {args.media_path}...")
        container_id, uri = create_resumable_container(ig_user_id, token, args.caption)
        upload_video_bytes(uri, token, args.media_path)
        wait_for_container(container_id, token)
    else:
        log(f"Creating {args.media_type} container from URL: {args.media_url}")
        container_id = create_hosted_container(
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
