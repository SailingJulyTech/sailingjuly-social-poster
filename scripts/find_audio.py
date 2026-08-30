"""
Search Meta's licensed audio catalogue for tracks you can legally attach to
a Reel through the API, and print their audio_ids.

Requires Instagram API with Facebook Login (IG_FB_ACCESS_TOKEN +
IG_FB_USER_ID). The Audio API does not exist on Instagram Business Login.

Usage:
  python scripts/find_audio.py                          # trending music
  python scripts/find_audio.py --query "lo-fi acoustic"
  python scripts/find_audio.py --audio-type original_sound --query "sailing"
  python scripts/find_audio.py --audio-id 587784541076604   # one track's metadata
  python scripts/find_audio.py --query "ambient" --json     # raw JSON out

Caveats worth knowing before you pick a track:
  - This catalogue is only the audio "authorized for third party use". It is
    a subset of what the Instagram app shows you, so a sound you saw in-app
    may simply not be here.
  - is_ads_eligible=False means the track cannot be used if the Reel is ever
    boosted as an ad.
  - There is no way to preview the finished Reel with the audio attached.
"""
import argparse
import json
import sys
import os

import requests

sys.path.insert(0, os.path.dirname(__file__))

from common import log  # noqa: E402
from post_instagram import resolve_target  # noqa: E402

AUDIO_FIELDS = (
    "audio_id,title,display_artist,duration_in_ms,audio_type,"
    "is_ads_eligible,on_platform_audio_preview_link,ig_username"
)


def require_facebook_login():
    target = resolve_target()
    if not target.supports_audio:
        raise SystemExit(
            f"The Audio API needs Facebook Login, but this resolved to {target}.\n"
            "Set IG_FB_ACCESS_TOKEN and IG_FB_USER_ID (token scopes: instagram_basic, "
            "instagram_content_publish, pages_show_list)."
        )
    return target


def search_audio(target, audio_type, search_query=None):
    params = {
        "audio_type": audio_type,
        "user_id": target.user_id,
        "access_token": target.token,
    }
    if search_query:
        params["search_query"] = search_query
    resp = requests.get(f"{target.base}/ig_audio", params=params, timeout=60)
    resp.raise_for_status()
    return resp.json().get("audio", [])


def get_audio(target, audio_id):
    resp = requests.get(
        f"{target.base}/{audio_id}",
        params={"fields": AUDIO_FIELDS, "access_token": target.token},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def format_row(item):
    duration_ms = item.get("duration_in_ms")
    duration = f"{duration_ms / 1000:.0f}s" if duration_ms else "?"
    artist = item.get("display_artist") or item.get("ig_username") or "-"
    ads = "" if item.get("is_ads_eligible", True) else "  [not ads-eligible]"
    return (
        f"{item.get('audio_id','?'):<22} {duration:>6}  "
        f"{(item.get('title') or '-')[:40]:<40} {artist[:24]:<24}{ads}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default=None, help="Search term; omit for trending")
    parser.add_argument("--audio-type", choices=["music", "original_sound"], default="music")
    parser.add_argument("--audio-id", default=None, help="Fetch one track's metadata instead of searching")
    parser.add_argument("--limit", type=int, default=25, help="Max rows to print")
    parser.add_argument("--json", action="store_true", help="Print raw JSON")
    args = parser.parse_args()

    target = require_facebook_login()

    if args.audio_id:
        item = get_audio(target, args.audio_id)
        print(json.dumps(item, indent=2) if args.json else format_row(item))
        return

    label = f"'{args.query}'" if args.query else "trending"
    log(f"Searching {args.audio_type} for {label}...")
    results = search_audio(target, args.audio_type, args.query)

    if args.json:
        print(json.dumps(results[: args.limit], indent=2))
        return

    if not results:
        print("No results. Try a different search_query or audio_type.")
        return

    print(f"{'AUDIO_ID':<22} {'LEN':>6}  {'TITLE':<40} {'ARTIST':<24}")
    for item in results[: args.limit]:
        print(format_row(item))
    print(
        f"\n{len(results)} result(s). Add one to a queue entry as:\n"
        '  "audio": {"audio_id": "<id>", "audio_volume": 25, "video_volume": 100}'
    )


if __name__ == "__main__":
    main()
