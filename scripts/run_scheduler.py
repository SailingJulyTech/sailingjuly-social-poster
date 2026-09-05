"""
Checks content/queue.json for due, pending posts and publishes them to each
listed platform. Meant to be run on a schedule (see
.github/workflows/scheduled-post.yml) but works fine run manually too:

  python scripts/run_scheduler.py
  python scripts/run_scheduler.py --dry-run
  python scripts/run_scheduler.py --queue path/to/other-queue.json

Updates queue.json in place with per-platform results so re-runs never
double-post. Exits non-zero if any platform post failed, so the GitHub
Actions job shows as failed and you get notified.
"""
import argparse
import datetime
import os
import sys
import tempfile

import requests

sys.path.insert(0, os.path.dirname(__file__))

from common import log, load_json, save_json, describe_error  # noqa: E402
import post_facebook  # noqa: E402
import post_instagram  # noqa: E402
import post_tiktok  # noqa: E402

DEFAULT_QUEUE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "content", "queue.json"
)
DEFAULT_STATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "content", "scheduler_state.json"
)

# Added 2026-09-05: a batch of ~14 due items all posted back-to-back in one
# run hammered Facebook hard enough to trip its own anti-spam rate limit
# (code 368) after ~13 rapid Reel attempts, and the run's own single
# end-of-run save_json+git-push lost all 80 minutes of results to an
# unrelated commit landing mid-run. Fix: process at most ONE due item per
# invocation, and refuse to even start a new one until MIN_GAP_MINUTES has
# passed since the last attempt (tracked in DEFAULT_STATE_PATH, not
# queue.json itself -- queue.json's schema is a flat list of post items,
# not a place for cross-run scheduler state). Real spacing between actual
# platform API calls, not just "whatever the cron happens to trigger."
MIN_GAP_MINUTES = 60


def load_state(path):
    if not os.path.exists(path):
        return {}
    return load_json(path)


def save_state(path, state):
    save_json(path, state)


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_scheduled_for(value):
    # Accepts "...Z" suffix.
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def caption_for(item, platform):
    """Per-platform caption override, when present, else the item's shared
    `caption` -- see content/README.md's "captions" field."""
    return (item.get("captions") or {}).get(platform, item["caption"])


def post_to_facebook(item, dry_run):
    caption = caption_for(item, "facebook")
    media_url = item.get("media_url")
    media_type = item.get("media_type")
    if dry_run:
        log(f"[dry-run] would post to Facebook: {item['id']}")
        return True
    try:
        page_id = os.environ["META_PAGE_ID"]
        token = os.environ["META_PAGE_ACCESS_TOKEN"]
        if media_url is None:
            resp = post_facebook.post_text(page_id, token, caption)
        elif media_type == "photo":
            resp = post_facebook.post_photo(page_id, token, caption, media_url)
        else:
            resp = post_facebook.post_video_reel(page_id, token, caption, media_url)
        resp.raise_for_status()
        return True
    except Exception as e:
        log(f"Facebook post failed for {item['id']}: {describe_error(e)}")
        return False


def post_to_instagram(item, dry_run):
    caption = caption_for(item, "instagram")
    media_url = item["media_url"]
    ig_media_type = "reels" if item.get("media_type") == "video" else "image"
    # Optional licensed music, attached at container-creation time:
    #   "audio": {"audio_id": "...", "audio_volume": 25, "video_volume": 100}
    # Find ids with scripts/find_audio.py. Requires Facebook Login creds --
    # if they're missing the item fails loudly rather than quietly publishing
    # a music-less Reel, because publishing can't be undone.
    audio = item.get("audio")
    if dry_run:
        extra = f" with audio {audio['audio_id']}" if audio else ""
        log(f"[dry-run] would post to Instagram: {item['id']}{extra}")
        return True
    try:
        if audio and ig_media_type != "reels":
            raise RuntimeError("audio can only be attached to reels, not images")
        target = post_instagram.resolve_target()
        log(f"Instagram via {target}")
        container_id = post_instagram.create_hosted_container(
            target, caption, media_url, ig_media_type, audio, item.get("audio_name")
        )
        if ig_media_type == "reels":
            post_instagram.wait_for_container(target, container_id)
        resp = post_instagram.publish_container(target, container_id)
        resp.raise_for_status()
        return True
    except Exception as e:
        log(f"Instagram post failed for {item['id']}: {describe_error(e)}")
        return False


