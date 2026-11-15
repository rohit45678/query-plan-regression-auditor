#!/usr/bin/env python3
"""Runnable entry point for the Query-Plan Regression Auditor.

Usage:
    python3 main.py                          # audit the bundled sample plans
    python3 main.py --format json            # machine-readable report
    python3 main.py --baseline B.json --candidate C.json
    python3 main.py --demo-sqlite            # also audit real SQLite queries
    python3 main.py --strict                 # exit 1 when a regression is found
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from plan_auditor import PlanAuditor, build_demo_db, audit_sqlite_query  # noqa: E402
from plan_auditor.report import render_markdown, render_text  # noqa: E402


def demo_sqlite() -> None:
    conn = build_demo_db()
    try:
        print("\n--- Live SQLite demo (in-memory database, real EXPLAIN QUERY PLAN) ---")
        cases = [
            ("indexed lookup", "SELECT * FROM orders WHERE user_id = ?", (7,)),
            ("unfiltered scan", "SELECT * FROM orders WHERE status = ?", ("paid",)),
        ]
        for label, sql, params in cases:
            result = audit_sqlite_query(conn, sql, params)
            plan = result["plan"]
            details = "; ".join(n.detail for n in plan.nodes)
            print(f"{label}: score={result['score']} seq_scan={result['has_seq_scan']}")
            print(f"  plan: {details}")
            for finding in result["findings"]:
                print(f"  [{finding.severity}] {finding.rule}: {finding.message}")
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default=str(ROOT / "sample_data" / "baseline.json"))
    parser.add_argument("--candidate", default=str(ROOT / "sample_data" / "candidate.json"))
    parser.add_argument("--format", choices=["markdown", "text", "json"], default="markdown")
    parser.add_argument("--threshold", type=float, default=1.5,
                        help="cost-blowup ratio threshold (default 1.5x)")
    parser.add_argument("--demo-sqlite", action="store_true",
                        help="also run the live in-memory SQLite demo")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 if the verdict is REGRESSION")
    args = parser.parse_args(argv)

    auditor = PlanAuditor(threshold_ratio=args.threshold)
    report = auditor.audit_files(args.baseline, args.candidate)

    if args.format == "json":
        print(json.dumps(report, indent=2))
    elif args.format == "text":
        print(render_text(report))
    else:
        print(render_markdown(report))

    if args.demo_sqlite:
        demo_sqlite()

    return 1 if (args.strict and report["is_regression"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
