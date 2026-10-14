"""
Post ONE story from a public video URL (diagnostic / manual use).

  python scripts/story_once.py --platform facebook --media-url URL [--dry-run]
  python scripts/story_once.py --platform instagram --media-url URL

Credentials come from the environment, same as the other scripts
(META_PAGE_ID / META_PAGE_ACCESS_TOKEN for Facebook; IG_* for Instagram).
Exits non-zero with the Graph error text on failure.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from common import env, log, describe_error  # noqa: E402


def post_story(platform, media_url):
    """Post one story. Raises on failure."""
    if platform == "facebook":
        import post_facebook
        resp = post_facebook.post_video_story(
            env("META_PAGE_ID"), env("META_PAGE_ACCESS_TOKEN"), media_url
        )
        resp.raise_for_status()
        return resp
    if platform == "instagram":
        import run_scheduler
        return run_scheduler.publish_instagram_story(media_url)
    raise ValueError(f"Unsupported platform: {platform}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True, choices=["facebook", "instagram"])
    parser.add_argument("--media-url", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.dry_run:
        log(f"[dry-run] would post {args.platform} Story from {args.media_url}")
        return 0
    try:
        resp = post_story(args.platform, args.media_url)
        log(f"{args.platform} Story posted: {getattr(resp, 'text', '')[:500]}")
        return 0
    except Exception as e:
        log(f"{args.platform} Story failed: {describe_error(e)}")
        print(f"ERROR: {describe_error(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
