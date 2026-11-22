# The platform, module by module

This page maps the 15-module blueprint Ghostlight grew from — plus the ten
later additions — onto what actually ships in this repository, and just as
importantly onto what does **not**. Nothing here is a promise of revenue; see
[MONETIZATION.md](MONETIZATION.md) for that conversation.

## What is live

| Module | Where it lives | What it really does |
|---|---|---|
| **1. Trend radar** | `ghostlight/trends.py`, **The Radar** tab | A curated shelf of ~50 subjects across all eight niches, scored daily by interest, momentum, competition and how well the topic fits the selected channel. Opportunity = 40% interest + 25% momentum + 20% inverse competition + 15% fit. An optional live layer pulls Google Trends RSS (`?live=1`); it is cached for 30 minutes and fails back to the shelf without an error. |
| **2. AI story & script** | `ghostlight/content.py`, `scriptwriter.py` | Structured brief → hook → segments → close, with a per-format signature and chapter headings for long form. Uses OpenAI / Anthropic / Gemini / Ollama when configured, otherwise the offline "Muse". Every draft must clear the novelty ledger (`novelty.py`) — films are standalone by construction. |
| **3. AI video generation** | `visuals.py`, `render.py`, `aivideo.py` | By default the studio paints its own plates (7 styles × 17 palettes), adds layered parallax, camera moves, grain, transitions and burned-in captions, then composes with ffmpeg — deterministic and free. When `ai_video.enabled` is on and a key exists, OpenAI Videos or Replicate can also supply **silent moving bases** for the first shots; the still stays the poster and thumbnail, the clip is looped and cropped to the frame, and spend is clamped by `ai_video.budget_usd`. Faceless prompt guardrails and the AI disclosure are unchanged. |
| **4. Humanised voices** | `ghostlight/tts.py` | Piper neural TTS (default), Edge, OpenAI, ElevenLabs or the system voice, with per-word timings used for karaoke captions. Each channel gets a stable voice choice. Emotion is carried by scripting and pacing, not a per-sentence emotion parameter. |
| **5. Music & SFX** | `ghostlight/music.py`, `render.py` | numpy-composed pads and rhythm matched to the script's mood, sidechain-ducked under narration and loudness-normalised to roughly −14 LUFS. No third-party library of tracks. |
| **6. AI editor / retention** | `render.py` | Pacing is derived from narration length (scene count, shot length, 0.7 s / 1.1 s transitions), captions keep the eye moving, and a hook is written first. There is no frame-by-frame retention model; the editor is a deterministic rule set, not a learned one. |
| **7. Metadata** | `ghostlight/publish.py` | Title, description with disclosure line, hashtags, tags, chapters, word-timed SRT, an optional first comment and a share kit. All generated per film and per channel. |
| **8. Thumbnails** | `render.make_thumbnail_variants` | Three treatments per film — *hero*, *close-up*, *quiet frame* — with measured title-band contrast and a studio recommendation. Swap takes in the film drawer; the choice becomes the upload thumbnail. |
| **9. Publishing** | `youtube.py`, `social.py`, `orchestrator.py` | Per-channel Google OAuth, resumable uploads, scheduled release, playlists, captions, AI disclosure, quota metering. Optional Instagram Reels and TikTok posting (module 23) runs from the share kit after the same quality gate. |
| **10. Scheduler & approval** | `scheduler.py`, channel `approval` field | Per-channel airtimes, catch-up window, upload caps, backlog warming, self-pausing after three failures. **Auto** publishes unattended; **Review** parks each finished film on the review shelf until a human presses *Approve & upload*. |
| **11. Quality gate** | `ghostlight/quality.py` | Every render is inspected before any upload: file exists and is not truncated, video and audio streams present, duration sane for the format, bitrate, captions, **caption drift against the word timings**, **measured loudness with ffmpeg `volumedetect`**, thumbnail, description length, novelty floor, **the stored editorial read** and channel ownership. Hard failures block publishing; warnings are shown but do not. |
| **12. AI brain** | `showrunner.py`, `autopilot` settings | A per-channel playbook learns which niches, registers and hours travel, then re-weights tomorrow's choices while keeping an exploration slice. This is an adaptive bandit over real analytics — not a trained model, and it never invents numbers. |
| **13. Multi-account** | `channels.py`, `secrets/channels/<id>/` | Any number of voices, each with its own token, client secret, quota, airtimes, visibility, approval mode and analytics. |
| **14. Idea wall & calendar** | `ideas.py`, **The Radar** tab | Original pitch cards with an angle, question and director's guidance; one click turns a pitch into a commission. The calendar shows planned airtimes, ready films, films in production and what already published — and says "empty" when it is empty. |
| **15. Dashboard & PWA** | `web/`, `web/sw.js`, `web/manifest.webmanifest` | The studio desk, network, radar, shelf and settings with a live event stream, dressed as **Aurora Theatre** — a drifting star canvas, layered aurora washes, glass panels, a warm ghost light and a serif/sans type pairing. **Four moods** — night, daylight, twilight and ember — repaint the stage, aurora, star tint and browser theme-colour, and the choice is remembered in `localStorage`. A ⌘/Ctrl-K command palette searches every view, action, film, chapter and mood, driving the same API calls a click would; bare keys move between views (`1`–`5`), open the observatory (`O`), cycle moods (`T`), open the bell (`B`) and focus the command bar (`/`). A live studio clock sits in the masthead, and the film drawer carries a chapter rail built from real narration timings that seeks the player. Installable on desktop and mobile; shell assets are fetched network-first (cache `ghostlight-v6`) so an update lands on the next load, with the cache used only offline. All studio state stays network-only. |
| **16. Vertical repurposing** | `ghostlight/repurpose.py`, `orchestrator.repurpose` | Cuts complete-thought clips from a finished film using the word timings in `narration.json`. Windows are 15–60 s, non-overlapping, deduplicated by digest and text overlap, and never split a spoken sentence. Each cut becomes its own vertical child record (`kind=clip`) with blurred-fill framing, fitted foreground and burned-in captions, so the normal gate, approval, share-kit and upload paths work unchanged. |
| **17. Localization** | `ghostlight/languages.py`, the film drawer | The configured model translates title, hook, description, tags and every spoken segment into fifteen languages — English, Hindi, Telugu, Tamil, Bengali, Marathi, Gujarati, Kannada, Malayalam, Arabic, Japanese, Spanish, French, German and Portuguese. Segment counts are validated and unchanged source text is rejected rather than passed off as a translation. Captions keep the original timings; a localized voiceover is recorded only when `edge-tts` is reachable and is labelled with its real provider. |
| **18. Editorial read** | `ghostlight/editorial.py`, the film drawer | A deterministic second read of the script: hook, pacing, clarity, payoff, invitation, repetition, structure and rights flags, with a 0–100 score, concrete notes and hook starting points. It calls no model and explicitly labels its retention band a structural guess, not a forecast. |
| **19. Notification center** | `notifications` table, `EventBus.notify`, the masthead bell | Durable studio notices for completed films, gate blocks, review requests, publications, failed localizations, exports and prunes. Unread counts survive restarts and the bell opens the relevant film. This is separate from the transient live log. |
| **20. Library & maintenance** | `ghostlight/library.py`, **The knobs → The archive** | Storage report (records, tracked and on-disk size, free space, largest files, orphan folders), a catalogue ZIP with JSON/CSV and optional media, a safe SQLite backup, and a guarded prune. Pruning is preview-first, requires an explicit confirm, and only ever touches archived or failed films inside the studio's own video directory. |
| **21. Observatory** | `ghostlight/observatory.py`, `GET /api/observatory`, the ◎ overlay | Provider bench, cost ledger and pipeline observability in one overlay (`O`). The bench reports seven providers from live status — writer (LLM provider), voice, score, art, render, radar and publishing — with where each runs and what it needs; an unavailable provider is shown as offline with the reason (publishing waits on a real Google OAuth grant). The ledger counts words, voiced minutes, rendered minutes, uploads and on-disk bytes from the films themselves, then prices them with a zero-default rate card (`costs.*`, editable in the overlay, persisted through `PATCH /api/settings`). Everything is labelled an estimate, never a bill. **Before you run** is a forecast for the *next* film: each format's length window midpoint at `script.words_per_minute` becomes words, voiced minutes, rendered minutes and disk, priced at the same rate card; storage uses the measured average of your own rendered minutes or states its assumption. The pipeline shows each recent film's progress through written → voiced → scored → cut → gated → published plus its persisted stage trail; `EventBus.step` stores stage events in SQLite so the trail survives restarts, and SSE stage events refresh the overlay live. |
| **22. The readout** | `ghostlight/evaluation.py`, `GET /api/videos/{id}/evaluation`, the film drawer | Seven deterministic signals from a film's own files: script (stored editorial read), originality (novelty ledger), voice (timed words per minute and narration coverage), picture (ffprobe resolution, bitrate, fps), captions (drift between the last cue and the cut), delivery (gate hard fail veto, notes shaved) and rights (editorial keyword flags). Missing artefacts read `—`; only measured signals enter the weighted total. The fixed caveat says the readout does no factual verification, no legal clearance and no prediction of reach. |
| **23. Instagram & TikTok** | `ghostlight/social.py`, `GET /api/social/status`, the share kit | Real Graph API v21 Reels (container → status poll → publish) and TikTok Content Posting API v2 (`PULL_FROM_URL`) code paths. The studio signs its own `/api/social/media/<id>` links with an HMAC key under `secrets/social/`, requires a public HTTPS base, and serves the operator's TikTok URL-prefix verification file. Every send needs `confirm: true`, passes the hard quality gate first, and is recorded in `social_posts`. Off by default; TikTok defaults to `SELF_ONLY`. |
| **24. AI shots** | `ghostlight/aivideo.py`, **AI shots** settings | OpenAI Videos or Replicate text-to-video as silent moving bases for the first scenes, budget-capped before anything is bought. Prompts carry a faceless/documentary guardrail; a failed or disabled provider falls back to painted plates with a logged reason. The still poster and the AI disclosure stay in place. |
| **25. Research triage** | `ghostlight/research.py`, the film drawer's **Fact check** panel | Extracts numbered, dated, superlative and named claims from the narration, searches Wikipedia and OpenAlex (plus an optional SearXNG instance) for allowlisted sources, and scores each claim by word overlap: ≥55% supported, ≥25% related, else unmatched. Sources are linked and kept. The fixed caveat says this is triage, not verification, and a missing match is not proof of falsity. |

