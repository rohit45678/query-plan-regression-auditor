"""Plan scoring: one deterministic 0-100 score per plan.

The score is deliberately simple and explainable -- every deduction
maps to a named problem, so the report can say *why* a plan scored
what it did, and tests can pin the arithmetic down exactly.

Deductions
----------
* sequential / full scan ......... -15 per node (full index scan: -8)
* missing partition pruning ...... -20 per node
* total cost >= 100 ................ -5
* total cost >= 1,000 .............. -10 (instead of the -5 tier)
* total cost >= 10,000 ............. -20 (instead of the lower tiers)
"""
from __future__ import annotations

from .models import QueryPlan


def score_plan(plan: QueryPlan) -> int:
    score = 100
    for node in plan.seq_scan_nodes():
        score -= 8 if node.uses_index else 15
    for _node in plan.pruning_failures():
        score -= 20
    cost = float(plan.total_cost or 0)
    if cost >= 10_000:
        score -= 20
    elif cost >= 1_000:
        score -= 10
    elif cost >= 100:
        score -= 5
    return max(0, min(100, score))


def grade_for_score(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def score_summary(plan: QueryPlan) -> dict:
    score = score_plan(plan)
    return {
        "name": plan.name,
        "score": score,
        "grade": grade_for_score(score),
        "total_cost": float(plan.total_cost or 0),
        "node_count": len(plan.nodes),
        "seq_scan_count": len(plan.seq_scan_nodes()),
        "tables": plan.tables(),
    }
