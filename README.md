# Ghostlight Studio

**One strange idea at a time.**

Ghostlight is an autonomous, faceless video studio — a small network of YouTube voices
driven by one machine. It writes original scripts, records narration, composes its own
score, paints every frame procedurally, renders the film, and uploads it to each channel
on its own airtimes — with no camera, no stock footage, and no human face.
Every film is a standalone idea: no sequels, no callbacks, no two stories alike —
enforced by a local novelty ledger that rejects drafts too similar to anything made before.

You talk to it like a person: *"make a short about deep-sea light"*, *"upload the latest film"*,
*"pause the schedule"*, *"set times 10:00, 20:30"*. It replies in plain, warm English and
keeps working while you're away.

---

## What it makes

- **A network, not a channel** — three editorial identities ship by default (Ghostlight,
  The Quiet Machine, Field Notes from Elsewhere), each with its own niches, art direction,
  cadence, upload cap, visibility, approval mode and Google account. Add or remove voices on **The Network**.
- **Trend Radar & Idea Wall** — a scored, daily shelf of subjects per niche, an optional
  Google Trends live layer, and original pitch cards you can turn into a commission in one click
- **A quality gate and a review shelf** — every render is inspected before upload (streams,
  duration, bitrate, captions, thumbnail, description, novelty). Channels can publish
  unattended or hold each film for a human *Approve & upload*
- **A content calendar and an AI brain** — planned airtimes, films in flight and what already
  published in one view; the brain shows what its analytics ledger has actually learned
- **Shorts** (vertical 1080×1920) and **long-form** (1920×1080) video essays
- **Original scripts** from an LLM (OpenAI / Anthropic / Gemini / local Ollama) — or from the
  built-in offline "Muse" writer that needs zero API keys
- **Narration** with per-word timing: Piper neural TTS (offline, human-sounding, recommended),
  Edge TTS, OpenAI TTS, ElevenLabs, or the operating system's built-in voice
- **A generative score** — numpy-synthesised pads, chords and rhythm, mood-matched per film
- **Procedural art** — 7 painterly styles × 16 palettes, no two plates alike
- **Layered parallax animation** — a painted plate, a style-aware silhouette midground and a
  drifting foreground of dust, bokeh and light streaks, each moving at its own depth and speed;
  slow camera pushes, sway, a roaming light sweep and living grain in every shot
- **Karaoke-style burned-in captions**, chapter cards, ducked and loudness-normalised audio
  (~ −14 LUFS)
- **A poster and three thumbnail takes** (hero, close-up, quiet frame) per film, with measured
  contrast and a studio recommendation; each carries the channel's own wordmark and tagline
- **Automated distribution** — word-timed SRT captions, thumbnails, playlists, hashtags, an
  optional first comment, a share kit, an optional Discord-compatible webhook and an RSS feed
- **An installable dashboard** — the shell works offline as a PWA; live studio state always
  comes from the server

## The safety defaults

The studio ships deliberately cautious. Out of the box it will **not** publish anything:

| Setting | Default | Why |
|---|---|---|
| `youtube.enabled` | `false` | No uploads until you link a channel |
| `youtube.privacy` / channel visibility | `private` | Even then, uploads stay private first |
| `schedule.enabled` / `paused` | `false` / `true` | Autonomy off until a channel signs in |
| `youtube.disclose_ai` | `true` | Sets `status.containsSyntheticMedia` on every upload |

Only **linked** channels auto-produce, so no films pile up for a voice you never connected.
Completing Google's consent screen is treated as your explicit go-ahead: uploads switch on
and the schedule resumes by itself. You can pause either at any time.

---

## Quick start

```bash
pip install -r requirements.txt
python -m ghostlight serve
```

Open **http://127.0.0.1:8787** — the desk is yours. Three voices are already on
**The Network**. Try typing `make a short about abandoned observatories` and watch the log,
or open a channel card and press **Make one now**.

Everything works with **zero API keys**: the Muse writes, numpy scores, and the renderer paints.

### A natural voice (recommended)

The built-in Windows/macOS voice sounds robotic. Piper is a small neural TTS that runs locally
and sounds human, with no account and no network:

```bash
pip install piper-tts
# download any voice from https://huggingface.co/rhasspy/piper-voices
#   e.g. en_US-ryan-high.onnx + en_US-ryan-high.onnx.json
# put both files in data/models/piper/ — the studio finds them automatically
```

