"""
Post to a Facebook Page via the Graph API.

Env vars required:
  META_PAGE_ACCESS_TOKEN
  META_PAGE_ID

Usage:
  python post_facebook.py --caption "Hello world" --media-url https://.../clip.mp4 --media-type video
  python post_facebook.py --caption "Hello world" --media-url https://.../photo.jpg --media-type photo
  python post_facebook.py --caption "Text-only post, no media"

See docs/META_SETUP.md for how to obtain these values.
"""
import argparse
import requests
from common import env, log

GRAPH_VERSION = "v19.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--caption", required=True)
    parser.add_argument("--media-url", default=None)
    parser.add_argument(
        "--media-type", choices=["photo", "video"], default=None,
        help="Required if --media-url is set"
    )
    args = parser.parse_args()

    page_id = env("META_PAGE_ID")
    token = env("META_PAGE_ACCESS_TOKEN")

    if args.media_url and not args.media_type:
        raise SystemExit("--media-type is required when --media-url is set")

    if args.media_url is None:
        log("Posting text-only update to Facebook Page...")
        resp = post_text(page_id, token, args.caption)
    elif args.media_type == "photo":
        log(f"Posting photo to Facebook Page: {args.media_url}")
        resp = post_photo(page_id, token, args.caption, args.media_url)
    else:
        log(f"Posting video to Facebook Page: {args.media_url}")
        resp = post_video(page_id, token, args.caption, args.media_url)

    if resp.status_code >= 300:
        log(f"FAILED ({resp.status_code}): {resp.text}")
        raise SystemExit(1)

    log(f"Success: {resp.json()}")


if __name__ == "__main__":
    main()
