# Automated Query-Plan Regression Auditor & Partition-Pruning Optimization Framework

A Python tool that parses query execution plans, compares a candidate plan
against a trusted baseline, and reports performance regressions — sequential /
full scans, total-cost blowups, lost partition pruning, and row-estimate
explosions — with a deterministic 0–100 score and concrete recommendations
for each finding.

It works on two kinds of input, normalised into one plan model:

- **Real SQLite plans** — the output of `EXPLAIN QUERY PLAN` from the
  `sqlite3` standard-library module, explained live against a real
  (in-memory) database.
- **Synthetic plan trees** — JSON plans (flat node lists or nested trees)
  in a Postgres-style vocabulary (`Seq Scan`, `Index Scan`, estimated
  cost / rows, partition counts), which is how you audit plans captured
  from systems you cannot run locally.

## What it does

- **Plan parsing** (`plan_auditor/parser.py`) — SQLite
  `(id, parent, notused, detail)` rows, flat JSON, and nested JSON trees
  all become the same `QueryPlan` / `PlanNode` model
  (`plan_auditor/models.py`), with table, index, cost, row estimates and
  partitioning fields extracted.
- **Regression detection** (`plan_auditor/detector.py`)
  - `SEQ_SCAN` — a sequential / full table (or full index) scan in a plan.
  - `NEW_SEQ_SCAN` — a table that was a `SEARCH` / index scan in the
    baseline but is scanned in the candidate (critical).
  - `COST_BLOWUP` — total cost grew past a configurable ratio
    (default 1.5×) *and* a minimum absolute increase (default 10),
    so trivial plans don't false-positive.
  - `MISSING_PARTITION_PRUNING` — a partitioned table is filtered but
    all partitions are still scanned and none are pruned; only counted
    as a regression if the baseline did prune.
  - `ROW_ESTIMATE_BLOWUP` — per-table row estimates rose ≥10×.
- **Scoring** (`plan_auditor/scoring.py`) — explainable deductions from
  100: −15 per sequential scan (−8 for a full index scan), −20 per
  pruning failure, and a cost tier (−5 / −10 / −20), mapped to a
  letter grade A–F.
- **Reporting** (`plan_auditor/report.py`) — a structured report dict
  (verdict `OK` / `WARNING` / `REGRESSION`, both plan scores, score and
  cost deltas, findings, recommendations) rendered as Markdown, plain
  text, or JSON.
- **Live SQLite auditing** (`plan_auditor/sqlite_audit.py`) — explain
  and audit an actual query against a real database, plus a
  deterministic in-memory demo database (`users` / `orders`, indexed on
  `orders.user_id`) where a filtered lookup is a `SEARCH` and an
  unindexed predicate is a `SCAN`.

## Stack

- **Python 3** (standard library only at runtime: `sqlite3`, `json`,
  `dataclasses`, `argparse`)
- **sqlite3** for real `EXPLAIN QUERY PLAN` output
- **pytest** as the test runner (dev-only dependency)

No network calls, no credentials, no external services.

## How to run

```bash
cd query-plan-regression-auditor

# Audit the bundled sample plans (baseline vs. candidate in sample_data/)
python3 main.py

# Machine-readable report, or plain text
python3 main.py --format json
python3 main.py --format text

# Audit your own pair of JSON plans, with a custom cost threshold
python3 main.py --baseline my_baseline.json --candidate my_candidate.json --threshold 2.0

# Also explain + audit real queries on the in-memory SQLite demo database
python3 main.py --demo-sqlite

# CI-style gate: exit 1 when the verdict is REGRESSION
python3 main.py --strict
```

Sample verdict for the bundled plans: baseline scores **95 (A)**, candidate
**40 (D)** — the candidate lost both indexes (two new sequential scans),
its cost rose 142 → 1840 (12.96×), and it scans all 12 partitions of
`orders` despite a partition-key filter.

As a library:

```python
from plan_auditor import PlanAuditor, build_demo_db, audit_sqlite_query

report = PlanAuditor().audit_files("sample_data/baseline.json",
                                   "sample_data/candidate.json")
print(report["verdict"], report["regression_count"])

conn = build_demo_db()
result = audit_sqlite_query(conn, "SELECT * FROM orders WHERE user_id = ?", (7,))
print(result["has_seq_scan"], result["score"])   # False 100
```

## How to test

```bash
cd query-plan-regression-auditor
python3 -m pip install pytest   # if pytest is not already available
python3 -m pytest               # 27 tests
```

The suite (`tests/`) covers:

| File | Covers |
|---|---|
| `tests/test_parser.py` | SQLite row parsing, flat JSON (incl. field aliases and cost fallback), nested-tree flattening, bundled sample files |
| `tests/test_detector.py` | Seq-scan detection, new-scan regressions, cost-blowup thresholds, partition-pruning check (missing / OK / unpartitioned / pre-existing) |
| `tests/test_scoring_report.py` | Exact score arithmetic, grade boundaries, report structure and verdicts, Markdown rendering, the `PlanAuditor` facade |
| `tests/test_sqlite_integration.py` | **Real `sqlite3` in-memory queries**: an indexed lookup audits clean as a `SEARCH`, an unindexed predicate is flagged as a `SEQ_SCAN`, and the demo database contents are deterministic |

## Project layout

```
query-plan-regression-auditor/
├── main.py                  # CLI entry point
├── plan_auditor/
│   ├── models.py            # PlanNode / QueryPlan
│   ├── parser.py            # SQLite rows + JSON (flat & tree) -> QueryPlan
│   ├── detector.py          # regression rules / Finding
│   ├── scoring.py           # 0-100 score + grade
│   ├── report.py            # report dict + Markdown / text rendering
│   ├── sqlite_audit.py      # live EXPLAIN QUERY PLAN auditing + demo DB
│   └── auditor.py           # PlanAuditor facade
├── sample_data/
│   ├── baseline.json        # healthy plan: index scans, 1/12 partitions scanned
│   └── candidate.json       # regressed plan: seq scans, 12/12 partitions, 12.96x cost
├── tests/                   # pytest suite (27 tests)
├── pyproject.toml
└── README.md
```

## Author

Rohit Garapati — Network Operations Engineer; portfolio project built with
Python and SQLite.