Then set `voice.provider: piper` (already the shipped default). Prosody is tunable:
`voice.piper_length_scale` (speaking rate, `1.02` default), `voice.piper_noise`,
`voice.piper_noise_w`, and `voice.piper_volume`. If Piper is unavailable the studio falls back
to Edge TTS (when reachable), then the system voice, and says so in the log.

### CLI

```bash
python -m ghostlight make --format long --topic "the physics of honey"   # one film now
python -m ghostlight status                                              # the state of the studio
python -m ghostlight upload                                              # publish the newest ready film
python -m ghostlight log -n 50                                           # the desk log
python -m ghostlight connect                                             # link your YouTube channel
python -m ghostlight serve                                               # the web desk + autonomy
```

---

## Linking your YouTube channels

Full walkthrough: **[docs/GOOGLE_SETUP.md](docs/GOOGLE_SETUP.md)**. The short version:

1. In [Google Cloud Console](https://console.cloud.google.com/) create a project and enable
   the **YouTube Data API v3** and **YouTube Analytics API**.
2. Create an **OAuth client ID** (*Web application*) with the redirect URI
   `http://127.0.0.1:8787/api/youtube/oauth/callback` — or your public
   `https://…/api/youtube/oauth/callback`.
3. In the web desk, The Network → **Google key** on a channel card → choose the downloaded
   `client_secret.json`. Repeat per project, or install one shared key under The knobs.
4. Press **Connect with Google** on that channel and sign in with the account (or Brand
   Account) that owns it. The token lands in `secrets/channels/<channel_id>/token.json`.
5. That is the last manual step. The channel's schedule goes live, and autopilot starts
   choosing and publishing on its own airtimes.

**Quota reality:** YouTube grants 10,000 units/day per Google Cloud project and one upload
costs ~1,600 units. The studio meters quota per project and per channel, caps uploads at
**5/day/channel** by default, and resets at **midnight Pacific**. Separate projects per
channel mean separate daily allowances.

Reused/uploaded content and AI narration without disclosure are the fastest ways to lose
monetization; Ghostlight discloses synthetic media on every upload and never reuses footage.

### Running headless (Docker)

```bash
docker compose up -d
docker compose exec studio python -m ghostlight connect   # first sign-in
```

Data, films and secrets live in `./data` and `./secrets` on the host.

---

## The Network

Every channel has a card on **The Network** tab:

| Column | What it controls |
|---|---|
| **Niches** | The idea territories this voice owns |
| **Art direction** | Palettes/styles it is allowed to paint in |
| **Formats** | Shorts, long form, and the rotation between them |
| **Airtimes** | HH:MM slots in `schedule.timezone` (default: system time) |
| **Films per day** | Per-channel daily cap |
| **Visibility** | Private / Unlisted / Public at upload time |
| **Approval** | `auto` publishes on its own; `review` parks each film until you approve it |
| **Voice & tone / audience / CTA** | The showrunner feeds these into every script prompt |

Under the cards:

- **Journal** — every editorial decision, sign-in, lesson and birth, with the reason.
- **The plan** — what each voice will make next, chosen from its playbook.
- **Add a voice** — start from a house template or build one from scratch.

**The Radar** is the editorial desk upstream of the network: scored trends per niche, an
idea wall of original pitches, a content calendar and the AI brain's current reading. A pitch
becomes a commission with one click, and the writer + novelty ledger still decide what ships.

The **quality gate** inspects every finished film before it can upload. Hard failures block
publishing; notes are shown but do not. In `review` mode the film waits on the review shelf
and the drawer offers **Approve & upload**.

Autopilot is the fifth character: it reads each channel's analytics, writes a playbook of
what travels, and re-weights tomorrow's choices. `autopilot.explore` keeps a deliberate slice
random so a channel never calcifies. `autopilot.adapt_schedule` lets it move airtimes toward
the hours that earn subscribers (off by default; it needs at least four films of data).

**Growth** (views, watch hours, subscribers, revenue) is read from YouTube Analytics when a
channel is linked and falls back to public video statistics otherwise. The ledger shows what
actually happened — never a forecast.

---

## Configuration

Everything lives in `config.yaml` (override with `config.local.yaml`). The knobs:

| Path | Meaning |
|---|---|
| `creator.niches` | Idea territories: cosmic, deep_sea, forgotten_history, human_mind, … |
| `script.provider` | `auto`, `openai`, `anthropic`, `gemini`, `ollama`, `offline` |
| `voice.provider` | `auto`, `edge`, `openai`, `elevenlabs`, `piper`, `system` |
| `visuals.style` | `auto`, `aurora`, `ember`, `ink`, `neon`, `paper`, `tide`, `dusk` |
| `schedule.mode` | `rhythm` (fixed times) or `continuous` (one film every N minutes) |
| `schedule.times` | Publishing rhythm, e.g. `["09:30", "19:30"]` |
| `novelty.max_similarity` | How close to an earlier film a draft may be (default 0.30) |
| `youtube.privacy` | Default `private`, `unlisted`, or `public` (channels can override) |
| `autopilot.enabled` | Let the showrunner choose, learn and keep a backlog |
| `autopilot.learn_minutes` | How often analytics are re-read (default 180) |
| `autopilot.explore` | Share of each decision kept random (default 0.18) |
| `autopilot.backlog` / `backlog_hours` | Warm films kept ready, and how far ahead to look |
| `autopilot.max_films_per_day` | Network-wide production ceiling |
| `distribution.webhook_url` | Optional Discord-compatible share webhook |
| `distribution.rss` | Serve `feed.xml` for the shelf |

API keys go in `.env` (git-ignored): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
`ELEVENLABS_API_KEY`. Local Ollama is discovered automatically at `http://127.0.0.1:11434`
and the largest installed model is used.

## How autonomy works

- **One worker, one queue.** Commissions are queued (by you, by the scheduler, or recovered
  after a restart) and produced one at a time: writing → narration → score → art → render.
- **The showrunner** chooses what each voice makes next. It weighs the channel's niches and
  art directions by what actually performed, rotates formats, writes persona-specific
  guidance into the prompt, and records every decision with its rationale in the journal.
- **The scheduler** ticks every 20s. Each channel fires its own airtimes with a 45-minute
  catch-up window and a minimum gap; network and per-channel daily caps are enforced. Only
  channels with a Google sign-in auto-produce. In legacy single-channel *rhythm* mode it
  cycles `short → long → short`; *continuous* mode keeps a minimum gap.
- **Self-pausing.** Three production failures in a row pause the schedule and tell you why.
- **Novelty ledger.** Every script is fingerprinted (premise + shingles + title terms) and
  rejected if it comes within the similarity threshold of any earlier film — so no storyline
  ever connects to another, and the "no repeats" promise is enforced, not just intended.
- **Learning loop.** After each publish, analytics become a per-channel playbook (which
  niches, registers and hours travel). Autopilot re-reads them on a timer and nudges the
  next decision; failures are logged to the journal instead of silently retried forever.

## Honest notes on monetization

See [docs/MONETIZATION.md](docs/MONETIZATION.md) for the full picture — what the studio
controls, what YouTube's thresholds are, and what "passive income" realistically requires.
Short version: Ghostlight maximises everything a channel *can* control (originality,
retention-minded pacing, consistency, metadata, disclosure compliance); nobody can promise
income figures, and any tool that does is selling you something.

For a module-by-module map of the platform — including what is deliberately **not** built
(Instagram publishing, multilingual output, long→short repurposing, a multi-tenant SaaS
layer) — read [docs/PLATFORM.md](docs/PLATFORM.md).

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Project layout

```
ghostlight/
  config.py        settings + defaults            app.py        FastAPI + SSE desk
  db.py            SQLite (videos, channels, …)   cli.py        command line
  events.py        event bus → live log           orchestrator.py  the worker
  llm.py           LLM providers + Ollama         scheduler.py  the multi-channel clock
  prompts.py       script & directive prompts     channels.py   channel templates + airtimes
  scriptwriter.py  writing + validation           showrunner.py editorial brain + learning
  youtube.py       OAuth hub + resumable uploads  publish.py    metadata, SRT, share kit, RSS
  content.py       niches, formats, the Muse      novelty.py    the no-repeats ledger
  tts.py           narration + word timings       music.py      generative score
  visuals.py       procedural art engine          captions.py   ASS karaoke lettering
  trends.py        trend shelf + live RSS layer   ideas.py      the idea wall
  quality.py       pre-upload inspection          render.py     ffmpeg composition + stills
web/               the studio dashboard + PWA shell (no build step)
scripts/           make_icons.py for the PWA assets
docs/              Google setup, monetization, platform map
```

*Every film is written, scored, painted and uploaded by the machine. No faces. No repeats.*
