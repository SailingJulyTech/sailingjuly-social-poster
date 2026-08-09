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

sys.path.insert(0, os.path.dirname(__file__))

from common import log, load_json, save_json  # noqa: E402
import post_facebook  # noqa: E402
import post_instagram  # noqa: E402
import post_tiktok  # noqa: E402

DEFAULT_QUEUE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "content", "queue.json"
)


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_scheduled_for(value):
    # Accepts "...Z" suffix.
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def post_to_facebook(item, dry_run):
    caption = item["caption"]
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
            resp = post_facebook.post_video(page_id, token, caption, media_url)
        resp.raise_for_status()
        return True
    except Exception as e:
        log(f"Facebook post failed for {item['id']}: {e}")
        return False


def post_to_instagram(item, dry_run):
    caption = item["caption"]
    media_url = item["media_url"]
    ig_media_type = "reels" if item.get("media_type") == "video" else "image"
    if dry_run:
        log(f"[dry-run] would post to Instagram: {item['id']}")
        return True
    try:
        ig_user_id = os.environ["IG_BUSINESS_ACCOUNT_ID"]
        token = os.environ["META_PAGE_ACCESS_TOKEN"]
        container_id = post_instagram.create_container(
            ig_user_id, token, caption, media_url, ig_media_type
        )
        if ig_media_type == "reels":
            post_instagram.wait_for_container(container_id, token)
        resp = post_instagram.publish_container(ig_user_id, token, container_id)
        resp.raise_for_status()
        return True
    except Exception as e:
        log(f"Instagram post failed for {item['id']}: {e}")
        return False


def post_to_tiktok(item, dry_run):
    caption = item["caption"]
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
        init_resp = post_tiktok.init_post(access_token, caption, media_url, privacy_level)
        publish_id = init_resp.get("data", {}).get("publish_id")
        if not publish_id:
            raise RuntimeError(f"no publish_id in response: {init_resp}")
        post_tiktok.poll_status(access_token, publish_id)
        return True
    except Exception as e:
        log(f"TikTok post failed for {item['id']}: {e}")
        return False


PLATFORM_HANDLERS = {
    "facebook": post_to_facebook,
    "instagram": post_to_instagram,
    "tiktok": post_to_tiktok,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", default=DEFAULT_QUEUE_PATH)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Don't actually call any platform APIs, just show what would post"
    )
    args = parser.parse_args()

    queue = load_json(args.queue)
    now = utcnow()
    any_failure = False
    any_change = False

    for item in queue:
        if item.get("status") != "pending":
            continue
        scheduled_for = parse_scheduled_for(item["scheduled_for"])
        if scheduled_for > now:
            continue

        log(f"Processing due post: {item['id']}")
        posted_at = item.setdefault("posted_at", {})
        results = {}
        for platform in item.get("platforms", []):
            handler = PLATFORM_HANDLERS.get(platform)
            if handler is None:
                log(f"Unknown platform '{platform}' in item {item['id']}, skipping")
                results[platform] = False
                continue
            ok = handler(item, args.dry_run)
            results[platform] = ok
            if ok and not args.dry_run:
                posted_at[platform] = utcnow().isoformat()

        any_change = True
        if all(results.values()):
            item["status"] = "posted" if not args.dry_run else "pending"
        else:
            item["status"] = "failed"
            any_failure = True
        item["last_result"] = results

    if any_change and not args.dry_run:
        save_json(args.queue, queue)
        log(f"Updated {args.queue}")
    elif not any_change:
        log("Nothing due.")

    if any_failure:
        sys.exit(1)


if __name__ == "__main__":
    main()
