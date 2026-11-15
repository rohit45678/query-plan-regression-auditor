"""Report generation: a structured dict plus Markdown / text renderings."""
from __future__ import annotations

from .detector import Finding, SEVERITY_ORDER, detect_regressions
from .models import QueryPlan
from .scoring import score_summary

TITLE = (
    "Automated Query-Plan Regression Auditor "
    "& Partition-Pruning Optimization Framework"
)


def _recommendations(findings: list[Finding]) -> list[str]:
    recs: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        if text not in seen:
            seen.add(text)
            recs.append(text)

    for f in findings:
        if f.rule in {"SEQ_SCAN", "NEW_SEQ_SCAN"}:
            add(
                f"Add or restore an index matching the predicate on "
                f"'{f.table}' so the plan uses a SEARCH / index scan instead of a full scan."
            )
        elif f.rule == "MISSING_PARTITION_PRUNING":
            add(
                f"Make the predicate on '{f.table}' partition-aware (filter directly on "
                "the partition key, avoid wrapping it in a function) so unneeded "
                "partitions are pruned."
            )
        elif f.rule == "COST_BLOWUP":
            add(
                "Investigate the cost blowup first: compare per-node costs with the "
                "baseline, refresh statistics (ANALYZE), and check for a dropped index."
            )
        elif f.rule == "ROW_ESTIMATE_BLOWUP":
            add(
                f"Row estimates for '{f.table}' changed sharply -- refresh table "
                "statistics and check whether the predicate selectivity really changed."
            )
    if not recs:
        recs.append("No action required: candidate plan matches the baseline's access paths.")
    return recs


def build_report(
    baseline: QueryPlan,
    candidate: QueryPlan,
    threshold_ratio: float = 1.5,
    min_absolute: float = 10.0,
) -> dict:
    """Build the full audit report dict for a baseline -> candidate pair."""
    findings = detect_regressions(
        baseline, candidate, threshold_ratio=threshold_ratio, min_absolute=min_absolute
    )
    base_summary = score_summary(baseline)
    cand_summary = score_summary(candidate)
    worst = max((SEVERITY_ORDER[f.severity] for f in findings), default=0)
    if worst >= 3:
        verdict = "REGRESSION"
    elif findings:
        verdict = "WARNING"
    else:
        verdict = "OK"
    return {
        "title": TITLE,
        "verdict": verdict,
        "is_regression": verdict == "REGRESSION",
        "baseline": base_summary,
        "candidate": cand_summary,
        "score_delta": cand_summary["score"] - base_summary["score"],
        "cost_delta": cand_summary["total_cost"] - base_summary["total_cost"],
        "regression_count": len(findings),
        "regressions": [f.to_dict() for f in findings],
        "recommendations": _recommendations(findings),
    }


def render_markdown(report: dict) -> str:
    b, c = report["baseline"], report["candidate"]
    lines = [
        f"# {report['title']}",
        "",
        f"**Verdict: {report['verdict']}** "
        f"({report['regression_count']} regression finding(s))",
        "",
        "## Plan scores",
        "",
        "| Plan | Score | Grade | Total cost | Nodes | Seq scans |",
        "|---|---|---|---|---|---|",
        f"| {b['name']} (baseline) | {b['score']} | {b['grade']} | {b['total_cost']:.1f} | {b['node_count']} | {b['seq_scan_count']} |",
        f"| {c['name']} (candidate) | {c['score']} | {c['grade']} | {c['total_cost']:.1f} | {c['node_count']} | {c['seq_scan_count']} |",
        "",
        f"Score delta: {report['score_delta']:+d} · Cost delta: {report['cost_delta']:+.1f}",
        "",
        "## Regressions",
        "",
    ]
    if report["regressions"]:
        for f in report["regressions"]:
            lines.append(f"- **[{f['severity'].upper()}] {f['rule']}** — {f['message']}")
    else:
        lines.append("No regressions detected.")
    lines += ["", "## Recommendations", ""]
    lines += [f"- {r}" for r in report["recommendations"]]
    lines.append("")
    return "\n".join(lines)


def render_text(report: dict) -> str:
    md = render_markdown(report)
    return md.replace("# ", "").replace("## ", "").replace("**", "")
