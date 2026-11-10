# Linking YouTube channels

Ghostlight runs several YouTube channels at once. Each voice on **The Network** is its own
editorial identity with its own niches, art direction, airtimes, upload caps, visibility and
Google sign-in. Nothing is shared except the machine that makes the films.

This guide covers the one part that cannot be automated: Google's consent screen. You do it
once per channel, from the studio's own website, and the schedule takes over from there.

## 1. Create one Google Cloud project

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create (or pick) a project.
2. **APIs & Services → Library** → enable:
   - **YouTube Data API v3** — uploads, captions, playlists, thumbnails, comments.
   - **YouTube Analytics API** — watch time, subscribers and revenue learning.
3. **APIs & Services → OAuth consent screen**:
   - User type: **External**.
   - Add the Google accounts that own your channels as **test users** while the app is in
     *Testing*. A test-mode refresh token expires after 7 days; publish the app (or move to
     *In production*) once you are happy with it, or expect to re-consent weekly.
   - Scopes: `youtube.force-ssl`, `yt-analytics.readonly`,
     `yt-analytics-monetary.readonly` (the studio requests these at sign-in).
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application** (the website flow) — or *Desktop app* if you only
     ever use the CLI.
   - **Authorised redirect URIs** — this exact string, matching how you open the studio:
     - locally: `http://127.0.0.1:8787/api/youtube/oauth/callback`
     - on a server: `https://your-domain.example/api/youtube/oauth/callback`
   - Download the JSON. Keep it out of git (`secrets/` is already ignored).

> If the redirect URI does not match exactly, Google returns `redirect_uri_mismatch`.
> `http` and `https`, the port, and the trailing path all matter.

## 2. Give each voice its Google key

Two options, both from the website:

- **Per channel (recommended when channels live in different Google projects):**
  The Network → the channel card → **Google key** → choose that channel's
  `client_secret.json`. It is written to
  `secrets/channels/<channel_id>/client_secret.json`.
- **One shared key:** The knobs → The channel → **Google key**. The file lands in
  `secrets/client_secret.json` and every channel falls back to it.

A channel-specific key always wins. This lets each YouTube brand belong to a different
Google Cloud project, which also keeps quota accounting honest per project.

## 3. Sign in from the website

1. On the channel card press **Connect with Google**.
2. Pick the Google account that owns that YouTube channel. If one Google account manages
   several brand channels, choose the right **Brand Account** on the consent screen.
3. Approve the scopes. Google redirects to
   `/api/youtube/oauth/callback`, the studio exchanges the code, stores the refresh token in
   `secrets/channels/<channel_id>/token.json`, reads the channel name and subscriber count,
   and returns you to The Network with a green confirmation.

On the first successful sign-in the studio also:

- switches `youtube.enabled` on (consent is the explicit go-ahead),
- resumes the schedule (`scheduler.go_live()`),
- writes the connection to the journal.

Repeat for each channel. The chips at the top show `YT: n/n LINKED`.

## 4. What happens next, without you

- The **scheduler** checks each channel's airtimes every 20 seconds with a 45-minute
  catch-up window. Only linked channels auto-produce, so no films pile up for a channel that
  never signed in.
- Each channel keeps a **warm backlog** film ready for its next slot
  (`autopilot.backlog` / `autopilot.backlog_hours`).
- **Autopilot** re-reads analytics every `autopilot.learn_minutes`, learns which niches,
  styles and hours travel, and nudges the next choice. A slice of every decision stays random
  (`autopilot.explore`) so the channel never collapses into one formula.
- **Per-channel visibility** is set in the channel editor (Private / Unlisted / Public) and
  becomes the upload's `privacyStatus`. Scheduled releases stay private until `publishAt`.
- Every upload carries word-timed SRT captions, a thumbnail, a playlist, hashtags and the
  AI disclosure flag (`containsSyntheticMedia`). If `distribution.webhook_url` is set, the
  share kit also goes to a Discord-compatible webhook; `feed.xml` is the RSS mirror.

## 5. Quota and limits

- YouTube gives **10,000 units/day per Google Cloud project** by default. An upload costs
  about **1,600 units**, so each project supports roughly five uploads/day after the small
  reads. The studio meters this per project and per channel.
- If several channels share one project they share its quota. Separate projects (separate
  client secrets) means separate daily allowances.
- The quota day resets at **midnight Pacific**, matching YouTube.
- `youtube.daily_upload_limit` caps uploads per channel per day.

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `redirect_uri_mismatch` | URI not registered exactly | Add the exact callback URL to the OAuth client |
| `access_denied` | Consent cancelled or account not a test user | Add the account as a test user, retry |
| `invalid_grant` after a week | App still in *Testing* | Re-consent, or publish the OAuth app |
| Sign-in worked, uploads still off | `youtube.enabled` was forced off | The knobs → Uploads enabled, or just reconnect |
| “No Google OAuth client for …” | No client secret for that channel/project | Upload the JSON on that channel card |
| Videos stay private | Channel visibility is Private | Change it in the channel editor |
| Two channels show the same account | Wrong Brand Account picked | Disconnect that channel and sign in again, choosing the right brand |

## Security notes

- Tokens and client secrets live under `secrets/` and are git-ignored. Never commit them.
- The OAuth flow uses a server-side `state` map; unknown or expired states are rejected.
- Revoke access from your Google Account → Security → Third-party apps at any time.
- Disconnecting a channel deletes its token; its films stay on the shelf, unassigned.
