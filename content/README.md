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

## Licensed music on Instagram Reels (optional)

Meta's Audio API can attach officially licensed catalogue music to a Reel at
the moment it's published — no re-render, no adding it by hand in the app.
Add an `audio` block to any item whose `platforms` include `instagram`:

```json
{
  "id": "...",
  "media_type": "video",
  "audio": {
    "audio_id": "587784541076604",
    "audio_volume": 25,
    "video_volume": 100
  }
}
```

- `audio_id` — get one from `python scripts/find_audio.py --query "lo-fi acoustic"`.
- `audio_volume` / `video_volume` — 0-100, both optional. They default to
  **25 / 100**: our shorts already carry mixed VO and SFX, so catalogue music
  sits underneath as a bed rather than competing with the voice.

Requirements and gotchas:

- **Needs Facebook Login credentials** (`IG_FB_ACCESS_TOKEN` + `IG_FB_USER_ID`).
  Meta's docs are explicit: the Audio API "is not supported on the Instagram
  API with Instagram Login". If an item asks for audio and only Instagram
  Login creds are present, the scheduler **fails that item rather than
  publishing it without music** — publishing can't be undone, so a loud
  failure you can retry beats a silent one you'd have to delete.
- Only tracks "authorized for third party use" are reachable. That's a subset
  of what you see in the Instagram app, so a specific trending sound may
  simply not be available.
- There is no way to preview the Reel with its audio attached before it goes
  live. The mix is committed blind.
- `audio_name` is a separate optional top-level field that names the Reel's
  audio page. Meta only lets it be set **once, ever** — here or in the app.

To skip a platform for one post, just omit it from `platforms`. To cancel a
queued post before it goes out, delete its entry or set `"status":
"skipped"`.
