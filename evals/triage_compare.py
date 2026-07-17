"""Compare triage scoring between models on the same sample of real board roles.

Scores a fixed sample (spread across the current ranking: top, middle, bottom)
under the given model WITHOUT writing anything to the tracker, and saves a
labelled JSON. Run once per model, reusing the first run's role ids so both
models score the same roles, then compare:

  ../.venv/bin/python evals/triage_compare.py --out evals/results/triage-27b.json
  ../.venv/bin/python evals/triage_compare.py --model qwen/qwen3.5-8b \
      --ids-from evals/results/triage-27b.json --out evals/results/triage-8b.json
  ../.venv/bin/python evals/triage_compare.py --compare \
      evals/results/triage-27b.json evals/results/triage-8b.json

Outputs are gitignored: the reasons cite real profile facts.

Gate check (frozen in 8B-GATE.md): the candidate must put the same roles in the
top-3 and bottom-3 buckets as the baseline (at least 2 of 3 in each).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import settings  # noqa: E402
import tracker_db  # noqa: E402
import triage  # noqa: E402
from cv_profile import load_profile  # noqa: E402
from local_llm import LocalLLM  # noqa: E402

BUCKET_MIN_OVERLAP = 2  # of 3, in each of the top and bottom buckets


def _sample_ids(conn, n: int) -> list[int]:
    """A deterministic spread across the current ranking: top 4, middle 3, bottom 3."""
    scored = [r for r in tracker_db.list_roles(conn) if r.get("fit_score") is not None]
    scored.sort(key=lambda r: r["fit_score"], reverse=True)
    if len(scored) <= n:
        return [r["id"] for r in scored]
    mid = len(scored) // 2
    picks = scored[:4] + scored[mid - 1 : mid + 2] + scored[-3:]
    return [r["id"] for r in picks[:n]]


def score(model: str, ids: list[int] | None, out: Path, n: int) -> int:
    conn = tracker_db.connect()
    tracker_db.init_db(conn)
    profile = load_profile()
    llm = LocalLLM(base_url=settings.LLM_BASE_URL, model=model)
    if not llm.is_up():
        raise SystemExit("local endpoint not running - start the LM Studio server on :1234")

    role_ids = ids or _sample_ids(conn, n)
    results = []
    for i, rid in enumerate(role_ids, start=1):
        role = tracker_db.get_role(conn, rid)
        if not role:
            continue
        r = triage.score_role(role, profile, llm)  # no DB write
        results.append({"id": rid, "title": role["title"], "company": role.get("company"),
                        "score": r["score"], "reason": r["reason"]})
        print(f"  scored {i}/{len(role_ids)}", end="\r")
    print()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "model": model, "date": dt.date.today().isoformat(),
        "ids": role_ids, "results": results, "stats": dict(llm.stats),
    }, indent=2), encoding="utf-8")
    for r in sorted(results, key=lambda x: x["score"], reverse=True):
        print(f"  {r['score']:3}  {r['title'][:56]}, {r['company']}")
    print(f"saved: {out}")
    return 0


def compare(base_path: str, cand_path: str) -> int:
    base = json.loads(Path(base_path).read_text())
    cand = json.loads(Path(cand_path).read_text())
    b = {r["id"]: r for r in base["results"]}
    c = {r["id"]: r for r in cand["results"]}
    common = [rid for rid in base["ids"] if rid in b and rid in c]
    if not common:
        print("no common roles between the two runs")
        return 2

    print(f"baseline:  {base['model']}\ncandidate: {cand['model']}\n")
    print(f"{'role':<48}{'base':>6}{'cand':>6}{'diff':>7}")
    print("-" * 68)
    diffs = []
    for rid in sorted(common, key=lambda i: b[i]["score"], reverse=True):
        d = c[rid]["score"] - b[rid]["score"]
        diffs.append(abs(d))
        print(f"{b[rid]['title'][:46]:<48}{b[rid]['score']:>6}{c[rid]['score']:>6}{d:>+7}")
    print("-" * 68)
    mean_abs = round(sum(diffs) / len(diffs), 1)

    def bucket(scores, ids, reverse):
        return set(sorted(ids, key=lambda i: scores[i]["score"], reverse=reverse)[:3])

    top_overlap = len(bucket(b, common, True) & bucket(c, common, True))
    bot_overlap = len(bucket(b, common, False) & bucket(c, common, False))
    print(f"mean absolute difference: {mean_abs} points")
    print(f"top-3 agreement: {top_overlap}/3   bottom-3 agreement: {bot_overlap}/3")
    ok = top_overlap >= BUCKET_MIN_OVERLAP and bot_overlap >= BUCKET_MIN_OVERLAP
    print(f"\nGATE (triage): {'PASSED' if ok else 'FAILED'} "
          f"(needs at least {BUCKET_MIN_OVERLAP}/3 in each bucket)")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Triage scoring comparison between models.")
    ap.add_argument("--model", default=settings.LLM_MODEL)
    ap.add_argument("--out", default=None, help="where to save the labelled results")
    ap.add_argument("--sample", type=int, default=10)
    ap.add_argument("--ids-from", default=None,
                    help="reuse the role ids from a previous run's JSON")
    ap.add_argument("--compare", nargs=2, metavar=("BASE", "CAND"),
                    help="compare two saved runs instead of scoring")
    args = ap.parse_args(argv)

    if args.compare:
        return compare(*args.compare)
    ids = None
    if args.ids_from:
        ids = json.loads(Path(args.ids_from).read_text())["ids"]
    slug = args.model.split("/")[-1].replace(".", "").replace(":", "-")
    out = Path(args.out) if args.out else Path(__file__).parent / f"results/triage-{slug}.json"
    return score(args.model, ids, out, args.sample)


if __name__ == "__main__":
    raise SystemExit(main())
