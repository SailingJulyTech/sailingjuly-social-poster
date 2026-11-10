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
    """Poll AFTER finish_reel until Meta has processed and published the Reel.

    2026-11-10: this used to run BEFORE finish, waiting for "ready". Meta's
    Reels processing doesn't start until upload_phase=finish (same as
    video_stories, fixed 2026-10-14), so every Reel sat at upload_complete /
    processing_phase not_started until the timeout, then fell back to a plain
    /videos post. Every FB post from 2026-09-04 to 2026-11-10 went out as a
    plain video (almost no reach). Now finish first, then poll here.
    Returns the last status dict; raises on a terminal error status."""
    status, last = {}, None
    for attempt in range(REEL_POLL_MAX_ATTEMPTS):
        resp = requests.get(
            f"{GRAPH_BASE}/{video_id}",
            params={"fields": "status", "access_token": token},
            timeout=30,
        )
        resp.raise_for_status()
        status = resp.json().get("status", {})
        video_status = status.get("video_status")
        publishing = (status.get("publishing_phase") or {}).get("status")
        if status != last:
            log(f"Reel {video_id} status: {video_status}, publishing: {publishing} ({status})")
            last = status
        if video_status in REEL_TERMINAL_ERROR_STATUSES or publishing == "error":
            raise RuntimeError(f"Reel processing failed: {status}")
        if video_status == "ready" and publishing in (None, "complete"):
            return status
        time.sleep(REEL_POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Reel {video_id} not published after finish: {status}")


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


def post_video_story(page_id, token, media_url):
    """Publish the video as a Facebook Page Story (24h). Graph API has no
    "share an existing Reel to Story" action (that's the web/app Share ->
    Your story button), so this re-uploads the same file via the Page
    video_stories edge. No caption is supported. Best-effort by design:
    callers must not let a story failure fail the Reel post."""
    r = requests.post(
        f"{GRAPH_BASE}/{page_id}/video_stories",
        data={"upload_phase": "start", "access_token": token},
        timeout=60,
    )
    r.raise_for_status()
    j = r.json()
    video_id, upload_url = j["video_id"], j["upload_url"]
    tmp_path = download_to_tempfile(media_url)
    try:
        upload_reel_bytes(upload_url, token, tmp_path)
        # NOTE: unlike the Reel flow, do NOT wait for "ready" before finish --
        # for video_stories processing only starts after upload_phase=finish
        # (2026-10-14 live test: status sat at upload_complete/not_started
        # until the poll timed out with nothing published).
        return requests.post(
            f"{GRAPH_BASE}/{page_id}/video_stories",
            data={"upload_phase": "finish", "video_id": video_id, "access_token": token},
            timeout=60,
        )
    finally:
        os.remove(tmp_path)


def post_video_reel(page_id, token, caption, media_url):
    """Publish a short vertical video as a Facebook Reel rather than a plain
    Page video post. Plain /videos posts get almost no organic distribution
    under Meta's current algorithm -- nearly all short vertical video reach
    goes through the dedicated Reels surface, which this uses instead.

    Order: start -> upload bytes -> finish (video_state PUBLISHED) -> poll.
    Processing only begins at finish (see wait_for_reel_ready).

    Fallback to a plain /videos post ONLY when finish itself is rejected
    (nothing was published, so no double post). After a successful finish
    the Reel is Meta's to process: a slow poll is logged and counted as
    posted, a terminal error status is raised; neither is re-posted as a
    plain video (that would duplicate it).
    """
    video_id, upload_url = start_reel_upload(page_id, token)
    log(f"Reel upload session started: video_id={video_id}")
    log(f"Downloading {media_url} for direct upload...")
    tmp_path = download_to_tempfile(media_url)
    try:
        upload_reel_bytes(upload_url, token, tmp_path)
        resp = finish_reel(page_id, token, video_id, caption)
        ok = resp.ok and (resp.json() if resp.content else {}).get("success", True)
        if not ok:
            log(f"Reel finish rejected for {video_id} (HTTP {resp.status_code}: {resp.text[:500]}) "
                f"-- falling back to a plain video post (reduced reach)")
            return post_video_file(page_id, token, caption, tmp_path)
        log(f"Reel {video_id} finish accepted: {resp.text[:300]}")
        try:
            wait_for_reel_ready(page_id, token, video_id)
            log(f"Reel {video_id} published")
        except TimeoutError as e:
            # Finish was accepted, so the Reel is queued on Meta's side. Count it
            # as posted: failing here would make the scheduler retry = duplicate.
            log(f"WARNING: {e} -- finish was accepted, treating as posted; check the Page")
        return resp
    finally:
        os.remove(tmp_path)


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
