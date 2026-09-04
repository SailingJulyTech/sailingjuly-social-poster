"""
Post to a Facebook Page via the Graph API.

Env vars required:
  META_PAGE_ACCESS_TOKEN
  META_PAGE_ID

Usage:
  python post_facebook.py --caption "Hello world" --media-path ./clip.mp4 --media-type video
  python post_facebook.py --caption "Hello world" --media-url https://.../clip.mp4 --media-type video
  python post_facebook.py --caption "Hello world" --media-path ./photo.jpg --media-type photo
  python post_facebook.py --caption "Text-only post, no media"

--media-path uploads the local file directly (multipart) -- no public hosting
needed. --media-url instead has Meta fetch the file from a public URL.

--media-type video with --media-url publishes as a Facebook Reel (the
start/upload/finish flow below), not a plain Page video post. Plain /videos
posts get almost no organic reach under Meta's current algorithm -- short
vertical video only gets real distribution through the Reels surface. This
is what run_scheduler.py uses for every queued short. --media-path video
still goes through the older plain-video-post path (post_video_file) --
nothing in this repo drives that code path today, so it hasn't been
converted; convert it the same way (start/upload-bytes/finish) if a local
upload is ever needed.

See docs/META_SETUP.md for how to obtain these values.
"""
import argparse
import os
import tempfile
import time
import requests
from common import env, log

GRAPH_VERSION = "v19.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

REEL_POLL_INTERVAL_SECONDS = 5
REEL_POLL_MAX_ATTEMPTS = 60  # ~5 minutes
REEL_TERMINAL_ERROR_STATUSES = {"error", "expired", "upload_failed"}


def post_text(page_id, token, caption):
    resp = requests.post(
        f"{GRAPH_BASE}/{page_id}/feed",
        data={"message": caption, "access_token": token},
        timeout=60,
    )
    return resp


def post_photo(page_id, token, caption, media_url):
    resp = requests.post(
        f"{GRAPH_BASE}/{page_id}/photos",
        data={"url": media_url, "caption": caption, "access_token": token},
        timeout=60,
    )
    return resp


def post_photo_file(page_id, token, caption, media_path):
    with open(media_path, "rb") as f:
        resp = requests.post(
            f"{GRAPH_BASE}/{page_id}/photos",
            data={"caption": caption, "access_token": token},
            files={"source": f},
            timeout=120,
        )
    return resp


def post_video(page_id, token, caption, media_url):
    resp = requests.post(
        f"{GRAPH_BASE}/{page_id}/videos",
        data={
            "file_url": media_url,
            "description": caption,
            "access_token": token,
        },
        timeout=120,
    )
    return resp


def post_video_file(page_id, token, caption, media_path):
    with open(media_path, "rb") as f:
        resp = requests.post(
            f"{GRAPH_BASE}/{page_id}/videos",
            data={"description": caption, "access_token": token},
            files={"source": f},
            timeout=600,
        )
    return resp


def start_reel_upload(page_id, token):
    """Phase 1 of Reels publishing: open an upload session.
    Returns (video_id, upload_url)."""
    resp = requests.post(
        f"{GRAPH_BASE}/{page_id}/video_reels",
        data={"upload_phase": "start", "access_token": token},
        timeout=60,
    )
    resp.raise_for_status()
    j = resp.json()
    return j["video_id"], j["upload_url"]


def download_to_tempfile(media_url):
    resp = requests.get(media_url, stream=True, timeout=120)
    resp.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
        return f.name


def upload_reel_bytes(upload_url, token, media_path):
    """Phase 2, uploading raw bytes rather than pointing Meta at our URL.
    queue.json's media_urls are GitHub Releases links, which redirect to a
    short-lived signed blob URL -- the same "unverified domain for
    PULL_FROM_URL" reliability problem post_tiktok.py already had to work
    around (see run_scheduler.py's TikTok FILE_UPLOAD path). Downloading
    ourselves and uploading bytes sidesteps Meta's hosted-fetch entirely."""
    file_size = os.path.getsize(media_path)
    with open(media_path, "rb") as f:
        video_bytes = f.read()
    headers = {
        "Authorization": f"OAuth {token}",
        "offset": "0",
        "file_size": str(file_size),
    }
    resp = requests.post(upload_url, headers=headers, data=video_bytes, timeout=600)
    resp.raise_for_status()
    j = resp.json()
    if not j.get("success"):
        raise RuntimeError(f"Reel upload failed: {j}")


