"""
One-off maintenance: find and delete a Facebook Page video post by matching
a substring in its description. Used to clean up stray test/verification
posts that shouldn't be left live on the Page.

Env vars required:
  META_PAGE_ACCESS_TOKEN
  META_PAGE_ID

Usage:
  python delete_facebook_post.py --contains "token-fix verification"
  python delete_facebook_post.py --contains "token-fix verification" --confirm

Without --confirm, only lists matches (id, description, created_time) --
nothing is deleted. Deletion is not reversible, so --confirm is required.
"""
import argparse
import requests
from common import env, log

GRAPH_VERSION = "v19.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


def find_matching_videos(page_id, token, contains):
    resp = requests.get(
        f"{GRAPH_BASE}/{page_id}/videos",
        params={"fields": "id,description,created_time", "access_token": token, "limit": 50},
        timeout=30,
    )
    resp.raise_for_status()
    videos = resp.json().get("data", [])
    return [v for v in videos if contains.lower() in (v.get("description") or "").lower()]


def delete_video(video_id, token):
    return requests.delete(f"{GRAPH_BASE}/{video_id}", params={"access_token": token}, timeout=30)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--contains", required=True, help="Substring to match in the post's description")
    parser.add_argument("--confirm", action="store_true", help="Actually delete matches; otherwise just list them")
    args = parser.parse_args()

    page_id = env("META_PAGE_ID")
    token = env("META_PAGE_ACCESS_TOKEN")

    matches = find_matching_videos(page_id, token, args.contains)
    if not matches:
        log(f"No Page videos found matching {args.contains!r} (searched the most recent 50)")
        return

    for v in matches:
        log(f"Match: id={v['id']} created={v.get('created_time')} description={v.get('description')!r}")

    if not args.confirm:
        log(f"{len(matches)} match(es) found. Re-run with --confirm to delete them.")
        return

    for v in matches:
        resp = delete_video(v["id"], token)
        if resp.status_code >= 300:
            log(f"FAILED to delete {v['id']}: {resp.text}")
        else:
            log(f"Deleted {v['id']}: {resp.json()}")


if __name__ == "__main__":
    main()
