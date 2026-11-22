# AI shots: moving bases from a video model

By default every Ghostlight film is painted by the studio's own art engine. **AI shots**
are an optional extra: when enabled, a text-to-video provider renders a few silent,
faceless clips that become the moving base for the first scenes. The painted still stays
the poster and thumbnail; the narration and the studio's score remain the soundtrack; the
upload keeps its AI disclosure.

It ships **off**. Rendering clips costs real money at a provider, so nothing is bought
until you set a provider, a key, and a budget.

## What it does to a film

- Up to `ai_video.max_clips` scenes (default 3) are replaced with generated clips.
- Each clip is looped, cropped to the film's frame and trimmed to the scene duration by the
  normal renderer. Everything after it — captions, grade, transitions — is unchanged.
- A still is extracted from each clip at the one-second mark for the poster and thumbnail.
- The prompts carry a fixed guardrail:

  > Faceless documentary plate: no people, no faces, no on-screen text, no logos, no
  > watermark. Subtle natural motion, cinematic light, one continuous shot.

- If the provider is unreachable, refuses, times out, or produces no still, the film falls
  back to painted plates and the studio logs the reason. A failed AI pass never fails the
  film.

## Providers

| Provider | Setting | Default model | Key |
|---|---|---|---|
| OpenAI Videos | `ai_video.provider: openai` | `sora-2` | `OPENAI_API_KEY` |
| Replicate | `ai_video.provider: replicate` | `minimax/video-01` | `REPLICATE_API_TOKEN` |

Set the key in `.env` (git-ignored):

```bash
OPENAI_API_KEY=sk-...
# or
REPLICATE_API_TOKEN=r8_...
```

Both providers are polled every `ai_video.poll_seconds` (default 5 s) until the clip is
ready or `ai_video.max_wait_seconds` (default 600 s) passes. A timeout is an error, never a
silent success.

For Replicate, `ai_video.model` must be `owner/name`. Its models disagree about dimension
inputs, so the studio sends only `prompt` and `prompt_optimizer`; orientation is written
into the prompt and the clip is fitted at render time.

## Settings

**The knobs → AI shots** (all live under `ai_video.*`):

| Setting | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Master switch |
| `provider` | `none` | `openai` or `replicate` (`sora` is accepted as an alias for OpenAI) |
| `model` | empty | Blank means the provider default |
| `max_clips` | 3 | Clamp on shots per film |
| `seconds` | 4 | Requested clip length (OpenAI) |
| `cost_per_clip_usd` | 0 | Your known price per clip |
| `budget_usd` | 0 | Per-film cap; 0 means no cap |

The budget only bites when **both** a per-clip price and a budget are set: the studio
computes how many shots fit and trims the count before calling the provider. When no price
is set the spend is labelled **unpriced** in the film notes and the observatory, never
recorded as zero.

## Turning it on

1. Set the provider's key in `.env`.
2. In **The knobs → AI shots**, set the provider, turn **Generate moving shots** on, and set
   a budget if you want a hard cap.
3. The readiness line under the group reads *Ready to draw with …* once the key is found.
   `GET /api/ai-video` returns the same state and the exact missing piece when it is not
   ready.
4. Make a film. Shots are requested after the script and plates exist, so their prompts
   follow the actual segments.

## Boundaries

- **Silent.** Both APIs return video only. The studio does not fabricate speech, lip-sync
  or a presenter; the film stays faceless and narrated.
- **First scenes only.** Shots replace the opening plates, not the whole film. The rest of
  the film remains deterministic and free.
- **No guarantee about content.** The guardrail asks for no people or text, but a model can
  still produce them. Review the cut; a clip you dislike is a provider problem, not
  something the studio will silently fix.
- **Real money.** Prices vary by provider and model. Setting `cost_per_clip_usd` is the only
  way the studio can estimate spend; it will not invent a rate.
