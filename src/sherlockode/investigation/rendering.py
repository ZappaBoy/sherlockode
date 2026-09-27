from sherlockode.domain.evidence import Evidence
from sherlockode.investigation.models import InvestigationReport


def render_markdown(report: InvestigationReport) -> str:
    evidence = {item.id: item for item in report.evidence}
    manifest = report.manifest
    lines = [
        f"# Investigation {manifest.id}",
        "",
        f"**Question:** {manifest.question}",
        "",
        f"**Scope:** {', '.join(manifest.resolved_scope) or 'all repositories'}  ",
        f"**Model:** {manifest.model}  ",
        f"**Status:** {manifest.status.value}",
        "",
        "## Answer",
        "",
        report.answer.answer,
        "",
        "## Findings",
        "",
    ]
    for finding in report.answer.findings:
        lines.append(f"- **[{finding.kind.value}]** {finding.statement}")
        lines += [f"  - `{eid}` {_describe(evidence[eid])}" for eid in finding.evidence_ids if eid in evidence]
    if report.answer.limitations:
        lines += ["", "## Limitations", "", *(f"- {item}" for item in report.answer.limitations)]
    if report.plan:
        lines += ["", "## Plan", "", f"_{report.plan.objective}_", ""]
        lines += [f"{step.id}. {step.goal} ({', '.join(step.data_sources)})" for step in report.plan.steps]
    lines += ["", "## Trace", "", f"{len(report.steps)} tool calls, {len(report.evidence)} evidence items."]
    return "\n".join(lines) + "\n"


def _describe(item: Evidence) -> str:
    return f"{item.statement} — {item.source.describe()}"
