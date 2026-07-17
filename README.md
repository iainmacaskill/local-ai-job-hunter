# Local Job Hunter

**A free job-hunt assistant that lives on your own computer. It finds roles, tracks
your applications, and uses AI to draft tailored, honest CVs, with no subscription
and without your career history ever leaving your machine.**

`free to run · private by design · refuses to invent experience · built by directing an AI agent`

## What it does, in plain English

Applying for jobs properly means rewriting your CV for every role so it speaks the
advert's language. Most people either send the same CV everywhere, or paste their
career history into an online AI tool and hope for the best. This tool takes a
different path:

1. **It finds roles.** It searches Reed and Adzuna (using their free, official
   interfaces, no scraping) and files new, relevant roles on a simple board. Roles
   you have already seen, and roles needing security clearance, are skipped.
2. **You decide.** Each role arrives as *Found*. Read the advert and either *Pass*
   or set it to *Draft CV*.
3. **It drafts.** The AI on your own laptop rewrites your real experience to mirror
   the advert: a plain CV for the automated screening systems, a designed PDF for
   human readers, and a cover letter if you want one. About 50 seconds, about £0.
4. **It keeps the AI honest.** Every draft is checked against your real profile
   before it is saved. Invented employers, stretched dates or made-up numbers are
   blocked or flagged for your review.
5. **You apply.** Mark the role *Applied*. From there the conversation with the
   recruiter is yours; the tool tracks the search, not the relationship.

## The AI runs on your computer, not in the cloud

