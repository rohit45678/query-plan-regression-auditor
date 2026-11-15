"""Regression rules: seq scans, cost blowup, partition pruning."""
from plan_auditor import parse_json_plan
from plan_auditor.detector import (
    audit_single_plan,
    detect_cost_blowup,
    detect_missing_partition_pruning,
    detect_new_seq_scans,
    detect_regressions,
    detect_seq_scans,
)


def _plan(name, nodes, total=None):
    data = {"name": name, "nodes": nodes}
    if total is not None:
        data["total_cost"] = total
    return parse_json_plan(data)


GOOD_ORDERS = {"operation": "Index Scan", "table": "orders", "cost": 85, "rows": 120,
               "index": "idx_orders_user"}
SCAN_ORDERS = {"operation": "Seq Scan", "table": "orders", "cost": 900, "rows": 40000}
SCAN_USERS = {"operation": "Seq Scan", "table": "users", "cost": 50, "rows": 3000}


# -- seq-scan detection ------------------------------------------------------

def test_seq_scan_detection_flags_scans_not_searches():
    plan = _plan("p", [GOOD_ORDERS, SCAN_USERS])
    findings = detect_seq_scans(plan)
    assert len(findings) == 1
    assert findings[0].rule == "SEQ_SCAN" and findings[0].table == "users"
    assert findings[0].severity == "high"


def test_new_seq_scan_is_a_regression_but_preexisting_scan_is_not():
    baseline = _plan("b", [GOOD_ORDERS, SCAN_USERS], total=135)
    candidate = _plan("c", [SCAN_ORDERS, SCAN_USERS], total=950)
    new = detect_new_seq_scans(baseline, candidate)
    assert [f.table for f in new] == ["orders"]  # users was already scanned
    rules = {f.rule for f in detect_regressions(baseline, candidate)}
    assert "NEW_SEQ_SCAN" in rules


# -- cost blowup --------------------------------------------------------------

def test_cost_blowup_detected_above_threshold():
    baseline = _plan("b", [GOOD_ORDERS], total=100)
    candidate = _plan("c", [SCAN_ORDERS], total=400)
    findings = detect_cost_blowup(baseline, candidate)
    assert len(findings) == 1
    assert findings[0].rule == "COST_BLOWUP"
    assert findings[0].baseline_value == 100 and findings[0].candidate_value == 400
    assert findings[0].severity == "critical"  # 4x >= 3x


def test_cost_blowup_not_flagged_for_small_or_cheaper_changes():
    baseline = _plan("b", [GOOD_ORDERS], total=100)
    similar = _plan("c", [GOOD_ORDERS], total=120)      # 1.2x < 1.5x
    cheaper = _plan("c", [GOOD_ORDERS], total=50)
    tiny_base = _plan("b", [GOOD_ORDERS], total=2)
    tiny_cand = _plan("c", [GOOD_ORDERS], total=5)      # 2.5x but +3 < min_absolute
    assert detect_cost_blowup(baseline, similar) == []
    assert detect_cost_blowup(baseline, cheaper) == []
    assert detect_cost_blowup(tiny_base, tiny_cand) == []


def test_cost_blowup_respects_custom_threshold():
    baseline = _plan("b", [GOOD_ORDERS], total=100)
    candidate = _plan("c", [GOOD_ORDERS], total=180)
    assert detect_cost_blowup(baseline, candidate, threshold_ratio=2.0) == []
    assert len(detect_cost_blowup(baseline, candidate, threshold_ratio=1.5)) == 1


# -- partition pruning ---------------------------------------------------------

def _partitioned(scanned, pruned, total=12, filtered=True):
    return {"operation": "Index Scan", "table": "orders", "cost": 90, "rows": 100,
            "partitioned": True, "partition_filter": filtered,
            "partitions_total": total, "partitions_scanned": scanned,
            "partitions_pruned": pruned}


def test_missing_partition_pruning_detected():
    plan = _plan("p", [_partitioned(scanned=12, pruned=0)])
    findings = detect_missing_partition_pruning(plan)
    assert len(findings) == 1
    assert findings[0].rule == "MISSING_PARTITION_PRUNING"
    assert findings[0].table == "orders"


def test_partition_pruning_ok_when_partitions_are_pruned():
    plan = _plan("p", [_partitioned(scanned=1, pruned=11)])
    assert detect_missing_partition_pruning(plan) == []
    assert plan.pruning_failures() == []


def test_unpartitioned_table_has_no_pruning_finding():
    plan = _plan("p", [GOOD_ORDERS])
    assert detect_missing_partition_pruning(plan) == []


def test_pruning_regression_only_when_baseline_pruned():
    baseline = _plan("b", [_partitioned(scanned=1, pruned=11)], total=90)
    candidate = _plan("c", [_partitioned(scanned=12, pruned=0)], total=95)
    rules = {f.rule for f in detect_regressions(baseline, candidate)}
    assert "MISSING_PARTITION_PRUNING" in rules
    # Both plans failing to prune is a pre-existing problem, not a regression.
    both_bad = detect_regressions(candidate, candidate)
    assert "MISSING_PARTITION_PRUNING" not in {f.rule for f in both_bad}


def test_audit_single_plan_combines_scan_and_pruning():
    node = dict(SCAN_ORDERS, partitioned=True, partition_filter=True,
                partitions_total=12, partitions_scanned=12, partitions_pruned=0)
    findings = audit_single_plan(_plan("p", [node]))
    assert {f.rule for f in findings} == {"SEQ_SCAN", "MISSING_PARTITION_PRUNING"}
