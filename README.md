# SailingJuly social auto-poster

Automates posting to the SailingJuly Facebook Page, Instagram Business
account, and TikTok account, using each platform's official API — no
browser automation, no third-party scheduler in the loop.

## How it works

1. You add posts to `content/queue.json` — a caption, a public media URL,
   which platforms it should go to, and when.
2. A GitHub Actions workflow (`.github/workflows/scheduled-post.yml`) runs
   every 30 minutes, checks the queue for anything due, and posts it via
   `scripts/run_scheduler.py`.
3. The workflow commits the queue back to the repo with each item marked
   `posted` or `failed`, so nothing double-posts and you can see history
   in the git log.

## One-time setup

1. **Meta (Facebook + Instagram)**: follow `docs/META_SETUP.md` to get
   `META_PAGE_ACCESS_TOKEN`, `META_PAGE_ID`, and `IG_BUSINESS_ACCOUNT_ID`.
2. **TikTok**: follow `docs/TIKTOK_SETUP.md` to get `TIKTOK_CLIENT_KEY`,
   `TIKTOK_CLIENT_SECRET`, and `TIKTOK_REFRESH_TOKEN`. Note TikTok's audit
   process is the long pole — start it early. Until it's approved, TikTok
   posts land as private/draft, not public.
3. **Push this repo to GitHub** — run the included script:

   ```bash
   chmod +x push_to_github.sh
   ./push_to_github.sh
   ```

   It checks for the GitHub CLI (`gh`), confirms you're authenticated as
   the right account, sets the commit identity, and creates + pushes the
   repo in one go. Safe to re-run if something fails partway through.
4. **Add the secrets**: in the GitHub repo, go to Settings → Secrets and
   variables → Actions → New repository secret, and add each of:
   - `META_PAGE_ACCESS_TOKEN`
   - `META_PAGE_ID`
   - `IG_BUSINESS_ACCOUNT_ID`
   - `TIKTOK_CLIENT_KEY`
   - `TIKTOK_CLIENT_SECRET`
   - `TIKTOK_REFRESH_TOKEN`

   Optional: under the "Variables" tab (not Secrets — this one isn't
   sensitive), add `TIKTOK_PRIVACY_LEVEL` set to `SELF_ONLY` until your
   TikTok app is audited, then switch it to `PUBLIC_TO_EVERYONE`.
5. **Enable the workflow**: it's already set to run every 30 minutes once
   it's on GitHub's default branch. You can also trigger it manually from
   the Actions tab (workflow_dispatch) to test before waiting for the
   schedule.

## Day to day usage

Add an entry to `content/queue.json` (see `content/README.md` for the exact
format) whenever you have something ready to schedule. That's it — the
workflow picks it up on its next run.

To test without actually posting anywhere:

```bash
pip install -r requirements.txt
export META_PAGE_ACCESS_TOKEN=... META_PAGE_ID=... IG_BUSINESS_ACCOUNT_ID=...
export TIKTOK_CLIENT_KEY=... TIKTOK_CLIENT_SECRET=... TIKTOK_REFRESH_TOKEN=...
python scripts/run_scheduler.py --dry-run
```

## Repo layout

```
.github/workflows/scheduled-post.yml   -- the cron job
content/queue.json                     -- your post queue (edit this)
content/README.md                      -- queue format docs
docs/META_SETUP.md                     -- Facebook + Instagram API setup
docs/TIKTOK_SETUP.md                   -- TikTok API setup
scripts/post_facebook.py               -- Facebook Graph API calls
scripts/post_instagram.py              -- Instagram Graph API calls
scripts/post_tiktok.py                 -- TikTok Content Posting API calls
scripts/run_scheduler.py               -- reads the queue, posts what's due
scripts/common.py                      -- shared helpers
requirements.txt
push_to_github.sh                      -- one-shot script to init + push this repo
```

## Limitations to know about going in

- **TikTok won't auto-publish publicly until your app passes TikTok's
  Content Posting API audit.** Until then, posts arrive as drafts for
  manual publish in the TikTok app.
- **Media must be hosted at a public URL** before it's queued (both Meta
  and TikTok fetch media by URL, they don't accept raw uploads through
  these endpoints as configured here). Where you host that (GitHub raw
  URLs, S3, Cloudinary, etc.) is up to you — happy to wire that up too if
  useful.
- **Meta Page tokens generated this way don't auto-expire**, but can be
  invalidated by a password change or deauthorizing the app — if posts
  start failing with an auth error, regenerate the token per
  `docs/META_SETUP.md` step 3 and update the GitHub secret.
- The workflow needs `contents: write` permission to commit queue updates
  back — that's already set in the workflow file, but double check your
  repo's Settings → Actions → General → Workflow permissions allows it if
  commits aren't landing.
