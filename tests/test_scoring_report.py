"""Scoring, report structure, rendering, and the PlanAuditor facade."""
from pathlib import Path

from plan_auditor import PlanAuditor, build_report, grade_for_score, parse_json_plan, render_markdown, score_plan

ROOT = Path(__file__).resolve().parents[1]

GOOD = {"name": "good", "total_cost": 90, "nodes": [
    {"operation": "Index Scan", "table": "orders", "cost": 85, "rows": 10, "index": "idx"},
    {"operation": "SORT", "cost": 5, "rows": 10},
]}
BAD = {"name": "bad", "total_cost": 1840, "nodes": [
    {"operation": "Seq Scan", "table": "orders", "cost": 1650, "rows": 50000,
     "partitioned": True, "partition_filter": True,
     "partitions_total": 12, "partitions_scanned": 12, "partitions_pruned": 0},
    {"operation": "Seq Scan", "table": "users", "cost": 140, "rows": 5000},
    {"operation": "SORT", "cost": 50, "rows": 50000},
]}


def test_score_good_plan_beats_bad_plan_with_exact_values():
    good, bad = parse_json_plan(GOOD), parse_json_plan(BAD)
    # good: 100, no deductions (cost 90 < 100) -> 100
    assert score_plan(good) == 100
    # bad: 100 -15 (orders scan) -15 (users scan) -20 (pruning) -10 (cost >= 1000) = 40
    assert score_plan(bad) == 40
    assert score_plan(good) > score_plan(bad)


def test_grade_boundaries():
    assert grade_for_score(100) == "A" and grade_for_score(90) == "A"
    assert grade_for_score(75) == "B" and grade_for_score(60) == "C"
    assert grade_for_score(40) == "D" and grade_for_score(39) == "F"


def test_report_structure_and_verdict_for_regression():
    report = build_report(parse_json_plan(GOOD), parse_json_plan(BAD))
    assert report["verdict"] == "REGRESSION" and report["is_regression"] is True
    assert report["regression_count"] == len(report["regressions"]) >= 3
    rules = {r["rule"] for r in report["regressions"]}
    assert {"NEW_SEQ_SCAN", "COST_BLOWUP", "MISSING_PARTITION_PRUNING"} <= rules
    assert report["score_delta"] == 40 - 100
    assert report["cost_delta"] == 1840.0 - 90.0
    assert report["baseline"]["grade"] == "A"
    assert report["recommendations"]  # non-empty, actionable


def test_report_ok_for_identical_plans():
    plan = parse_json_plan(GOOD)
    report = build_report(plan, plan)
    assert report["verdict"] == "OK" and report["is_regression"] is False
    assert report["regression_count"] == 0


def test_markdown_rendering_contains_title_scores_and_findings():
    md = render_markdown(build_report(parse_json_plan(GOOD), parse_json_plan(BAD)))
    assert "Automated Query-Plan Regression Auditor" in md
    assert "Partition-Pruning Optimization Framework" in md
    assert "REGRESSION" in md and "COST_BLOWUP" in md
    assert "Recommendations" in md


def test_auditor_facade_on_bundled_sample_files():
    report = PlanAuditor().audit_files(
        ROOT / "sample_data" / "baseline.json", ROOT / "sample_data" / "candidate.json"
    )
    assert report["is_regression"] is True
    assert report["candidate"]["seq_scan_count"] == 2
