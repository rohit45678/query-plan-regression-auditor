"""Regression detection rules.

Each rule is a small, pure function over one plan (what is wrong with
this plan on its own?) or two plans (what got *worse* from baseline to
candidate?).  :func:`detect_regressions` composes them into the single
list the report is built from.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .models import QueryPlan

SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass
class Finding:
    rule: str                    # SEQ_SCAN / COST_BLOWUP / MISSING_PARTITION_PRUNING / ...
    severity: str                # low | medium | high | critical
    message: str
    table: str | None = None
    baseline_value: float | None = None
    candidate_value: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Single-plan rules
# --------------------------------------------------------------------------

def detect_seq_scans(plan: QueryPlan) -> list[Finding]:
    """Flag every sequential / full scan in *plan*."""
    findings: list[Finding] = []
    for node in plan.seq_scan_nodes():
        if node.uses_index:
            severity, kind = "medium", "full index scan"
        else:
            severity, kind = "high", "sequential / full table scan"
        findings.append(
            Finding(
                rule="SEQ_SCAN",
                severity=severity,
                table=node.table,
                message=(
                    f"{kind} on table '{node.table}' "
                    f"(detail: {node.detail or node.operation}) -- "
                    "every row is visited; an index search would not be."
                ),
            )
        )
    return findings


def detect_missing_partition_pruning(plan: QueryPlan) -> list[Finding]:
    """Flag partitioned tables where no partition is pruned away."""
    findings: list[Finding] = []
    for node in plan.pruning_failures():
        filter_note = (
            " despite a partition-key filter in the query"
            if node.partition_filter else ""
        )
        findings.append(
            Finding(
                rule="MISSING_PARTITION_PRUNING",
                severity="high",
                table=node.table,
                message=(
                    f"no partition pruning on '{node.table}': "
                    f"{node.partitions_scanned}/{node.partitions_total} partitions "
                    f"scanned{filter_note}. Partition pruning / a partition-aware "
                    "predicate should reduce this to the matching partition(s)."
                ),
                candidate_value=float(node.partitions_scanned or 0),
            )
        )
    return findings


def audit_single_plan(plan: QueryPlan) -> list[Finding]:
    """All single-plan findings (seq scans + pruning failures)."""
    return detect_seq_scans(plan) + detect_missing_partition_pruning(plan)


# --------------------------------------------------------------------------
# Baseline-vs-candidate rules
# --------------------------------------------------------------------------

def detect_cost_blowup(
    baseline: QueryPlan,
    candidate: QueryPlan,
    threshold_ratio: float = 1.5,
    min_absolute: float = 10.0,
) -> list[Finding]:
    """Flag a total-cost increase beyond *threshold_ratio*.

    Both conditions must hold -- a ratio alone fires on trivial plans
    (2 -> 4 is 2x but meaningless), so an absolute floor is required
    too.  A zero-cost baseline with a real candidate cost is a blowup
    by definition.
    """
    base, cand = float(baseline.total_cost or 0), float(candidate.total_cost or 0)
    if cand <= base:
        return []
    diff = cand - base
    ratio = (cand / base) if base > 0 else float("inf")
    if base > 0 and ratio < threshold_ratio:
        return []
    if diff < min_absolute:
        return []
    ratio_text = "inf" if ratio == float("inf") else f"{ratio:.2f}x"
    return [
        Finding(
            rule="COST_BLOWUP",
            severity="critical" if ratio >= 3.0 else "high",
            message=(
                f"total plan cost blew up from {base:.1f} to {cand:.1f} "
                f"({ratio_text}, +{diff:.1f}) -- threshold is "
                f"{threshold_ratio:.2f}x with a minimum increase of {min_absolute:.1f}."
            ),
            baseline_value=base,
            candidate_value=cand,
        )
    ]


def detect_new_seq_scans(baseline: QueryPlan, candidate: QueryPlan) -> list[Finding]:
    """Flag tables that were searched in baseline but are scanned now."""
    baseline_scanned = {n.table for n in baseline.seq_scan_nodes()}
    findings: list[Finding] = []
    for node in candidate.seq_scan_nodes():
        if node.table and node.table not in baseline_scanned:
            base_node = baseline.node_for_table(node.table)
            was = (
                f"baseline used '{base_node.detail or base_node.operation}'"
                if base_node else "baseline did not scan this table"
            )
            findings.append(
                Finding(
                    rule="NEW_SEQ_SCAN",
                    severity="critical",
                    table=node.table,
                    message=(
                        f"new sequential scan on '{node.table}': {was}, "
                        f"candidate uses '{node.detail or node.operation}'. "
                        "A lost/changed index or a changed predicate is the usual cause."
                    ),
                )
            )
    return findings


def detect_row_estimate_blowup(
    baseline: QueryPlan,
    candidate: QueryPlan,
    threshold_ratio: float = 10.0,
) -> list[Finding]:
    """Flag per-table row estimates that exploded between plans."""
    findings: list[Finding] = []
    for node in candidate.nodes:
        if not node.table or not node.rows:
            continue
        base_node = baseline.node_for_table(node.table)
        if base_node and base_node.rows and node.rows >= base_node.rows * threshold_ratio:
            findings.append(
                Finding(
                    rule="ROW_ESTIMATE_BLOWUP",
                    severity="medium",
                    table=node.table,
                    message=(
                        f"estimated rows for '{node.table}' rose from "
                        f"{base_node.rows:.0f} to {node.rows:.0f} "
                        f"({node.rows / base_node.rows:.1f}x)."
                    ),
                    baseline_value=float(base_node.rows),
                    candidate_value=float(node.rows),
                )
            )
    return findings


def detect_regressions(
    baseline: QueryPlan,
    candidate: QueryPlan,
    threshold_ratio: float = 1.5,
    min_absolute: float = 10.0,
) -> list[Finding]:
    """The full regression list for a baseline -> candidate pair.

    Order is stable and severity-meaningful: new seq scans, cost
    blowup, missing partition pruning, row-estimate blowup.  Plain
    ``SEQ_SCAN`` findings for scans that already existed in the
    baseline are *not* regressions, so they are excluded here (they
    still show up in a single-plan audit of the candidate).
    """
    findings: list[Finding] = []
    findings += detect_new_seq_scans(baseline, candidate)
    findings += detect_cost_blowup(
        baseline, candidate, threshold_ratio=threshold_ratio, min_absolute=min_absolute
    )
    # Pruning failures count as regressions only if the baseline pruned.
    baseline_pruning_tables = {n.table for n in baseline.pruning_failures()}
    for finding in detect_missing_partition_pruning(candidate):
        if finding.table not in baseline_pruning_tables:
            finding.rule = "MISSING_PARTITION_PRUNING"
            findings.append(finding)
    findings += detect_row_estimate_blowup(baseline, candidate)
    return findings