## Honest boundaries

These are deliberate omissions, not hidden TODOs. Each needs accounts,
infrastructure or review processes that no local build can supply honestly.

- **Instagram / TikTok publishing is wired but unconfigured and off.** The
  code paths are real, but sending still needs what no repository can supply:
  a Meta developer app with an Instagram business account and review for
  `instagram_content_publish`, a TikTok developer app with URL-prefix
  verification, and a publicly reachable HTTPS address that serves this
  studio's signed media links. Without all of that the share kit shows both
  targets as not ready with the exact missing piece. Posts are never sent
  automatically and never without `confirm: true`.
- **Localization needs a real model and a real voice.** Metadata and caption
  translation runs through the configured LLM provider; without one it fails
  and says so instead of guessing. A localized voiceover additionally needs
  `edge-tts` and network access. The original film is never relabelled: the
  localization is a separate record under `data/videos/<id>/lang/<code>/`.
  The offline Muse cannot translate, and no voice-cloning service is used —
  cloning would need the speaker's consent and a provider account.
- **Vertical cuts are excerpts, not sequels.** Repurposing lifts complete
  thoughts from an existing film; it does not create a series, continue a
  story or add new narration. The no-continuity and faceless rules still
  apply, and the cut keeps its parent film's AI disclosure.
- **Facebook is not wired.** Instagram and TikTok have paths; Facebook Pages
  do not. The share kit still hands the caption, captions file and link to the
  operator for networks the studio cannot post to itself.
