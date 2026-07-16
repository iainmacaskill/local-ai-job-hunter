"""S6: eval the local drafter across a set of JDs vs the Claude golden set.

Runs draft_screening_cv on each evals/jds/*.txt, records the local coverage and
the honesty result, and prints a table against the Claude reference numbers in
golden.json.

Read the comparison honestly: coverage is each drafter's own self-extracted
keyword set, so the local-vs-Claude percentages measure self-consistency, not an
identical-keyword contest. The honesty columns (errors / warnings) ARE directly
comparable and are the more important signal.

Run:  ../.venv/bin/python evals/run_eval.py   (needs the local endpoint up)
"""

from __future__ import annotations

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


def run() -> list[dict]:
    golden = json.loads((HERE / "golden.json").read_text())
    llm = LocalLLM(base_url=settings.LLM_BASE_URL, model=settings.LLM_MODEL)
    if not llm.is_up():
        raise SystemExit("local endpoint not running - start the LM Studio server on :1234")

    rows: list[dict] = []
    for jd_file in sorted(JD_DIR.glob("*.txt")):
        g = golden.get(jd_file.stem, {})
        t0 = time.time()
        res = draft_cv.draft_screening_cv(
            jd_file.read_text(encoding="utf-8"),
            role_title=g.get("title"),
            llm=llm,
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
    return rows


def print_table(rows: list[dict]) -> None:
    print(f"\n{'role':<14}{'local':>7}{'claude':>8}{'errors':>8}{'warn':>6}{'secs':>6}   note")
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


if __name__ == "__main__":
    print_table(run())
