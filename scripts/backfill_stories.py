"""
Backfill Stories for already-posted video queue entries.

  python scripts/backfill_stories.py --platform facebook --dry-run
  python scripts/backfill_stories.py --platform instagram --since-hours 24 --limit 3

Picks queue entries with media_type "video" whose posted_at[platform] is
within --since-hours (Stories expire after 24h, so older posts are pointless
and would just be spam), oldest first, skipping ids already recorded in
content/story_backfill_state.json ({platform: [ids]}). Posts at most --limit
stories with a pause between, recording each success in the state file
immediately. --dry-run prints the plan, needs no credentials, writes nothing.
"""
import argparse
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from common import log, load_json, save_json, describe_error  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_QUEUE_PATH = os.path.join(ROOT, "content", "queue.json")
DEFAULT_STATE_PATH = os.path.join(ROOT, "content", "story_backfill_state.json")
PAUSE_SECONDS = 60


def parse_ts(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_state(path):
    return load_json(path) if os.path.exists(path) else {}


def pick_eligible(queue, state, platform, since_hours, now):
    """Eligible entries, oldest posted first."""
    done = set(state.get(platform, []))
    cutoff = now - datetime.timedelta(hours=since_hours)
    picked = []
    for item in queue:
        if item.get("media_type") != "video" or not item.get("media_url"):
            continue
        posted = (item.get("posted_at") or {}).get(platform)
        if not posted or item["id"] in done:
            continue
        ts = parse_ts(posted)
        if ts < cutoff:
            continue
        picked.append((ts, item))
    picked.sort(key=lambda p: p[0])
    return [item for _, item in picked]


def post_story(platform, media_url):
    import story_once
    return story_once.post_story(platform, media_url)


def run(platform, since_hours, limit, dry_run, queue_path, state_path,
        now=None, sleep=time.sleep, poster=None):
    poster = poster or post_story
    now = now or datetime.datetime.now(datetime.timezone.utc)
    queue = load_json(queue_path)
    state = load_state(state_path)
    eligible = pick_eligible(queue, state, platform, since_hours, now)
    chosen = eligible[:limit]
    log(f"{len(eligible)} eligible for {platform} (last {since_hours}h); processing {len(chosen)}")
    failures = 0
    for i, item in enumerate(chosen):
        if dry_run:
            log(f"[dry-run] would post {platform} Story: {item['id']} "
                f"(posted {item['posted_at'][platform]})")
            continue
        if i > 0:
            sleep(PAUSE_SECONDS)
        try:
            poster(platform, item["media_url"])
        except Exception as e:
            failures += 1
            log(f"{platform} Story failed for {item['id']}: {describe_error(e)}")
            continue
        state.setdefault(platform, []).append(item["id"])
        save_json(state_path, state)
        log(f"{platform} Story posted for {item['id']}")
    return failures


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--platform", required=True, choices=["facebook", "instagram"])
    p.add_argument("--since-hours", type=float, default=24)
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--queue", default=DEFAULT_QUEUE_PATH)
    p.add_argument("--state", default=DEFAULT_STATE_PATH)
    a = p.parse_args(argv)
    failures = run(a.platform, a.since_hours, a.limit, a.dry_run, a.queue, a.state)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