- **No avatars, lip-sync or on-camera presenters.** The studio is faceless by
  design. Digital humans, talking heads and cloned likenesses are out of
  scope, not missing switches.
- **AI shots are moving scenery, not a talking head.** Clips come back silent
  and loop under the narration as first-scene bases; the prompt guardrail asks
  for no people, faces, text or logos, but a provider can still surprise you —
  rejecting a clip is the operator's call. They cost real money and only run
  when enabled with a budget set.
- **The SaaS layer is not built.** There are no tenants, billing, teams or
  per-user isolation. This is a single-operator studio that happens to run
  many channels. A hosted multi-tenant product would need auth, storage
  isolation, per-tenant OAuth and a background worker per tenant.
- **Trends are a signal, not a swarm.** The live layer reads Google Trends RSS
  only; it does not scrape Instagram, TikTok or YouTube search. The curated
  shelf is the reliable path and works offline.
- **Research is triage, not fact-checking.** The panel finds allowlisted
  sources and matches claims to them by text, keeping the links and saying
  which claims found nothing. It does not read sources for truth, cannot
  resolve numbers or quotes, and a missing match proves nothing. The editorial
  rights check remains a keyword heuristic, not legal clearance.
- **No billing or team accounts.** Usage stays on one machine and one
  operator. Adding subscriptions, seats or usage metering would require a
  real payment processor, auth and tenancy model — none of which is faked
  here.
