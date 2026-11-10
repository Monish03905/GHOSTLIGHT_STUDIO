# Monetization: the honest picture

Ghostlight was built around one commercial goal: a faceless channel that grows on its own.
This document separates what the studio actually controls from what nobody can promise.

## What nobody can promise

A target like "$20–40k/month" is an outcome, not a feature. Revenue on YouTube depends on
viewers choosing to watch, and no software — this one included — can guarantee attention.
Any product that promises specific income is misleading you. What follows is the realistic
mechanism, and where Ghostlight fits into it.

## How YouTube money actually works

1. **YouTube Partner Program (YPP)** — required before any revenue:
   - 1,000 subscribers **and** 4,000 public watch-hours in 12 months (long-form), **or**
   - 1,000 subscribers and 10M public Shorts views in 90 days.
2. **Watch time & retention drive reach.** The algorithm amplifies what people finish.
3. **RPM** (revenue per thousand views, after YouTube's ~45% cut):
   - Shorts: roughly **$0.05–$0.30** per 1,000 views.
   - Long-form: typically **$1–$10** per 1,000 views, higher in finance/business/tech niches.

What those numbers imply: a $20k/month Shorts-only channel needs tens of millions of views
a month. A long-form channel at a strong $5 RPM needs ~4M views/month. Both are achievable —
channels do it — but they are built over quarters, not weeks, and they are built on retention.

## What Ghostlight controls (and therefore optimizes)

- **Consistency, mechanically.** The scheduler publishes at fixed rhythms (rhythm or
  continuous mode) with daily caps, catch-up windows, and self-pausing on failures.
  Consistency is the single biggest controllable factor in channel growth.
- **Originality at scale.** The novelty ledger rejects any draft within the similarity
  threshold of an earlier film. "Made for the algorithm" channels collapse on repeat
  content; Ghostlight structurally cannot do repeats.
- **Retention-minded craft.** Word-timed karaoke captions, a hook-first script structure,
  chapter pacing in long form, ~−14 LUFS loudness, motion in every scene — the details that
  keep viewers past the first seconds, which is where Shorts live or die.
- **Compliance.** AI content is disclosed (`containsSyntheticMedia`), uploads default to
  private, and no copyrighted material is ever used — narration, score and frames are all
  generated locally. Disclosure protects monetization; reused content forfeits it.
- **Both surfaces.** Shorts for discovery (cheap to make, huge reach variance), long-form
  for RPM (better revenue per view). The default format cycle `short → long → short`
  feeds one with the other.

## Why several channels, and what it changes

Ghostlight runs a portfolio by default. That is not a shortcut to the same revenue spread
thinner — it changes the shape of the bet:

- **Independent shots at an audience.** Three voices with different niches, registers and
  airtimes are three separate classification problems for YouTube. One can find traction
  while the others stay quiet.
- **Cleaner signal.** Each channel's analytics build its own playbook. You can see which
  niche/register actually retains instead of averaging a confused audience, then move budget
  or silence the weakest voice.
- **Per-channel economics.** YPP thresholds, RPM and policy standing apply per channel. A
  channel that reaches 1,000 subscribers and 4,000 watch-hours monetizes on its own; a big
  aggregate audience across unmonetized channels does nothing.
- **Quota is per Google Cloud project.** Five uploads/day per project. Separate projects and
  client secrets per channel keep the ceiling from becoming a single bottleneck; sharing one
  project means sharing 10,000 units/day.
- **The cost is attention.** More channels means more distinct identities to keep coherent.
  The novelty ledger protects against repeats, but it cannot make three unrelated niches
  feel like one brand — that is a choice you make when you name the voices.

A realistic reading: $20–40k/month is still an outcome, not a feature. The portfolio raises
the number of independent attempts, not the probability of any single one succeeding. The
honest lever is retention: a channel people finish is worth more than three they skip.

## A realistic ramp

| Phase | Focus | Why |
|---|---|---|
| Weeks 1–4 | 1–2 films/day, keep everything private, review quality | Fix narration voices, tune niches/tone before spending an audience's first impression |
| Months 1–3 | Flip privacy to public, hold the rhythm, watch retention in YouTube Studio | The algorithm needs volume and time to classify the channel |
| Months 3–6 | Kill underperforming niches (`set niches to …`), double down on what retains | RPM varies wildly by niche; the studio makes redirecting cheap |
| Ongoing | Pause the weakest voice, give its airtimes to the one with watch time | Portfolio discipline: cadence follows retention, not symmetry |
| After YPP | Consider upload cadence ↑ (respecting the 5/day API cap), playlists, thumbnails | Growth compounds on a consistent base |

## Growth levers the studio exposes

- **Niche selection** — the highest-leverage monetization decision (RPM differs by
  multiples). Try `set niches to human_mind, forgotten_history` and compare analytics.
- **Voice quality** — Edge TTS voices are free and good; ElevenLabs is markedly better
  and cheap at this volume. Set `voice.provider` accordingly.
- **Script model** — a frontier LLM (OpenAI/Anthropic/Gemini) writes noticeably better
  twists than a local 4B model; ~1–2¢ per script.
- **Cadence** — `schedule.times`, `schedule.max_per_day`, `schedule.min_gap_minutes`.

## What it will never do

- Buy views, subscribers, or engagement (channel-killers).
- Repurpose other creators' footage or music.
- Hide AI generation from YouTube.
- Publish anything while `youtube.enabled` is false or the schedule is paused.

---

*The studio does the part machines are good at — showing up every day, forever, without
repeating itself. The part that earns money — being worth watching — it can only make
possible, never certain.*
