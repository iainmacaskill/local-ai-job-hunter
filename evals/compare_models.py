"""Compare two labelled eval runs and check the frozen 8B gate mechanically.

  ../.venv/bin/python evals/compare_models.py evals/results/qwen27b.json evals/results/qwen8b.json

The first file is the baseline (27B), the second the candidate. Gate criteria
live in 8B-GATE.md and are frozen before any candidate run; this script just
applies them so the M4 decision is arithmetic, not argument.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

COVERAGE_MAX_GAP = 10        # candidate avg coverage within N points of baseline
WARNINGS_MAX_RATIO = 2.0     # candidate warnings at most Nx baseline (min 2 allowed)


def _avg(rows, key):
    return round(sum(r[key] for r in rows) / len(rows), 1)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: compare_models.py BASELINE.json CANDIDATE.json")
        return 2
    base = json.loads(Path(argv[0]).read_text())
    cand = json.loads(Path(argv[1]).read_text())

    print(f"baseline:  {base['model']}  ({base['date']})")
    print(f"candidate: {cand['model']}  ({cand['date']})\n")
    print(f"{'role':<14}{'base cov':>9}{'cand cov':>9}{'base w':>7}{'cand w':>7}"
          f"{'base s':>7}{'cand s':>7}")
    print("-" * 60)
    cand_by_role = {r["role"]: r for r in cand["rows"]}
    for b in base["rows"]:
        c = cand_by_role.get(b["role"], {})
        print(f"{b['role']:<14}{b['local']:>8}%{c.get('local', '-'):>8}%"
              f"{b['warnings']:>7}{c.get('warnings', '-'):>7}"
              f"{b['secs']:>7}{c.get('secs', '-'):>7}")
    print("-" * 60)

    b_cov, c_cov = _avg(base["rows"], "local"), _avg(cand["rows"], "local")
    c_err = sum(r["errors"] for r in cand["rows"])
    b_warn = sum(r["warnings"] for r in base["rows"])
    c_warn = sum(r["warnings"] for r in cand["rows"])
    b_secs, c_secs = _avg(base["rows"], "secs"), _avg(cand["rows"], "secs")
    print(f"{'AVERAGE':<14}{b_cov:>8}%{c_cov:>8}%{b_warn:>7}{c_warn:>7}{b_secs:>7}{c_secs:>7}")

    checks = [
        ("hard fabrications: 0 (non-negotiable)", c_err == 0,
         f"candidate errors = {c_err}"),
        (f"coverage within {COVERAGE_MAX_GAP} points of baseline",
         c_cov >= b_cov - COVERAGE_MAX_GAP, f"{c_cov}% vs {b_cov}%"),
        (f"warnings at most {WARNINGS_MAX_RATIO}x baseline",
         c_warn <= max(2, b_warn * WARNINGS_MAX_RATIO), f"{c_warn} vs {b_warn}"),
        ("json: no unrecovered failures",
         cand["stats"]["json_failures"] == 0,
         f"{cand['stats']['json_failures']} failures, "
         f"{cand['stats']['json_retries']} retries"),
    ]
    print("\nGATE (frozen in 8B-GATE.md):")
    passed = True
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}  ({detail})")
        passed = passed and ok
    speedup = round(b_secs / c_secs, 1) if c_secs else 0
    print(f"\nspeed: {speedup}x the baseline draft time (informational)")
    print(f"\nVERDICT: {'GATE PASSED' if passed else 'GATE FAILED'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
