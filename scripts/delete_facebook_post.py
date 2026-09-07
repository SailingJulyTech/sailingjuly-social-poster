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

  # duplicate cleanup: a retry-caused duplicate always has the identical
  # caption as the original it duplicated -- --keep-earliest matches by the
  # same --contains substring but only deletes the newer copy(ies),
  # preserving whichever one actually published first.
  python delete_facebook_post.py --contains "Today's the day. No more excuses." --keep-earliest --confirm

Without --confirm, only lists matches (id, description, created_time) --
nothing is deleted. Deletion is not reversible, so --confirm is required.
"""
import argparse
import requests
from common import env, log

GRAPH_VERSION = "v19.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


def find_matching_videos(page_id, token, contains):
    """Searches both /videos (plain Page video posts) and /video_reels
    (Reels -- the edge run_scheduler.py's post_video_reel() actually
    publishes through, per commit 2a2c29a switching to Reels for
    distribution). A post's actual type isn't known ahead of a search, so
    both edges are queried and the results merged -- fixes a real miss:
    the first version of this script only checked /videos and silently
    found nothing for any Reel, despite Reels being 100% of what this
    project posts today.
    """
    seen_ids = set()
    matches = []
    for edge in ("videos", "video_reels"):
        resp = requests.get(
            f"{GRAPH_BASE}/{page_id}/{edge}",
            params={"fields": "id,description,created_time", "access_token": token, "limit": 50},
            timeout=30,
        )
        resp.raise_for_status()
        for v in resp.json().get("data", []):
            if v["id"] in seen_ids:
                continue
            if contains.lower() in (v.get("description") or "").lower():
                seen_ids.add(v["id"])
                matches.append(v)
    return matches


def delete_video(video_id, token):
    return requests.delete(f"{GRAPH_BASE}/{video_id}", params={"access_token": token}, timeout=30)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--contains", required=True, help="Substring to match in the post's description")
    parser.add_argument("--confirm", action="store_true", help="Actually delete matches; otherwise just list them")
    parser.add_argument(
        "--keep-earliest", action="store_true",
        help="Among the matches, keep only the earliest (by created_time) and delete the rest "
             "-- for cleaning up a retry-caused duplicate (identical caption, published later) "
             "without touching the original it duplicated.",
    )
    args = parser.parse_args()

    page_id = env("META_PAGE_ID")
    token = env("META_PAGE_ACCESS_TOKEN")

    matches = find_matching_videos(page_id, token, args.contains)
    if not matches:
        log(f"No Page videos found matching {args.contains!r} (searched the most recent 50)")
        return

    for v in matches:
        log(f"Match: id={v['id']} created={v.get('created_time')} description={v.get('description')!r}")

    to_delete = matches
    if args.keep_earliest:
        if len(matches) < 2:
            log(f"--keep-earliest given but only {len(matches)} match(es) found -- nothing to delete.")
            return
        ordered = sorted(matches, key=lambda v: v["created_time"])
        keeper = ordered[0]
        to_delete = ordered[1:]
        log(f"--keep-earliest: keeping id={keeper['id']} (created={keeper['created_time']}), "
            f"deleting the other {len(to_delete)} match(es).")

    if not args.confirm:
        log(f"{len(to_delete)} post(s) would be deleted. Re-run with --confirm to delete them.")
        return

    for v in to_delete:
        resp = delete_video(v["id"], token)
        if resp.status_code >= 300:
            log(f"FAILED to delete {v['id']}: {resp.text}")
        else:
            log(f"Deleted {v['id']}: {resp.json()}")


if __name__ == "__main__":
    main()
