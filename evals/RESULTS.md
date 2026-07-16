# Eval — local drafter vs Claude golden set

Run: 2026-07-17 · model `qwen/qwen3.6-27b` (LM Studio) · `python evals/run_eval.py`

Five real job adverts from the week's hunt, drafted by the local pipeline and
compared to the CVs Claude drafted for the same roles.

| role | local | Claude | hard errors | warnings | secs | note |
|---|---:|---:|---:|---:|---:|---|
| deloitte | 100% | 100% | 0 | 0 | 55 | Claude promoted the CLS/IBM cyber story hard |
| head-biztech | 91% | 94% | 0 | 1 | 58 | RPA is a genuine gap |
| hsbc | 63% | 94% | 0 | 1 | 53 | UX is a genuine gap |
| oliver-james | 94% | 93% | 0 | 1 | 50 | no legal-sector experience |
| sr2 | 77% | 100% | 0 | 0 | 54 | pharma is a nice-to-have gap |
| **average** | **85%** | **96%** | **0** | **3** | ~54 | |

## Read

- **Honesty: clean pass.** Zero hard fabrications across all five drafts — the
  local model never invented, renamed or reordered an employer, title or date.
  That is the architecture working: structure comes from `profile.json`, the model
  only writes prose. The three warnings are minor figure/style review flags, not
  fabrications.
- **Coverage: ~85% average, but variable (63%–100%).** On two of five the local
  drafter matched or beat Claude (Deloitte, Oliver James); on two it trailed
  (HSBC, SR2). Coverage is self-scored against each drafter's own extracted
  keywords, so treat local-vs-Claude as indicative, not identical-keyword.
- **Variance is the main quality caveat.** At temperature 0 the *writing* is
  stable, but the keyword extraction (the coverage denominator) shifts run to run,
  so some drafts land noticeably weaker (HSBC here at 63%). Expect to polish the
  lower ones more.
- **Cost & speed:** ~50–58s per full CV draft, £0 (fully local).

## Verdict

Fit for purpose as a **free first-draft tool you review**: it is reliably honest,
fast, and gets you ~85% of the way on average, with the human closing the gap and
handling the occasional weaker draft. Not a replacement for a final human/cloud
pass on a role that matters.
