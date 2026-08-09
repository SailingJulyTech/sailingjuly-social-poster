# Meta (Facebook + Instagram) API Setup

This gets you a **Page Access Token** and an **Instagram Business Account ID** —
the two things `scripts/post_facebook.py` and `scripts/post_instagram.py` need.

Posting to your *own* Page/Instagram account as the app's admin does **not**
require Meta's public App Review process. That review is only needed if
other people will use your app. Since this is just for SailingJuly's own
accounts, you can be posting within about a day.

## 1. Prerequisites

- A Facebook Page for SailingJuly (not a personal profile — Page).
- An Instagram account converted to **Business** or **Creator**, and linked
  to that Facebook Page.
  - On Instagram: Settings → Account type and tools → Switch to
    professional account → Business.
  - Link it to the Page: Settings → Linked accounts → Facebook (or do this
    from the Facebook Page's Settings → Linked Accounts → Instagram).

## 2. Create a Meta Developer account + App

1. Go to https://developers.facebook.com and log in with the Facebook
   account that manages the SailingJuly Page (register as a developer if
   prompted — just requires phone/email verification).
2. My Apps → Create App.
3. Choose use case **"Other"** → app type **"Business"**.
4. Name it something like `sailingjuly-poster`.
5. In the App Dashboard, **Add Product** → add both:
   - **Facebook Login for Business** (or just "Graph API" access — you
     mainly need permission scopes, not a login flow)
   - **Instagram Graph API**

## 3. Get permissions and a token

You need these permission scopes: `pages_show_list`, `pages_read_engagement`,
`pages_manage_posts`, `instagram_basic`, `instagram_content_publish`.

The fastest way to get a working token for your own account:

1. In the App Dashboard, go to **Tools → Graph API Explorer**
   (https://developers.facebook.com/tools/explorer/).
2. Select your app from the dropdown.
3. Click **"Generate Access Token"**, and when prompted, check the boxes
   for the permissions listed above.
4. Log in / grant access as the Page admin.
5. This gives you a **short-lived User Access Token** (expires in ~1 hour).
   Exchange it for a **long-lived token** (~60 days) by running:

   ```bash
   curl -i -X GET "https://graph.facebook.com/v19.0/oauth/access_token?\
   grant_type=fb_exchange_token&\
   client_id=YOUR_APP_ID&\
   client_secret=YOUR_APP_SECRET&\
   fb_exchange_token=YOUR_SHORT_LIVED_TOKEN"
   ```

   (App ID and App Secret are on the App Dashboard's Settings → Basic page.)

6. That long-lived **User** token can then get you a **Page** token, which
   doesn't expire as long as the user token stays valid:

   ```bash
   curl -i -X GET "https://graph.facebook.com/v19.0/me/accounts?\
   access_token=YOUR_LONG_LIVED_USER_TOKEN"
   ```

   The response lists your Pages, each with its own `access_token` — that's
   the `META_PAGE_ACCESS_TOKEN` the scripts use. Page tokens generated from
   a long-lived user token do not expire on their own (they can only be
   invalidated by a password change, deauthorizing the app, or Meta
   security actions).

## 4. Find your IDs

- **Page ID**: shown in the `/me/accounts` response above, or on the Page
  itself under About → Page ID.
- **Instagram Business Account ID**: with your Page token, call:

  ```bash
  curl -i -X GET "https://graph.facebook.com/v19.0/YOUR_PAGE_ID?\
  fields=instagram_business_account&access_token=YOUR_PAGE_ACCESS_TOKEN"
  ```

  The `instagram_business_account.id` in the response is your
  `IG_BUSINESS_ACCOUNT_ID`.

## 5. What to store as secrets

| Secret name | Value |
|---|---|
| `META_PAGE_ACCESS_TOKEN` | The Page access token from step 3 |
| `META_PAGE_ID` | Your Facebook Page ID |
| `IG_BUSINESS_ACCOUNT_ID` | Your Instagram Business Account ID |

See the top-level README for how these map to GitHub Actions secrets.

## Notes / gotchas

- Instagram posting via the API requires the image/video to be reachable at
  a **public URL** at the moment you call the API — Meta's servers fetch it
  from that URL. You can't upload a raw local file directly; host it
  somewhere (e.g. a GitHub raw URL, S3, Cloudinary) first. The scripts
  assume you already have a URL — see `content/queue.json`.
- Reels/video posts go through an async "container" flow (create container
  → poll status → publish). The `post_instagram.py` script handles that.
- Rate limits are generous for a single-Page use case, but avoid posting
  more than a handful of times per day per account to stay well within them.
