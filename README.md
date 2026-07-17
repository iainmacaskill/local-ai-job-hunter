# cv-drafter-local

**A local, free job-hunt tool that tracks the roles you are chasing and drafts
honest, tailored CVs for them, refusing to invent experience you do not have.**

You paste a job advert (or let the tool **find** roles for you); it drafts a
keyword-tuned **screening CV** (`.docx`), a designed **interview CV** (`.pdf`) and a
matching **cover letter**, in your house style, using only facts from your own
profile, and it tells you where you genuinely fall short of the advert instead of
papering over it. A local **tracker** keeps the roles you are pursuing in one place,
and an **active hunt** pulls new ones in from free job-board APIs, so the whole find,
draft and track loop runs on your own machine.

Three things make it different from the flood of AI CV tools:

- **Local:** your CV, your profile and your tracker live only on your machine, and
  drafting runs against a model on your own laptop (LM Studio / Ollama).
- **Free:** no paid API, no subscription, no per-draft cost. A full CV draft is about
  £0 and 50 seconds, and the active hunt uses free official job-board APIs.
- **Honest by design:** the model may only write prose. Every employer, job title
  and date comes straight from your profile, and a verification guard blocks any
  invented experience before it reaches the page.

`Python · local LLM · MIT-licensed · your CV never leaves your device`

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
honesty:  review: 1 warning(s)
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

## Tracker

The roles you are chasing live in a local dashboard (Streamlit), so drafting is part
of a loop rather than a one-off command:

```bash
./.venv/bin/streamlit run app.py
```

- **Add a role** with its advert, and it is stored locally (a SQLite file that is
  gitignored, like your profile).
- **Move it through the pipeline** (Found, Applied, Interview, Offer and so on) by
  editing the status in the grid, with a metrics row (active, applied, interviewing,
  offers) and a status filter across the top.
- **Draft from the row.** Set a role's status to *Draft CV* or *Draft CV & Cover
  Letter* and it joins a "to draft" queue; one click runs the same local drafters,
  records the coverage and honesty result on the row, and gives you the finished
  files to download.

The tracker, the model and your files all stay on your machine; the only outbound
call is the job search below, and only when you use it.

## Active hunt

Rather than paste every advert by hand, let the tool **find** roles and drop the new
ones into the tracker as *Found*. It searches free, official job-board APIs (no
scraping, no agent, no paid service):

- **Reed** ([reed.co.uk/developers](https://www.reed.co.uk/developers)): a free key,
  returns the full job description.
- **Adzuna** ([developer.adzuna.com](https://developer.adzuna.com)): a free app id
  and key, returns a description snippet (paste the full advert before drafting).

Put your key(s) in a gitignored `.env` in the repo root:

```
REED_API_KEY=your-key
ADZUNA_APP_ID=your-id
ADZUNA_APP_KEY=your-key
```

Then search from the **Find roles** panel in the tracker, or the command line:

```bash
./.venv/bin/python hunt.py --source adzuna --location London --distance 20 \
  --keywords "ai delivery manager" --keywords "digital transformation manager"
```

Each new role is de-duplicated against what you already track, skips clearance roles
(DV/SC/NPPV) and off-target titles, and is stored with its JD, ready to draft. A run
reports what it did:

```
added:     12 new role(s)
  + AI Programme Manager, Capco
  + Delivery Manager - Digital Transformation, Government
  + Head of PMO, Context Recruitment
  ...
skipped:   3 already tracked, 21 off-target titles, 1 needing clearance
```

The relevance filter (`hunt.RELEVANT_TITLE_TERMS`) keeps roles whose title mentions a
delivery / AI / data / transformation / programme term (short terms match whole
words, so "AI" does not match "repair"); pass `--all-titles` to keep everything. The
only thing that leaves your machine is the search itself, not your CV or profile.

## Built by directing an AI agent

This is also a small proof of a bigger idea. It was built by an agile delivery
manager, not a professional software engineer, by pair-programming with an AI coding
agent (Claude Code), one small user story at a time. The result is not a throwaway
script: it ships with a 40-plus test suite, a linter, an honesty guard and a
reproducible eval. Modern agentic tooling now lets someone who understands the
*problem* deliver a real, tested, zero-running-cost product without a dev team. That
is the part I find most interesting, and the reason it is public.

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

For a one-off draft you can skip the tracker and go straight to the command line:

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

You do not have to paste every advert by hand: the [Active hunt](#active-hunt) finds
roles from free job-board APIs and logs them to the tracker with their JD.

## Under the hood

Everything the tool needs lives in this repo; it stands alone:

- `draft_cv.py` / `draft_cover.py`: the drafters (local-model pipeline + CLI).
- `cv_render.py`: the ATS-safe screening `.docx`, `keyword_coverage`, `cv_fulltext`.
- `pdf_render.py`: the designed interview `.pdf` (headless Chrome).
- `cv_profile.py`: loads and locates your `profile.json`.
- `honesty.py`: the verification guard.
- `local_llm.py` / `settings.py`: the local-model client and endpoint config.
- `app.py`: the local **tracker** dashboard (Streamlit).
- `tracker_db.py`: the local SQLite store of roles and the pipeline metrics.
- `tracker_draft.py`: drafts the CV/cover letter for a tracked role and records the result.
- `reed.py` / `adzuna.py`: free job-board API clients (the active-hunt sources).
- `hunt.py`: the sweep, and its CLI: search a source, dedupe, filter, log new roles.

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

- **Drafting** (screening CV, interview PDF, cover letter): done.
- **Tracking** (a local dashboard of the roles you are pursuing, drafting straight
  from a row): done.
- **Active hunt** (find roles from the free Reed and Adzuna APIs and log them to the
  tracker, with de-duplication, a clearance skip and a title-relevance filter): done.

Next: sharper sweep relevance (tighter defaults, fuzzy de-duplication of agency
re-posts), delete and archive in the tracker UI, and saved searches.

## License

[MIT](LICENSE). Your own CV data lives in `profile.json`, which is gitignored and
never leaves your machine; copy `profile.example.json` to `profile.json` and fill in
your details to get started.