This is the part that surprises people: there is no ChatGPT subscription, no API
bill and no company server involved. The drafting is done by a language model
running **on your own laptop**, using a free desktop app called
[LM Studio](https://lmstudio.ai/).

- **One-time setup:** install LM Studio, download a model through its built-in
  browser (this tool uses `qwen3.6-27b`, a large download of roughly 16 GB), and
  click to start its local server. That is the whole AI installation.
- **After that:** drafting costs nothing per use, works without sharing your data,
  and your CV, profile and application history stay on your machine. The only thing
  that ever goes out is the job-board search itself.
- **The honest trade-off:** a laptop-sized model is not as strong as the big cloud
  ones. Benchmarked over five real adverts against a frontier cloud model:

| | this tool (local) | frontier cloud model |
|---|---:|---:|
| Invented experience | **0 across all drafts** | 0 |
| Advert keyword coverage | 85% average | 96% |
| Cost per draft | **£0** | paid API |

So treat it as a fast, free, honest **first draft that you review and polish**, not
a replacement for your own judgement on a role that really matters.

You will need a reasonably powerful computer to run the model (it was built and
tested on an Apple silicon MacBook); everything else about the tool is lightweight.

## Why honesty is the whole point

Recruiters are drowning in AI-written CVs and are getting good at spotting the
tells: fabricated metrics, inflated titles, stretched dates. An invented claim wins
you a phone call you then fail in the room.

So this tool is built the opposite way round. The AI is only allowed to write the
*wording*: the summary, the phrasing of your bullet points. The *facts* of your
career (which employers, which job titles, which dates, in which order) are copied
straight from your profile and the AI cannot touch them. A verification step then
checks every draft and reports anything questionable:

```
$ python draft_cv.py --jd-file jd.txt --title "AI Delivery Manager"
saved:    outputs/Alex Rivera - Screening - AI Delivery Manager.docx
          outputs/Alex Rivera - Interview - AI Delivery Manager.pdf
coverage: 91%  (10/11 keywords)
gaps:     RPA
honesty:  review: 1 warning(s)
  review  unverified figure '3 million' in summary
```

Two things happened in that real run: the tool admitted a genuine gap (no RPA
experience, rather than pretending) and it caught the AI inflating a "2 million
records" fact into "3 million" before the CV was saved. It also tells you your
keyword coverage against the advert, so you know where you genuinely stand before
you apply.

## Why I built it, and what it shows

I am an agile delivery manager, not a software engineer. I built this tool by
directing an AI coding agent (Claude Code), one small user story at a time: writing
the backlog, making the product decisions, insisting on tests and honest metrics,
and reviewing every increment, exactly as I would run a delivery team.

The result is not a throwaway script. It ships with a 60-plus automated test suite,
a linter, a documented architecture, a reproducible benchmark, and a commit history
you can read like a delivery log. Total running cost: zero.

I think that is the interesting part. Someone who deeply understands a problem and
knows how to direct work can now ship real, tested software by managing AI well.
If that capability would be useful to your team, I am at
[linkedin.com/in/iainmacaskill](https://www.linkedin.com/in/iainmacaskill).

## Run it yourself

The short version for the technically comfortable; each step is a one-time setup.

**1. The AI.** Install [LM Studio](https://lmstudio.ai/), download `qwen3.6-27b`,
and start the local server on port `1234` (Developer tab).

**2. The tool.**

```bash
git clone https://github.com/iainmacaskill/local-job-hunter
cd local-job-hunter
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp profile.example.json profile.json   # then fill in YOUR career facts (gitignored)
```

The interview PDF also needs Chrome or Chromium installed. A different endpoint or
model can be set with the `CVDRAFTER_LLM_URL` / `CVDRAFTER_LLM_MODEL` variables
(for example Ollama on `:11434`).

**3. The job search (optional).** Get free keys from
[reed.co.uk/developers](https://www.reed.co.uk/developers) and/or
[developer.adzuna.com](https://developer.adzuna.com), and put them in a gitignored
`.env` file in the repo root:

```
REED_API_KEY=your-key
ADZUNA_APP_ID=your-id
ADZUNA_APP_KEY=your-key
```

**4. Use it.** Start the tracker and work from the board: find roles, triage them,
draft from a row, download the documents, mark them applied.

```bash
./.venv/bin/streamlit run app.py
```

Or draft one-off from the command line:

```bash
./.venv/bin/python draft_cv.py --jd-file jd.txt --title "The Role Title"
./.venv/bin/python draft_cover.py --jd-file jd.txt --title "The Role Title" --company "The Company"
./.venv/bin/python hunt.py --source adzuna --location London --keywords "ai delivery manager"
```

Outputs land in `outputs/` (gitignored). Every draft prints its coverage, keyword
gaps and honesty report: read the `review` lines before you send anything.

## For developers

Everything lives in this repo; it stands alone:

- `draft_cv.py` / `draft_cover.py`: the drafters (local-model pipeline + CLI).
- `cv_render.py` / `pdf_render.py`: the screening `.docx` (single column, no tables,
  so automated parsers read it cleanly) and the designed interview `.pdf`.
- `honesty.py`: the verification guard.
- `local_llm.py` / `settings.py` / `cv_profile.py`: model client, config, profile.
- `app.py` / `tracker_db.py` / `tracker_draft.py`: the Streamlit tracker, its local
  SQLite store, and drafting from a tracked role.
- `reed.py` / `adzuna.py` / `hunt.py`: the free job-board clients and the sweep
  (dedupe, clearance skip, title-relevance filter).

**The local-model trick.** `qwen3.6-27b` in LM Studio is a reasoning model that
ignores the usual API thinking switches and burns its whole token budget thinking,
returning empty `content`. `local_llm.py` beats this by calling the raw
`/v1/completions` endpoint with a hand-built qwen ChatML prompt and a pre-closed
`<think></think>` block, turning 40 to 70 seconds of nothing into a roughly 9 second
clean answer. For longer generative tasks it also prefills the answer with `{` so
the model must continue a JSON object rather than drift into prose.

```bash
./.venv/bin/python -m pytest          # tests; live ones skip with no endpoint
./.venv/bin/ruff check .
./.venv/bin/python evals/run_eval.py  # benchmark vs the golden set (needs the endpoint)
```

The full benchmark write-up is in [`evals/RESULTS.md`](evals/RESULTS.md).

## Roadmap

- **Drafting** (screening CV, interview PDF, cover letter): done.
- **Tracking** (a local board: Found, Pass, Draft CV, Applied): done.
- **Active hunt** (find roles from the free Reed and Adzuna APIs, deduplicated and
  relevance-filtered): done.

Next: sharper sweep relevance (fuzzy de-duplication of agency re-posts), delete and
archive on the board, and saved searches.

## License

[MIT](LICENSE). Your own CV data lives in `profile.json`, which is gitignored and
never leaves your machine; copy `profile.example.json` to `profile.json` and fill in
your details to get started.
