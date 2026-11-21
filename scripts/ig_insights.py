"""Pull Instagram Reel and account insights into content/ig_insights.json (read-only).

  python scripts/ig_insights.py            # writes content/ig_insights.json

For each media item: caption, timestamp, type, like/comment counts, and the per-media
insights the token allows (views, reach, saved, shares, total_interactions, Reels watch
time). Each item is matched to its queue slug the same way comment_links.py does, so the
shorts-engine can join it to its own review items. Account level: follower count, and
online_followers (followers online by hour) when the API offers it.

Never posts, edits or deletes anything, and never writes the token anywhere. A metric the
token or API version refuses is recorded under "unavailable" instead of failing the run.
Needs IG_* env (see post_instagram.py) with instagram_manage_insights /
instagram_business_manage_insights.
"""
import datetime
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(__file__))

from common import log, load_json, save_json, describe_error  # noqa: E402
from post_instagram import resolve_target  # noqa: E402
from comment_links import match, QUEUE, MAP  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "content", "ig_insights.json")
REEL_METRICS = ["views", "reach", "saved", "shares", "total_interactions", "likes", "comments",
                "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"]
FEED_METRICS = ["views", "reach", "saved", "shares", "total_interactions", "likes", "comments"]


def get(url, **params):
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def list_media(t):
    url, params, out = f"{t.base}/{t.user_id}/media", {
        "fields": "id,timestamp,permalink,media_product_type,media_type,caption,like_count,comments_count",
        "limit": 100, "access_token": t.token}, []
    while url:
        j = get(url, **(params or {}))
        out += j.get("data", [])
        url, params = j.get("paging", {}).get("next"), None
    return out


def media_insights(t, media_id, metrics):
    """All metrics in one call; on refusal, one call per metric so one bad name costs only itself."""
    def parse(j):
        return {d["name"]: (d.get("values") or [{}])[0].get("value", d.get("total_value", {}).get("value"))
                for d in j.get("data", [])}
    try:
        return parse(get(f"{t.base}/{media_id}/insights", metric=",".join(metrics), access_token=t.token)), {}
    except Exception:  # noqa: BLE001
        got, bad = {}, {}
        for m in metrics:
            try:
                got.update(parse(get(f"{t.base}/{media_id}/insights", metric=m, access_token=t.token)))
            except Exception as e:  # noqa: BLE001
                bad[m] = describe_error(e)[:200]
        return got, bad


def account(t):
    out, bad = {}, {}
    try:
        out.update(get(f"{t.base}/{t.user_id}", fields="followers_count,media_count", access_token=t.token))
    except Exception as e:  # noqa: BLE001
        bad["profile"] = describe_error(e)[:200]
    try:
        j = get(f"{t.base}/{t.user_id}/insights", metric="online_followers", period="lifetime",
                access_token=t.token)
        out["online_followers"] = [v.get("value") for d in j.get("data", []) for v in d.get("values", [])]
    except Exception as e:  # noqa: BLE001
        bad["online_followers"] = describe_error(e)[:200]
    for metric, breakdown in (("follower_demographics", "city"), ("follower_demographics", "age"),
                              ("follower_demographics", "country")):
        try:
            j = get(f"{t.base}/{t.user_id}/insights", metric=metric, period="lifetime",
                    metric_type="total_value", breakdown=breakdown, access_token=t.token)
            out[f"{metric}_{breakdown}"] = j.get("data", [])
        except Exception as e:  # noqa: BLE001
            bad[f"{metric}_{breakdown}"] = describe_error(e)[:200]
    out["unavailable"] = bad
    return out


def main():
    t = resolve_target()
    media = list_media(t)
    queue = load_json(QUEUE)
    ymap = load_json(MAP) if os.path.exists(MAP) else {}
    slugs = {r["media_id"]: r["slug"] for r in match(media, queue, ymap)}
    rows = []
    for m in media:
        reel = (m.get("media_product_type") or "") == "REELS"
        got, bad = media_insights(t, m["id"], REEL_METRICS if reel else FEED_METRICS)
        rows.append({k: m.get(k) for k in ("id", "timestamp", "permalink", "media_product_type",
                                           "media_type", "caption", "like_count", "comments_count")}
                    | {"slug": slugs.get(m["id"]), "insights": got, "unavailable": bad})
    out = {"pulled_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "login_type": t.login_type if hasattr(t, "login_type") else None,
           "account": account(t), "media": rows}
    save_json(OUT, out)
    with_views = sum(1 for r in rows if r["insights"].get("views") is not None)
    log(f"{len(rows)} media, {with_views} with views; account keys: {sorted(out['account'])}")


if __name__ == "__main__":
    main()
