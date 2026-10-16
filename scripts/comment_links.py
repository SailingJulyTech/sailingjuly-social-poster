"""Comment the YouTube link on each posted Instagram Reel.

  python scripts/comment_links.py --dry-run        # list media, print the match table, post nothing
  python scripts/comment_links.py --limit 5        # post up to 5 comments

Matches each Instagram media item to a queue entry by posted_at timestamp
(within MATCH_WINDOW_SECONDS), then looks up its YouTube video id in
content/ig_youtube_map.json ({queue_id: youtube_video_id}). Ids already in
content/ig_comment_state.json are skipped. Needs IG_* env (see post_instagram.py)
and, to post, the instagram_manage_comments permission on the token.
"""
import argparse
import datetime
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))

from common import log, load_json, save_json, describe_error  # noqa: E402
from post_instagram import resolve_target  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
QUEUE = os.path.join(ROOT, "content", "queue.json")
MAP = os.path.join(ROOT, "content", "ig_youtube_map.json")
STATE = os.path.join(ROOT, "content", "ig_comment_state.json")
MATCH_WINDOW_SECONDS = 600
PAUSE_SECONDS = 20
BIO_URL = "sailingjulytech.github.io/shorts-links"
TEXT = ("Full video on YouTube: https://www.youtube.com/watch?v={vid}\n"
        "(or link in bio -> {bio}/#{slug})")


def ts(v):
    return datetime.datetime.fromisoformat(v.replace("Z", "+00:00").replace("+0000", "+00:00"))


def list_media(t):
    url, params, out = f"{t.base}/{t.user_id}/media", {
        "fields": "id,timestamp,permalink,media_product_type", "limit": 100,
        "access_token": t.token}, []
    while url:
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        j = r.json()
        out += j.get("data", [])
        url, params = j.get("paging", {}).get("next"), None
    return out


def match(media, queue, ymap):
    posted = [(ts(i["posted_at"]["instagram"]), i["id"]) for i in queue if (i.get("posted_at") or {}).get("instagram")]
    rows = []
    for m in sorted(media, key=lambda m: m["timestamp"], reverse=True):
        mt = ts(m["timestamp"])
        best = min(posted, key=lambda p: abs((p[0] - mt).total_seconds()), default=None)
        ok = best and abs((best[0] - mt).total_seconds()) <= MATCH_WINDOW_SECONDS
        slug = best[1] if ok else None
        rows.append({"media_id": m["id"], "timestamp": m["timestamp"], "permalink": m.get("permalink"),
                     "type": m.get("media_product_type"), "slug": slug, "vid": ymap.get(slug) if slug else None})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=5)
    a = ap.parse_args()
    t = resolve_target()
    queue, ymap = load_json(QUEUE), load_json(MAP)
    state = load_json(STATE) if os.path.exists(STATE) else {"commented": {}}
    rows = match(list_media(t), queue, ymap)
    ready = [r for r in rows if r["vid"] and r["media_id"] not in state["commented"]]
    log(f"{len(rows)} media | {sum(1 for r in rows if r['vid'])} matched | {len(ready)} to comment")
    for r in rows:
        print(f"{r['timestamp'][:16]}  {r['type'] or '?':6}  {r['permalink']}  ->  "
              f"{('https://youtu.be/' + r['vid']) if r['vid'] else 'NO MATCH'}  [{r['slug']}]"
              f"{'  (done)' if r['media_id'] in state['commented'] else ''}")
    if a.dry_run:
        return
    for r in ready[: a.limit]:
        try:
            resp = requests.post(f"{t.base}/{r['media_id']}/comments", timeout=60, data={
                "message": TEXT.format(vid=r["vid"], bio=BIO_URL, slug=r["slug"]), "access_token": t.token})
            resp.raise_for_status()
        except Exception as e:
            log(f"FAILED {r['permalink']}: {describe_error(e)}")
            sys.exit(1)
        state["commented"][r["media_id"]] = resp.json().get("id")
        save_json(STATE, state)
        log(f"commented {r['permalink']}")
        time.sleep(PAUSE_SECONDS)


if __name__ == "__main__":
    main()
