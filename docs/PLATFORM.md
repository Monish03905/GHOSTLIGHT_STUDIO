# The platform, module by module

This page maps the 15-module blueprint Ghostlight grew from onto what actually
ships in this repository — and, just as importantly, onto what does **not**.
Nothing here is a promise of revenue; see [MONETIZATION.md](MONETIZATION.md)
for that conversation.

## What is live

| Module | Where it lives | What it really does |
|---|---|---|
| **1. Trend radar** | `ghostlight/trends.py`, **The Radar** tab | A curated shelf of ~50 subjects across all eight niches, scored daily by interest, momentum, competition and how well the topic fits the selected channel. Opportunity = 40% interest + 25% momentum + 20% inverse competition + 15% fit. An optional live layer pulls Google Trends RSS (`?live=1`); it is cached for 30 minutes and fails back to the shelf without an error. |
| **2. AI story & script** | `ghostlight/content.py`, `scriptwriter.py` | Structured brief → hook → segments → close, with a per-format signature and chapter headings for long form. Uses OpenAI / Anthropic / Gemini / Ollama when configured, otherwise the offline "Muse". Every draft must clear the novelty ledger (`novelty.py`) — films are standalone by construction. |
| **3. AI video generation** | `ghostlight/visuals.py`, `render.py` | Not a text-to-video API. The studio paints its own plates (7 styles × 16 palettes), adds layered parallax, camera moves, grain, transitions and burned-in captions, then composes the film with ffmpeg. Deterministic, free, and never reuses stock footage. |
| **4. Humanised voices** | `ghostlight/tts.py` | Piper neural TTS (default), Edge, OpenAI, ElevenLabs or the system voice, with per-word timings used for karaoke captions. Each channel gets a stable voice choice. Emotion is carried by scripting and pacing, not a per-sentence emotion parameter. |
| **5. Music & SFX** | `ghostlight/music.py`, `render.py` | numpy-composed pads and rhythm matched to the script's mood, sidechain-ducked under narration and loudness-normalised to roughly −14 LUFS. No third-party library of tracks. |
| **6. AI editor / retention** | `render.py` | Pacing is derived from narration length (scene count, shot length, 0.7 s / 1.1 s transitions), captions keep the eye moving, and a hook is written first. There is no frame-by-frame retention model; the editor is a deterministic rule set, not a learned one. |
| **7. Metadata** | `ghostlight/publish.py` | Title, description with disclosure line, hashtags, tags, chapters, word-timed SRT, an optional first comment and a share kit. All generated per film and per channel. |
| **8. Thumbnails** | `render.make_thumbnail_variants` | Three treatments per film — *hero*, *close-up*, *quiet frame* — with measured title-band contrast and a studio recommendation. Swap takes in the film drawer; the choice becomes the upload thumbnail. |
| **9. Publishing** | `ghostlight/youtube.py`, `orchestrator.py` | Per-channel Google OAuth, resumable uploads, scheduled release, playlists, captions, AI disclosure, quota metering. |
| **10. Scheduler & approval** | `scheduler.py`, channel `approval` field | Per-channel airtimes, catch-up window, upload caps, backlog warming, self-pausing after three failures. **Auto** publishes unattended; **Review** parks each finished film on the review shelf until a human presses *Approve & upload*. |
| **11. Quality gate** | `ghostlight/quality.py` | Every render is inspected before any upload: file exists and is not truncated, video and audio streams present, duration sane for the format, bitrate, captions, thumbnail, description length, novelty floor, channel ownership. Hard failures block publishing; warnings are shown but do not. |
| **12. AI brain** | `showrunner.py`, `autopilot` settings | A per-channel playbook learns which niches, registers and hours travel, then re-weights tomorrow's choices while keeping an exploration slice. This is an adaptive bandit over real analytics — not a trained model, and it never invents numbers. |
| **13. Multi-account** | `channels.py`, `secrets/channels/<id>/` | Any number of voices, each with its own token, client secret, quota, airtimes, visibility, approval mode and analytics. |
| **14. Idea wall & calendar** | `ideas.py`, **The Radar** tab | Original pitch cards with an angle, question and director's guidance; one click turns a pitch into a commission. The calendar shows planned airtimes, ready films, films in production and what already published — and says "empty" when it is empty. |
| **15. Dashboard & PWA** | `web/`, `web/sw.js`, `web/manifest.webmanifest` | The studio desk, network, radar, shelf and settings with a live event stream. Installable on desktop and mobile; the shell is cached for offline reading while all studio state stays network-only. |

## Honest boundaries

These are deliberate omissions, not hidden TODOs. Each needs accounts,
infrastructure or review processes that no local build can supply honestly.

- **Instagram / TikTok publishing is not wired.** A real integration needs a
  Meta developer app, a publicly reachable HTTPS callback, business-account
  linking and app review for `instagram_content_publish`. The studio has no
  code path that pretends otherwise. Use the **share kit** in a film's drawer
  to hand a finished film to those networks manually.
- **Multilingual output is not implemented.** `creator.language` exists in
  config, but the Muse corpus, prompts and caption/upload defaults are
  English. Non-English output would need a translated corpus, a matching
  Piper/Edge voice and localised metadata templates. An LLM could translate a
  script today, but the surrounding pipeline would still label it English.
- **Long-form → Shorts repurposing is not automatic.** Every film is a
  standalone essay; cutting clips from it would break the no-continuity
  promise. The shelf lets you make a *new* short on the same subject, but it
  will be written and painted fresh.
- **The SaaS layer is not built.** There are no tenants, billing, teams or
  per-user isolation. This is a single-operator studio that happens to run
  many channels. A hosted multi-tenant product would need auth, storage
  isolation, per-tenant OAuth and a background worker per tenant.
- **Trends are a signal, not a swarm.** The live layer reads Google Trends RSS
  only; it does not scrape Instagram, TikTok or YouTube search. The curated
  shelf is the reliable path and works offline.
- **Analytics are read-only.** The studio reads YouTube Analytics to learn; it
  never buys views, boosts posts or automates engagement. Those are the
  fastest routes to a policy strike.
- **No revenue guarantee.** The quality gate and radar improve the odds of a
  film being watchable and timely. They cannot promise subscribers or income.

## Approval modes at a glance

| Mode | What happens after a render |
|---|---|
| `auto` (default) | Gate runs. If it passes and the channel is linked, the film uploads on the next publish step. |
| `review` | Gate runs. The film is parked with stage `review`. Nothing uploads until **Approve & upload** in the drawer (or `POST /api/videos/<id>/approve`). |

A hard gate failure blocks both modes. The drawer shows every check with its
reason, so a blocked film can be retried rather than forced through.
