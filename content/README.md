# Content queue

`queue.json` is the list of upcoming posts. Add a new item any time you have
something ready:

```json
{
  "id": "2026-08-20-something-unique",
  "scheduled_for": "2026-08-20T15:00:00Z",
  "platforms": ["facebook", "instagram", "tiktok"],
  "caption": "Your caption / hook text here.",
  "media_url": "https://publicly-reachable-url/to/your/file.mp4",
  "media_type": "video",
  "status": "pending",
  "posted_at": {}
}
```

Field notes:

- `scheduled_for` — UTC, ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`). The item posts
  on the next scheduler run *at or after* this time — it won't post early,
  but if the workflow runs every 30 min it may post up to ~30 min late.
- `platforms` — any of `facebook`, `instagram`, `tiktok`. Each is posted
  independently; if one fails the others still go out.
- `media_type` — `photo` or `video`. For Instagram, video posts are always
  sent as Reels.
- `media_url` — must be a public URL both Meta's and TikTok's servers can
  fetch (a raw GitHub URL, S3/Cloudinary link, etc.) — not a local file
  path.
- `status` — leave as `"pending"` when you add it. The scheduler flips it
  to `"posted"` or `"failed"` and fills in `posted_at` per platform after a
  run, then commits the updated file back to the repo so items are never
  double-posted.

To skip a platform for one post, just omit it from `platforms`. To cancel a
queued post before it goes out, delete its entry or set `"status":
"skipped"`.
