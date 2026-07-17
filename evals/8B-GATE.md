# The 8B gate

Frozen 17 July 2026, before any candidate model was tested. The 8B-tier
experiment asks whether a smaller model (a qwen-family ~8B, runnable on a 16 GB
machine) can be offered as a supported budget tier. The honesty architecture was
built precisely so a weaker model cannot do damage; this gate is the test of
that claim, and it is decided by measurement, not argument.

The 27B model stays the recommended tier regardless of the outcome. The
candidate is judged against a same-day 27B baseline on the same five golden job
adverts (`compare_models.py`) and the same ten real board roles
(`triage_compare.py`).

## Criteria

| Metric | Bar |
|---|---|
| Hard fabrications (invented employers, titles or dates) | 0, non-negotiable |
| Figure/style warnings | At most 2x the baseline count |
| Keyword coverage (five-advert average) | Within 10 points of the baseline |
| JSON reliability | No unrecovered failures across the eval (retries reported) |
| Triage sanity | At least 2 of 3 agreement with the baseline in both the top-3 and bottom-3 buckets |
| Speed | Reported honestly; not a pass/fail criterion |

## Outcomes

1. **Passes everything:** the candidate is documented as the 16 GB tier in the
   README hardware guide.
2. **Passes triage but not drafting** (the expected outcome): a mixed mode is
   added, an optional `CVDRAFTER_LLM_MODEL_TRIAGE` setting, so budget machines
   still triage quickly and drafting stays on the best model available.
3. **Fails the honesty bar:** the result is published in the README as-is and
   the tool stays 27B-only. The brand survives an honest failure; it would not
   survive a fudged pass.

The comparison results (numbers only) are committed under `evals/results/`;
triage outputs are gitignored because their reasons cite real profile facts.
