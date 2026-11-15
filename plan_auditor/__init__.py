"""Automated Query-Plan Regression Auditor & Partition-Pruning Optimization Framework."""
from .auditor import PlanAuditor
from .detector import Finding, audit_single_plan, detect_regressions
from .models import PlanNode, QueryPlan
from .parser import load_plan_file, parse_json_plan, parse_plan_text, parse_sqlite_rows
from .report import build_report, render_markdown, render_text
from .scoring import grade_for_score, score_plan, score_summary
from .sqlite_audit import audit_sqlite_query, build_demo_db, explain_query

__all__ = [
    "Finding",
    "PlanAuditor",
    "PlanNode",
    "QueryPlan",
    "audit_single_plan",
    "audit_sqlite_query",
    "build_demo_db",
    "build_report",
    "detect_regressions",
    "explain_query",
    "grade_for_score",
    "load_plan_file",
    "parse_json_plan",
    "parse_plan_text",
    "parse_sqlite_rows",
    "render_markdown",
    "render_text",
    "score_plan",
    "score_summary",
]

__version__ = "1.0.0"
