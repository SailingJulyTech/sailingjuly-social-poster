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
        log(f"Posting {args.media_type} to Facebook Page from URL: {args.media_url}")
        resp = (post_video if args.media_type == "video" else post_photo)(
            page_id, token, args.caption, args.media_url
        )
    else:
        log("Posting text-only update to Facebook Page...")
        resp = post_text(page_id, token, args.caption)

    if resp.status_code >= 300:
        log(f"FAILED ({resp.status_code}): {resp.text}")
        raise SystemExit(1)

    log(f"Success: {resp.json()}")


if __name__ == "__main__":
    main()
