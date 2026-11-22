# Fact-check triage

Every film drawer has a **Fact check** panel. It pulls the claims out of the narration,
searches a short list of trustworthy sources, and shows which claims found a close textual
match — with links — and which found nothing. It is deliberately called **triage**, not
verification: the studio matches text, it does not read sources for truth.

The panel is on by default (`research.enabled: true`). It only makes outbound calls when you
press the button, and it needs no key.

## What counts as a claim

The extractor scores sentences in the narration. A sentence becomes a claim when it has:

- a number or a year, or
- a superlative / discovery word (`first`, `oldest`, `largest`, `never`, `discovered`,
  `proven`, …), or
- a named entity and a readable length.

It skips sentences shorter than five words or longer than forty-six, stops at
`research.max_claims` (default 5, range 1–10), and keeps the original sentence text.

## Sources

| Provider | What is queried | Filter |
|---|---|---|
| **Wikipedia** | The search API for two hits, then the REST summary for each | Title/summary text |
| **OpenAlex** | Up to two scholarly works | Sends `research.mailto` if set, as good manners |
| **SearXNG** (optional) | Your own instance's JSON search, up to eight results | Hosts must be in `research.allowlist` |

`research.allowlist` is a suffix list by default: `wikipedia.org`, `britannica.com`,
`openalex.org`, `arxiv.org`, `nature.com`, `science.org`, `sciencedirect.com`, `nasa.gov`,
`noaa.gov`, `usgs.gov`, `who.int`, `un.org`, `unesco.org`, `loc.gov`, `si.edu`, `bbc.co.uk`,
`reuters.com`, plus the special entries `edu` and `gov` (any `*.edu` / `*.gov` host). A host
that merely *contains* an allowed name — `nature.com.evil.example` — is rejected.

Only **SearXNG** results are allowlist-filtered before they are kept. Wikipedia is trusted
as Wikipedia, and OpenAlex DOI links can point at publisher domains outside the list; the
report says so in its notes.

To use SearXNG, set `research.searxng_url` to an instance with the JSON format enabled,
e.g. `http://127.0.0.1:8888`. Without it, the panel uses Wikipedia and OpenAlex only.

## Matching

Each source's title and snippet are compared with the claim using shared significant words
(stopwords removed, years tracked separately):

- **supported** — at least 55% of the claim's words appear in the source.
- **related** — at least 25%.
- **unmatched** — below 25%, or no source came back.

A year mismatch caps the score at 0.45 so a near-miss decade cannot read as support. Up to
`research.max_sources_per_claim` (default 3, range 1–5) ranked sources are kept per claim.

The panel shows the verdict, the counts, each claim with its status, confidence and links,
and the fixed caveat:

> This is automated triage, not verification. Sources are found and matched by text, not
> read for truth. Numbers and quotes still need a human, and a missing match is not proof
> that a claim is false.

## Running it

- **Drawer → Fact check → Read the sources.** The request runs in a worker thread so the
  desk stays responsive, then the report is stored on the film.
- `GET /api/videos/<id>/research` returns the stored report.
- `POST /api/videos/<id>/research` re-runs it and stores the new one.

The report is persisted in the film's `research` column and survives restarts. If a source
is unreachable, the run continues and adds a note — you get a report with fewer sources
rather than an error page.

## Honest limits

- **Text matching, not comprehension.** A source can share words with a false claim. Read
  the links.
- **No numeric verification.** The extractor finds numbers but does not compare them to the
  source's figures.
- **No quote checking.** Quotes are not matched to speakers or transcripts.
- **English Wikipedia only.** Other language editions are not queried.
- **No claim is "false" here.** The worst status is *unmatched*, which means the studio
  found nothing to compare — not that the claim is wrong.
- **No browsing behind paywalls.** OpenAlex links can be abstracts or publisher pages; the
  studio does not fetch them.