- **Analytics are read-only.** The studio reads YouTube Analytics to learn; it
  never buys views, boosts posts or automates engagement. Those are the
  fastest routes to a policy strike.
- **The observatory is local and honest.** It reads this machine's own state —
  no external APM, tracing service or telemetry upload. Cost figures are
  measured usage multiplied by a rate card you set, and are always labelled
  estimates; with the default zero rates the ledger reads `USD 0.00` because
  the local pipeline genuinely costs nothing per film. The forecast is a
  midpoint-of-window projection at that same rate card, and says whether its
  storage figure was measured from your renders or assumed. A provider that
  is not configured is shown offline, not inferred as working.
- **The readout is not a critic.** It scores only what can be measured in the
  film's own files and prints the same caveat every time: no factual
  verification, no legal clearance, no prediction of reach. A missing signal
  reads `—` instead of borrowing a number from somewhere else.
- **No revenue guarantee.** The quality gate and radar improve the odds of a
  film being watchable and timely. They cannot promise subscribers or income.

## Reliability notes

- **Local models are not routed through proxies.** Ollama is reached on
  localhost with proxy environment ignored, so a malformed `NO_PROXY` entry
  cannot fail the call before the socket opens.
- **Slow models fail honestly.** Provider calls time out (120 s for
  localization) and the attempt is stored as `failed` with the reason. No
  translation, caption or voice is fabricated to fill the gap.
- **Updates are not trapped behind the PWA cache.** Shell assets are
  network-first and fall back to the cache only offline; API responses are
  never cached.
- **Notifications are durable, the log is not.** The bell reads from SQLite
  and survives restarts; the desk log is the transient event stream.
- **Stage trails are durable too.** The observatory's pipeline reads persisted
  `events` rows written by `EventBus.step`, so a film's trail is still there
  after a restart. The desk log remains the live tail beside it.

## Approval modes at a glance

| Mode | What happens after a render |
|---|---|
| `auto` (default) | Gate runs. If it passes and the channel is linked, the film uploads on the next publish step. |
| `review` | Gate runs. The film is parked with stage `review`. Nothing uploads until **Approve & upload** in the drawer (or `POST /api/videos/<id>/approve`). |

A hard gate failure blocks both modes. The drawer shows every check with its
reason, so a blocked film can be retried rather than forced through.