def wait_for_reel_ready(page_id, token, video_id):
    """Poll until Meta finishes fetching/processing the uploaded video.
    Without this, calling finish while status is still "uploading" or
    "processing" publishes an empty/broken Reel instead of failing loudly."""
    for attempt in range(REEL_POLL_MAX_ATTEMPTS):
        resp = requests.get(
            f"{GRAPH_BASE}/{video_id}",
            params={"fields": "status", "access_token": token},
            timeout=30,
        )
        resp.raise_for_status()
        status = resp.json().get("status", {})
        video_status = status.get("video_status")
        log(f"Reel {video_id} status: {video_status} ({status})")
        if video_status == "ready":
            return
        if video_status in REEL_TERMINAL_ERROR_STATUSES:
            raise RuntimeError(f"Reel upload did not become ready: {status}")
        time.sleep(REEL_POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Reel {video_id} did not become ready in time")


def finish_reel(page_id, token, video_id, caption):
    """Phase 3: publish the uploaded video as a Reel."""
    return requests.post(
        f"{GRAPH_BASE}/{page_id}/video_reels",
        data={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": caption,
            "access_token": token,
        },
        timeout=60,
    )


def post_video_reel(page_id, token, caption, media_url):
    """Publish a short vertical video as a Facebook Reel rather than a plain
    Page video post. Plain /videos posts get almost no organic distribution
    under Meta's current algorithm -- nearly all short vertical video reach
    goes through the dedicated Reels surface, which this uses instead."""
    video_id, upload_url = start_reel_upload(page_id, token)
    log(f"Reel upload session started: video_id={video_id}")
    log(f"Downloading {media_url} for direct upload...")
    tmp_path = download_to_tempfile(media_url)
    try:
        upload_reel_bytes(upload_url, token, tmp_path)
    finally:
        os.remove(tmp_path)
    wait_for_reel_ready(page_id, token, video_id)
    return finish_reel(page_id, token, video_id, caption)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--caption", required=True)
    parser.add_argument("--media-url", default=None, help="Public URL for Meta to fetch")
    parser.add_argument("--media-path", default=None, help="Local file to upload directly")
    parser.add_argument(
        "--media-type", choices=["photo", "video"], default=None,
        help="Required if --media-url or --media-path is set"
    )
    args = parser.parse_args()

    page_id = env("META_PAGE_ID")
    token = env("META_PAGE_ACCESS_TOKEN")

    if (args.media_url or args.media_path) and not args.media_type:
        raise SystemExit("--media-type is required when posting media")
    if args.media_url and args.media_path:
        raise SystemExit("pass only one of --media-url or --media-path")

    if args.media_path:
        log(f"Uploading {args.media_type} directly to Facebook Page: {args.media_path}")
        resp = (post_video_file if args.media_type == "video" else post_photo_file)(
            page_id, token, args.caption, args.media_path
        )
    elif args.media_url:
        if args.media_type == "video":
            log(f"Posting video as a Facebook Reel from URL: {args.media_url}")
            resp = post_video_reel(page_id, token, args.caption, args.media_url)
        else:
            log(f"Posting {args.media_type} to Facebook Page from URL: {args.media_url}")
            resp = post_photo(page_id, token, args.caption, args.media_url)
    else:
        log("Posting text-only update to Facebook Page...")
        resp = post_text(page_id, token, args.caption)

    if resp.status_code >= 300:
        log(f"FAILED ({resp.status_code}): {resp.text}")
        raise SystemExit(1)

    log(f"Success: {resp.json()}")


if __name__ == "__main__":
    main()
