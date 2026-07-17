# cv-drafter-local

**A CV and cover-letter drafter that runs entirely on your own machine, for free,
and refuses to lie about your experience.**

You paste a job advert; it drafts a keyword-tuned **screening CV** (`.docx`), a
designed **interview CV** (`.pdf`) and a matching **cover letter**, in your house
style, using only facts from your own profile, and it tells you where you genuinely
fall short of the advert instead of papering over it.

Three things make it different from the flood of AI CV tools:

- **Local:** it runs against a model on your own laptop (LM Studio / Ollama). Your
  CV, your history and the roles you are chasing never leave the machine.
- **Free:** no cloud API, no subscription, no per-draft cost. A full CV draft is
  about £0 and 50 seconds.
- **Honest by design:** the model may only write prose. Every employer, job title
  and date comes straight from your profile, and a verification guard blocks any
  invented experience before it reaches the page.

`Python · local LLM · MIT-licensed · no data leaves your device`

## Why

Recruiters are now flooded with AI-written CVs, and they are increasingly screening
for the tells: fabricated metrics, inflated titles, stretched dates, tortured
phrasing. A CV that invents a number wins you a call you then fail in the room.

This tool takes the opposite bet. It uses AI for the thing AI is genuinely good at,
rephrasing your real experience to mirror an advert's language, and architecturally
prevents it from doing the thing that gets you caught: making things up.

## What you get

One command produces everything for a role:

- **Screening CV:** ATS-plain `.docx` (single column, no tables or graphics) so the
  automated parsers on job portals read it cleanly.
- **Interview CV:** a designed `.pdf` for human readers at shortlist stage (needs a
  local Chrome; degrades gracefully to "skipped" if absent).
- **Cover letter:** `.docx` to attach and `.txt` to paste into an email or portal.
- **A coverage score and an honesty report** printed on every run, so you know how
  well you match and exactly what to check before sending.

## Honest by design

The model only ever writes prose: the summary, the skill phrasing, the bullet
wording. The *structure* of your career (which employers, which titles, which dates,
in which order) is copied verbatim from `profile.json` and never touched. One-line
roles are passed through un-inflated rather than padded out.

Then `honesty.py` verifies every draft against your profile before it is saved:

- **ERROR (blocks the claim):** an employer, title or date that is not in your
  profile (invented, renamed, reordered or stretched experience).
- **WARNING (flagged for review):** a figure that appears nowhere in your profile (a
  likely fabricated metric), or an em dash (a house-style tell).

A typical run looks like this:

```
$ python draft_cv.py --jd-file jd.txt --title "AI Delivery Manager"
saved:    outputs/Alex Rivera - Screening - AI Delivery Manager.docx
          outputs/Alex Rivera - Interview - AI Delivery Manager.pdf
coverage: 91%  (10/11 keywords)
gaps:     RPA
honesty:  review — 1 warning(s)
  review  unverified figure '3 million' in summary
```

Here it has surfaced a genuine gap (no RPA experience) and caught the model inflating
a "2 million records" fact into "3 million", before it reached the CV.

**How well does it hold up?** Across five real job adverts, benchmarked against the
same CVs drafted by a frontier cloud model ([`evals/RESULTS.md`](evals/RESULTS.md)):

| | local (this tool) | cloud model |
|---|---:|---:|
| **Hard fabrications** | **0** | 0 |
| Keyword coverage (avg) | 85% | 96% |
| Cost per draft | **£0** | paid API |

A full local draft takes about 50 to 58 seconds. Zero fabrications across every
draft: that is the architecture working. Coverage is lower and more variable than a
frontier model (63% to 100% run to run), so it is best treated as a **fast, free,
honest first draft that you review and polish**, not a replacement for a final human
pass on a role that really matters.

## Built by directing an AI agent

This is also a small proof of a bigger idea. It was built by an agile delivery
manager, not a professional software engineer, by pair-programming with an AI coding
agent (Claude Code), one small user story at a time. The result is not a throwaway
script: it ships with 31 tests, a linter, an honesty guard and a reproducible eval.
Modern agentic tooling now lets someone who understands the *problem* deliver a real,
tested, zero-running-cost product without a dev team. That is the part I find most
interesting, and the reason it is public.

## Quick start

Requires [LM Studio](https://lmstudio.ai/) running `qwen3.6-27b` with the **Local
Server** started on `:1234` (Developer tab). Nothing else is needed: the tool is
fully self-contained.

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt -r requirements-dev.txt

# add your details
cp profile.example.json profile.json   # then edit profile.json (it is gitignored)
```

`python-docx` renders the documents; the interview PDF also needs a local Chrome or
Chromium. Point at a different endpoint or model with the `CVDRAFTER_LLM_URL` /
`CVDRAFTER_LLM_MODEL` env vars (for example Ollama on `:11434`).

## Use

```bash
# copy a job advert to the clipboard, then:
pbpaste > jd.txt

# CV: screening .docx + designed .pdf
./.venv/bin/python draft_cv.py --jd-file jd.txt --title "The Role Title"

# cover letter: .docx + .txt
./.venv/bin/python draft_cover.py --jd-file jd.txt --title "The Role Title" --company "The Company"
```

`--jd-file -` reads the JD from stdin instead. Outputs land in `outputs/`
(gitignored). Each run prints coverage, any keyword gaps and the honesty report. Read
the `review` lines and check those claims before you send.

Input is paste or pipe only. Fetching a JD straight from a job-board link needs the
board scraping that is deliberately deferred to a later phase (see Roadmap).

## Under the hood

Everything the tool needs lives in this repo; it stands alone:

- `draft_cv.py` / `draft_cover.py`: the drafters (local-model pipeline + CLI).
- `cv_render.py`: the ATS-safe screening `.docx`, `keyword_coverage`, `cv_fulltext`.
- `pdf_render.py`: the designed interview `.pdf` (headless Chrome).
- `cv_profile.py`: loads and locates your `profile.json`.
- `honesty.py`: the verification guard.
- `local_llm.py` / `settings.py`: the local-model client and endpoint config.

**The local-model trick.** `qwen3.6-27b` in LM Studio is a reasoning model that
ignores the usual API thinking switches (`/no_think`, `enable_thinking:false`,
`response_format`) and burns its whole token budget thinking, returning empty
`content`. `local_llm.py` beats this by calling the raw `/v1/completions` endpoint
with a hand-built qwen ChatML prompt and a **pre-closed `<think></think>` block**,
turning 40 to 70 seconds of nothing into a roughly 9 second clean answer. For longer
generative tasks it also **prefills the answer with `{`** so the model must continue
a JSON object rather than drift into prose.

## Develop

```bash
./.venv/bin/python -m pytest        # unit tests; live tests skip with no endpoint
./.venv/bin/ruff check .
./.venv/bin/python evals/run_eval.py   # eval vs the golden set (needs the endpoint)
```

## Roadmap

Phase 1 (this repo): **drafting**, complete. Later phases, in priority order:
**tracking** (a local dashboard of the roles you are pursuing), then **board
scraping** (which also unlocks fetching a JD straight from a link).

## License

[MIT](LICENSE). Your own CV data lives in `profile.json`, which is gitignored and
never leaves your machine; copy `profile.example.json` to `profile.json` and fill in
your details to get started.
