# cv-drafter-local

Offline CV and cover-letter drafting for the job hunt, powered by a **local model**
(LM Studio / qwen3.6-27b) instead of a cloud API, so drafting costs **zero API
tokens**.

You find a role by hand and paste its job description; the tool drafts a
keyword-optimised **screening CV** (`.docx`), a designed **interview CV** (`.pdf`)
and a **cover letter** (`.docx` + `.txt`), honestly (facts only from your profile)
and in your house style, for you to review before sending.

**Status: MVP complete** (stories S1 to S6). See [`evals/RESULTS.md`](evals/RESULTS.md)
for how it measures up against cloud-drafted CVs.

## What you get

Every CV run produces both formats from one command:

- **Screening CV** — ATS-plain `.docx`, for uploading to portals.
- **Interview CV** — designed `.pdf`, for humans and remote viewing (needs Chrome;
  it degrades gracefully to "skipped" if absent).
- **Cover letter** — `.docx` (to attach) and `.txt` (to paste into an email).
- A **coverage score** and an **honesty report** printed on every run.

## Setup

Requires LM Studio running qwen3.6-27b with the **Local Server** started on `:1234`
(Developer tab), and the [`jobtracker`](../jobtracker) repo checked out alongside
this one (its engine is reused, see below).

```
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

`python-docx` (in `requirements.txt`) renders the documents; the interview PDF also
needs a local Chrome or Chromium. Point at a different endpoint or model with the
`CVDRAFTER_LLM_URL` / `CVDRAFTER_LLM_MODEL` env vars (for example Ollama on `:11434`).

## Use

```
# copy a job advert to the clipboard by hand, then:
pbpaste > /tmp/jd.txt

# CV: screening .docx + designed .pdf
./.venv/bin/python draft_cv.py --jd-file /tmp/jd.txt --title "The Role Title"

# cover letter: .docx + .txt
./.venv/bin/python draft_cover.py --jd-file /tmp/jd.txt --title "The Role Title" --company "The Company"
```

`--jd-file -` reads the JD from stdin instead. Outputs land in `outputs/`
(gitignored). Each run prints coverage, any keyword gaps, and the honesty report:
read the `review` lines and check those claims before you send.

**Input is paste or pipe only.** Fetching a JD straight from a job-board link needs
the board scraping that is deliberately deferred to a later phase (see Roadmap).

## How it stays honest

The model only ever writes prose (summary, skills, bullets, letter paragraphs).
Every employer, role title and date comes straight from `profile.json`, and
one-line roles are passed through un-inflated rather than padded. Then `honesty.py`
verifies each draft against the profile:

- **ERROR (blocks):** an employer, role title or date that is not in `profile.json`
  (invented, renamed, reordered or stretched experience).
- **WARNING (review):** a figure that appears nowhere in the profile (a likely
  fabricated metric), or an em dash (house style).

It cannot judge qualitative claims semantically, so you stay the final gate. In the
eval it caught a fabricated "over eight years" claim and produced **zero hard
fabrications across five drafts**.

## Relationship to `jobtracker`

Deliberately **separate** from the `jobtracker` Streamlit app, but it **reuses
jobtracker's engine by import** rather than duplicating it. Rendering
(`screening_cv`, `interview_cv`, `cover_letter`), scoring (`keyword_coverage`) and
your `profile.json` all stay in jobtracker as the single source of truth, so the
honesty-critical code lives in exactly one place. `settings.py` puts the jobtracker
checkout on the import path (override with `JOBTRACKER_PATH`; it defaults to the
sibling `../jobtracker`) and is named `settings` (not `config`) so it never shadows
jobtracker's own `config` module.

## The local-model trick (why it works)

qwen3.6-27b in LM Studio is a reasoning model that ignores the API thinking
switches (`/no_think`, `enable_thinking:false`, `response_format`) and burns its
whole token budget thinking, returning empty `content`. `local_llm.py` beats this
by calling the raw `/v1/completions` endpoint with a hand-built qwen ChatML prompt
and a **pre-closed `<think></think>` block**, turning 40 to 70 seconds of nothing
into a ~9 second clean answer. For longer generative tasks it also **prefills the
answer with `{`** so the model must continue a JSON object rather than drift into
prose.

## Develop

```
./.venv/bin/python -m pytest        # unit tests; live tests skip with no endpoint
./.venv/bin/ruff check .
./.venv/bin/python evals/run_eval.py   # eval vs the golden set (needs the endpoint)
```

## Roadmap

Phase 1 (this repo): **drafting**, complete. Later phases, in priority order:
**tracking**, then **board scraping** (which also unlocks fetching a JD straight
from a link).
