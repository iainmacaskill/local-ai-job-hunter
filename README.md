# cv-drafter-local

Offline CV and cover-letter drafting for the job hunt, powered by a **local model**
(LM Studio / qwen3.6-27b) instead of a cloud API — so drafting costs **zero API
tokens**.

Given a job description (pasted, or best-effort fetched from a link the user found
by hand), it drafts a keyword-optimised **screening CV**, a designed **interview
PDF**, and a **cover letter** — honestly (facts only from the profile) and in the
user's house style — for the user to review before sending.

## Relationship to `jobtracker`

Deliberately **separate** from the [`jobtracker`](../jobtracker) Streamlit app, but
it **reuses jobtracker's engine by import** rather than duplicating it. Rendering
(`screening_cv`, `interview_cv`, `cover_letter`), scoring (`keyword_coverage`) and
the user's `profile.json` all stay in jobtracker as the single source of truth — so
honesty-critical code lives in exactly one place. `settings.py` puts the jobtracker
checkout on the import path (override with `JOBTRACKER_PATH`; defaults to the
sibling `../jobtracker`).

## The local-model trick (why it works)

qwen3.6-27b in LM Studio is a reasoning model that ignores the API thinking
switches (`/no_think`, `enable_thinking:false`, `response_format`) and burns its
whole token budget thinking, returning empty `content`. `local_llm.py` beats this
by calling the raw `/v1/completions` endpoint with a hand-built qwen ChatML prompt
and a **pre-closed `<think></think>` block** — 40-70s of nothing becomes a ~9s
clean, parseable JSON answer.

## MVP scope & status

Phase 1 (this repo): **drafting** — CV + cover letter from a pasted/fetched JD.
Later phases (in jobtracker or here, TBD): tracking, then board scraping.

- **S1 · walking skeleton** — done. `local_llm.py` returns clean structured JSON
  from the local endpoint.
- S2 CV drafting · S3 honesty guard · S4 cover letter · S5 interview PDF · S6 eval
  vs the Claude-drafted golden set.

## Run

```
python3 -m venv .venv && ./.venv/bin/pip install -r requirements-dev.txt
./.venv/bin/python -m pytest        # live tests skip if no local endpoint
```

Requires LM Studio running qwen3.6-27b with the **Local Server** started on
`:1234` (Developer tab). Model-agnostic via `CVDRAFTER_LLM_URL` /
`CVDRAFTER_LLM_MODEL` (e.g. point at Ollama on `:11434`).
