# Sending films to Instagram and TikTok

The share kit in a film's drawer can hand a finished film to **Instagram Reels** or
**TikTok**. Both paths are real — Graph API v21 containers and TikTok's Content Posting
API v2 — but they ship **switched off** and cannot work until you bring your own apps and
a public HTTPS address. This guide is that setup.

The studio never sends a post on its own. Every send needs a **per-post confirm**, runs the
hard quality gate first, and is recorded in the `social_posts` table so you can see exactly
what left the machine.

## What you need

| Piece | Why |
|---|---|
| A public **HTTPS** address that reaches this studio | Both networks fetch the film by URL; the studio serves it through a signed, expiring link |
| A Meta developer app + Instagram **business** account | Instagram Reels publishing needs `instagram_content_publish` and review |
| A TikTok developer app with **URL-prefix verification** | The Content Posting API refuses unverified media hosts |
| `secrets/social/` (git-ignored) | Access tokens live here, never in settings or git |

`http://` addresses are rejected on purpose: the API is only useful if the provider can
fetch it, and both providers want TLS.

## 1. Give the studio a public address

Run a reverse proxy or tunnel in front of `127.0.0.1:8787`. Any of these work:

```bash
# Cloudflare Tunnel
cloudflared tunnel --url http://127.0.0.1:8787

# ngrok
ngrok http 8787

# Caddy on a server
studio.example.com {
    reverse_proxy 127.0.0.1:8787
}
```

Then set **The knobs → Instagram & TikTok → Public HTTPS address** to that base, e.g.
`https://studio.example.com` (no trailing slash needed). The drawer's share kit will show
the address once it is accepted.

The studio serves the film at
`/api/social/media/<video_id>?expires=<unix>&sig=<hmac>`. The signature is HMAC-SHA256 over
`video_id:expires` with a key generated once at `secrets/social/signing.key`; links expire
after `social.media_ttl_seconds` (default one hour, minimum five minutes). Nothing is public
without a fresh signature.

> The media host you configure must be the same host you verify with TikTok, because TikTok
> checks the URL prefix of the video it is asked to pull. If Instagram and TikTok need
> different prefixes, verify the one you set in `social.public_url`.

## 2. Instagram Reels

1. In [Meta for Developers](https://developers.facebook.com/) create an app of type
   **Business**, add the **Instagram** product, and connect the Instagram **professional**
   account that should publish (it must be linked to a Facebook Page).
2. Request the permissions `instagram_basic` and `instagram_content_publish`, and submit
   the app for review when you are ready to use it outside your own test users.
3. Generate a long-lived access token with those scopes. Put it, and the Instagram business
   account id, in `secrets/social/instagram.json`:

   ```json
   {
     "access_token": "EAAG…",
     "account_id": "17841400000000000"
   }
   ```

   `account_id` can also be set as **Instagram business account id** in the settings; the
   settings value wins.
4. Turn on **Instagram sending** (and the master **Social sending** switch).

The studio creates a `REELS` container with `video_url` and the caption (the share kit's
description, truncated at 2,200 characters), polls `status_code` until `FINISHED`, then
calls `media_publish`. A container that is still processing after five minutes is recorded
as **pending**, not as a success — check the Instagram app before retrying.

Reels prefer **9:16**. Vertical cuts from the repurpose tab are ideal; a 16:9 film will be
letterboxed and the share kit says so.

## 3. TikTok

1. In [TikTok for Developers](https://developers.tiktok.com/) create an app and add the
   **Content Posting API** product. Request the `video.publish` scope.
2. TikTok will ask you to verify a **URL prefix**. It gives you a file path and its exact
   contents. Paste both into **The knobs → Instagram & TikTok**:
   - `social.tiktok.verify_path` — e.g. `/tiktok-developers-site-verification.txt`
   - `social.tiktok.verify_content` — the exact text TikTok shows

   Restart the studio. It now serves that path as `text/plain` at your public address, but
   **only** if the path starts with `/`, is not under `/api`, and the content is not empty.
   Re-check the public URL before asking TikTok to verify.
3. Authorise your account and put the access token in `secrets/social/tiktok.json`:

   ```json
   { "access_token": "act.…" }
   ```

4. Set **TikTok client key** (`social.tiktok.client_key`) and turn on **TikTok sending**.

The studio POSTs `PULL_FROM_URL` with the signed media link, polls the publish status until
`PUBLISH_COMPLETE`, and records the `publish_id`. `social.tiktok.privacy` defaults to
`SELF_ONLY`; change it to the audience you want (`PUBLIC_TO_EVERYONE`,
`MUTUAL_FOLLOW_FRIENDS`, `FOLLOWER_OF_CREATOR`, …) once you trust the pipeline. A post
still processing after `social.tiktok.max_wait_seconds` (default 180 s) is recorded as
pending.

Two things the API cannot do for you:

- Set TikTok's own **AI-generated label** in the app. The caption carries the disclosure
  text, but the app-level label is a manual toggle.
- Choose the cover frame beyond the timestamp the studio sends (1 second in).

## 4. Using it

Open a finished film → **Share kit** → **Send to Instagram** or **Send to TikTok**. The
button is disabled with the exact missing piece as its tooltip until the target is ready.
Pressing it asks for confirmation, then calls
`POST /api/videos/<id>/social/<target>` with `{ "confirm": true }`.

`GET /api/social/status` returns the same readiness data the drawer shows, plus the twelve
most recent posts. Posts also appear in the film's upload line.

## What can go wrong

| Symptom | Cause |
|---|---|
| Buttons disabled: "Set social.public_url…" | No HTTPS base, or it is still `http://` |
| "Drop the … access token in secrets/social/…" | The JSON file is missing or has no `access_token` |
| Instagram "refused the request" | Token expired, wrong account id, missing app review, or the media URL is not reachable from Meta |
| TikTok "refused the post" with a URL error | The public host does not match the verified URL prefix, or the signed link expired before TikTok fetched it |
| Status stays **pending** | The provider is still transcoding; the studio recorded the id and will not pretend it finished |

## Safety rules that remain

- Master switch and per-target switches default to off.
- A hard quality-gate failure blocks every send.
- TikTok defaults to `SELF_ONLY`.
- Tokens stay in `secrets/`, which is git-ignored. The signing key is generated locally and
  never leaves the machine.
- Nothing is ever posted by the scheduler; sending is always a human action.
