"""Eval the local drafter across a set of JDs vs the Claude golden set.

Runs draft_screening_cv on each evals/jds/*.txt, records the local coverage, the
honesty result and the JSON-reliability counters, and prints a table against the
Claude reference numbers in golden.json.

Read the comparison honestly: coverage is each drafter's own self-extracted
keyword set, so the local-vs-Claude percentages measure self-consistency, not an
identical-keyword contest. The honesty columns (errors / warnings) ARE directly
comparable and are the more important signal.

Model A/B (the 8B-tier experiment): run once per model and save labelled results,
then compare with compare_models.py against the frozen gate in 8B-GATE.md. Each
run also saves its CV drafts to outputs/eval-<model>/ (gitignored: real profile
data) so the documents themselves can be compared side by side, not just the
numbers.

  ../.venv/bin/python evals/run_eval.py --out evals/results/qwen27b.json
  ../.venv/bin/python evals/run_eval.py --model qwen/qwen3.5-8b --out evals/results/qwen8b.json
  ../.venv/bin/python evals/compare_models.py evals/results/qwen27b.json evals/results/qwen8b.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import draft_cv  # noqa: E402
import settings  # noqa: E402
from local_llm import LocalLLM  # noqa: E402

HERE = Path(__file__).resolve().parent
JD_DIR = HERE / "jds"


def _slug(model: str) -> str:
    return model.split("/")[-1].replace(".", "").replace(":", "-")


def run(model: str) -> tuple[list[dict], dict, Path]:
    golden = json.loads((HERE / "golden.json").read_text())
    llm = LocalLLM(base_url=settings.LLM_BASE_URL, model=model)
    if not llm.is_up():
        raise SystemExit("local endpoint not running - start the LM Studio server on :1234")

    # Each model's drafts land in their own folder so runs can be compared side
    # by side by a human, not just by the numbers. Lives under outputs/, which
    # is gitignored: these are real-profile CVs and never belong in the repo.
    cv_dir = HERE.parent / "outputs" / f"eval-{_slug(model)}"
    cv_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for jd_file in sorted(JD_DIR.glob("*.txt")):
        g = golden.get(jd_file.stem, {})
        t0 = time.time()
        res = draft_cv.draft_screening_cv(
            jd_file.read_text(encoding="utf-8"),
            role_title=g.get("title"),
            llm=llm,
            out_dir=cv_dir,
            render_pdf=False,
        )
        rep = res["honesty"]
        rows.append({
            "role": jd_file.stem,
            "local": res["coverage"]["pct"],
            "claude": g.get("claude"),
            "errors": len(rep.errors),
            "warnings": len(rep.warnings),
            "secs": round(time.time() - t0),
            "note": g.get("note", ""),
        })
    return rows, dict(llm.stats), cv_dir


def print_table(rows: list[dict], stats: dict, model: str) -> None:
    print(f"\nmodel: {model}")
    print(f"{'role':<14}{'local':>7}{'claude':>8}{'errors':>8}{'warn':>6}{'secs':>6}   note")
    print("-" * 78)
    for r in rows:
        print(
            f"{r['role']:<14}{str(r['local']) + '%':>7}{str(r['claude']) + '%':>8}"
            f"{r['errors']:>8}{r['warnings']:>6}{r['secs']:>6}   {r['note']}"
        )
    print("-" * 78)
    avg_local = round(sum(r["local"] for r in rows) / len(rows))
    claude_vals = [r["claude"] for r in rows if r["claude"] is not None]
    avg_claude = round(sum(claude_vals) / len(claude_vals)) if claude_vals else 0
    total_err = sum(r["errors"] for r in rows)
    total_warn = sum(r["warnings"] for r in rows)
    print(
        f"{'AVERAGE':<14}{str(avg_local) + '%':>7}{str(avg_claude) + '%':>8}"
        f"{total_err:>8}{total_warn:>6}"
    )
    print(f"\nhard fabrications caught: {total_err}   figure/style warnings: {total_warn}")
    print(f"json reliability: {stats['json_calls']} calls, {stats['json_retries']} retries, "
          f"{stats['json_failures']} unrecovered failures")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the drafting eval against a local model.")
    ap.add_argument("--model", default=settings.LLM_MODEL,
                    help="model name as LM Studio knows it (default: settings.LLM_MODEL)")
    ap.add_argument("--out", default=None,
                    help="save labelled results as JSON (for compare_models.py)")
    args = ap.parse_args(argv)

    rows, stats, cv_dir = run(args.model)
    print_table(rows, stats, args.model)
    print(f"cv drafts: {cv_dir}")
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "model": args.model,
            "date": dt.date.today().isoformat(),
            "cv_dir": str(cv_dir),
            "rows": rows,
            "stats": stats,
        }, indent=2), encoding="utf-8")
        print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
