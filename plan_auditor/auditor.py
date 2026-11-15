"""High-level facade tying parser -> detector -> scoring -> report together."""
from __future__ import annotations

from pathlib import Path

from .models import QueryPlan
from .parser import load_plan_file
from .report import build_report, render_markdown, render_text


class PlanAuditor:
    """Audit a candidate plan against a baseline plan."""

    def __init__(self, threshold_ratio: float = 1.5, min_absolute: float = 10.0):
        self.threshold_ratio = threshold_ratio
        self.min_absolute = min_absolute

    def audit(self, baseline: QueryPlan, candidate: QueryPlan) -> dict:
        return build_report(
            baseline,
            candidate,
            threshold_ratio=self.threshold_ratio,
            min_absolute=self.min_absolute,
        )

    def audit_files(self, baseline_path: str | Path, candidate_path: str | Path) -> dict:
        return self.audit(load_plan_file(baseline_path), load_plan_file(candidate_path))

    def audit_files_markdown(
        self, baseline_path: str | Path, candidate_path: str | Path
    ) -> str:
        return render_markdown(self.audit_files(baseline_path, candidate_path))

    def audit_text(self, baseline: QueryPlan, candidate: QueryPlan) -> str:
        return render_text(self.audit(baseline, candidate))
