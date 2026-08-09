# TikTok API Setup

TikTok is the slowest of the three to get working, and it's worth planning
around that rather than being surprised by it.

## 1. Create a developer account and app

1. Go to https://developers.tiktok.com and log in with the TikTok account
   you'll be posting from (or a business account you control).
2. Manage Apps → Create an App.
3. Fill in the app details (name, description, icon — TikTok reviews these
   too, so keep it clearly branded, e.g. "SailingJuly Auto-Poster").
4. Under **Products**, add **Content Posting API**.

## 2. Understand the access tiers — this is the part that catches people out

TikTok's Content Posting API has two access levels:

- **Unaudited access** (what you get by default while your app is in
  development): you can post, but only as **drafts / private / self-only**
  — content lands in the creator's TikTok inbox for them to review and
  publish manually from the app, or is restricted to non-public visibility
  depending on the exact scope. This is NOT the same as auto-publishing to
  a public feed.
- **Audited / approved access**: lets your app publish directly to public
  with `PUBLIC_TO_EVERYONE` visibility, unattended. This requires
  submitting your app for TikTok's review (Content Posting API audit),
  which asks for a demo video of your posting flow, a description of your
  use case, and can take anywhere from a few days to a few weeks, with no
  guaranteed approval.

**Practical implication:** until the audit is approved, treat the TikTok
script as "queues drafts for you to tap Publish on your phone," not true
hands-off automation. Plan the audit submission early since it's the long
pole here — it doesn't block getting Facebook/Instagram working in the
meantime.

## 3. Get credentials

1. From your app's dashboard, note the **Client Key** and **Client Secret**.
2. Implement (or use a browser-based one-time flow for) OAuth 2.0 to get a
   **user access token** and **refresh token** for the creator account.
   TikTok's login/authorize URL pattern:

   ```
   https://www.tiktok.com/v2/auth/authorize/?client_key=YOUR_CLIENT_KEY&
   scope=video.publish,video.upload&response_type=code&
   redirect_uri=YOUR_REDIRECT_URI&state=xyz
   ```

3. Exchange the returned `code` for an access token:

   ```bash
   curl -X POST "https://open.tiktokapis.com/v2/oauth/token/" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "client_key=YOUR_CLIENT_KEY" \
     -d "client_secret=YOUR_CLIENT_SECRET" \
     -d "code=THE_CODE_FROM_REDIRECT" \
     -d "grant_type=authorization_code" \
     -d "redirect_uri=YOUR_REDIRECT_URI"
   ```

4. This returns `access_token` (short-lived, ~24h) and `refresh_token`
   (long-lived, ~365 days). The scheduler script needs to refresh the
   access token before each run using the refresh token — `post_tiktok.py`
   includes that refresh step, so you mainly need to keep the
   `refresh_token` current as a secret.

## 4. What to store as secrets

| Secret name | Value |
|---|---|
| `TIKTOK_CLIENT_KEY` | From app dashboard |
| `TIKTOK_CLIENT_SECRET` | From app dashboard |
| `TIKTOK_REFRESH_TOKEN` | From the OAuth exchange in step 3 |

## Notes

- Videos are uploaded directly (chunked upload from a URL or file), unlike
  Instagram's fetch-by-URL model — `post_tiktok.py` handles the
  init-upload → send-video → check-status flow.
- Until your app is audited, expect posts to land as drafts for manual
  publish rather than going live automatically — build that into your
  workflow (e.g. a phone notification reminder) rather than assuming
  silent success.