def post_to_tiktok(item, dry_run):
    caption = caption_for(item, "tiktok")
    media_url = item["media_url"]
    if dry_run:
        log(f"[dry-run] would post to TikTok: {item['id']}")
        return True
    try:
        client_key = os.environ["TIKTOK_CLIENT_KEY"]
        client_secret = os.environ["TIKTOK_CLIENT_SECRET"]
        refresh_token = os.environ["TIKTOK_REFRESH_TOKEN"]
        access_token = post_tiktok.refresh_access_token(
            client_key, client_secret, refresh_token
        )
        privacy_level = os.environ.get("TIKTOK_PRIVACY_LEVEL", "SELF_ONLY")
        # queue.json media_urls point at GitHub Releases, an unverified
        # domain for PULL_FROM_URL -- download and FILE_UPLOAD instead,
        # for both the inbox (SELF_ONLY) and Direct Post paths.
        log(f"Downloading {media_url} for TikTok FILE_UPLOAD...")
        video_resp = requests.get(media_url, timeout=120)
        video_resp.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(video_resp.content)
            tmp_path = f.name
        try:
            video_size = os.path.getsize(tmp_path)
            if privacy_level == "SELF_ONLY":
                init_resp = post_tiktok.init_post_inbox_file(access_token, video_size)
            else:
                creator_info = post_tiktok.get_creator_info(access_token)
                allowed = creator_info.get("privacy_level_options") or []
                if allowed and privacy_level not in allowed:
                    raise RuntimeError(
                        f"privacy_level {privacy_level} not in allowed options {allowed}"
                    )
                init_resp = post_tiktok.init_post_direct_file(
                    access_token, caption, privacy_level, video_size
                )
            upload_url = init_resp.get("data", {}).get("upload_url")
            if not upload_url:
                raise RuntimeError(f"no upload_url in response: {init_resp}")
            post_tiktok.upload_video_file(upload_url, tmp_path)
        finally:
            os.remove(tmp_path)
        publish_id = init_resp.get("data", {}).get("publish_id")
        if not publish_id:
            raise RuntimeError(f"no publish_id in response: {init_resp}")
        post_tiktok.poll_status(access_token, publish_id)
        return True
    except Exception as e:
        log(f"TikTok post failed for {item['id']}: {describe_error(e)}")
        return False


PLATFORM_HANDLERS = {
    "facebook": post_to_facebook,
    "instagram": post_to_instagram,
    "tiktok": post_to_tiktok,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", default=DEFAULT_QUEUE_PATH)
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Don't actually call any platform APIs, just show what would post"
    )
    args = parser.parse_args()

    queue = load_json(args.queue)
    now = utcnow()

    # Same-hour throttle (2026-09-05 fix -- see MIN_GAP_MINUTES's own
    # comment): skipped entirely for --dry-run so previewing isn't blocked
    # by real posting history, and never persisted from a dry run either.
    if not args.dry_run:
        state = load_state(args.state)
        last_attempt_raw = state.get("last_attempt_at")
        if last_attempt_raw is not None:
            last_attempt_at = parse_scheduled_for(last_attempt_raw)
            elapsed_minutes = (now - last_attempt_at).total_seconds() / 60
            if elapsed_minutes < MIN_GAP_MINUTES:
                log(
                    f"Last post attempt was {elapsed_minutes:.1f} min ago; "
                    f"waiting until {MIN_GAP_MINUTES} min have passed "
                    f"({MIN_GAP_MINUTES - elapsed_minutes:.1f} min remaining). Nothing posted this run."
                )
                return

    # Only the SINGLE oldest due+pending item -- not a loop over every due
    # item -- is processed per invocation, so a batch of many due posts
    # gets spread across many runs (paced by MIN_GAP_MINUTES above) instead
    # of firing at every platform back-to-back in one run.
    due_items = [
        item for item in queue
        if item.get("status") == "pending"
        and parse_scheduled_for(item["scheduled_for"]) <= now
    ]
    due_items.sort(key=lambda item: parse_scheduled_for(item["scheduled_for"]))

    if not due_items:
        log("Nothing due.")
        return

    item = due_items[0]
    log(f"Processing due post: {item['id']} ({len(due_items) - 1} more still due after this one)")
    posted_at = item.setdefault("posted_at", {})
    results = {}
    for platform in item.get("platforms", []):
        if platform in posted_at:
            # A retry of a "failed" item (one or more OTHER platforms
            # failed last time) must not re-post to a platform that
            # already succeeded -- posted_at only ever gets a platform
            # key on success, so its presence is the retry-safe signal.
            log(f"Skipping {platform} for {item['id']}: already posted at {posted_at[platform]}")
            results[platform] = True
            continue
        handler = PLATFORM_HANDLERS.get(platform)
        if handler is None:
            log(f"Unknown platform '{platform}' in item {item['id']}, skipping")
            results[platform] = False
            continue
        ok = handler(item, args.dry_run)
        results[platform] = ok
        if ok and not args.dry_run:
            posted_at[platform] = utcnow().isoformat()

    if all(results.values()):
        item["status"] = "posted" if not args.dry_run else "pending"
    else:
        item["status"] = "failed"
    item["last_result"] = results

    if not args.dry_run:
        save_json(args.queue, queue)
        log(f"Updated {args.queue}")
        save_state(args.state, {"last_attempt_at": utcnow().isoformat()})
        log(f"Updated {args.state}")

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
