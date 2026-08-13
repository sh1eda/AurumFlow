"""Outcome-neutral D007 historical report rendering."""

from __future__ import annotations

from typing import Mapping


_CLASSIFICATIONS = {
    "NON_REDUNDANT_COMPONENT_CANDIDATE": "positive non-redundant component candidate",
    "CONDITIONAL_CANDIDATE": "context-dependent conditional candidate",
    "GEOMETRY_CANDIDATE": "geometry candidate",
    "REJECT_COMPONENT": "negative result; component rejected",
    "STRUCTURALLY_VALID_EMPIRICALLY_WEAK": "null or mixed result; structurally valid but empirically weak",
    "INSUFFICIENT_EVIDENCE": "insufficient evidence or sample inadequate",
    "REPRODUCIBILITY_DEFECT": "invalid result due to a reproducibility defect",
}


def _value(mapping: Mapping[str, object], key: str, default: object = "not available") -> object:
    value = mapping.get(key, default)
    return default if value is None else value


def render_historical_report(result: Mapping[str, object]) -> str:
    """Render only supplied computed statuses; never infer optimistic language."""

    disposition = str(result.get("disposition", "INSUFFICIENT_EVIDENCE"))
    if disposition not in _CLASSIFICATIONS:
        raise ValueError("unregistered D007 disposition")
    adequacy = result.get("adequacy", {})
    statistics = result.get("statistics", {})
    provenance = result.get("provenance", {})
    counts = result.get("counts", {})
    controls = result.get("controls", {})
    interactions = result.get("interactions", {})
    redundancy = result.get("redundancy", {})
    geometry = result.get("geometry", {})
    if not all(isinstance(value, Mapping) for value in (adequacy, statistics, provenance, counts, controls, interactions, redundancy, geometry)):
        raise ValueError("D007 report sections must be mappings")
    lines = [
        "# D007 OTE Historical Research Report",
        "",
        "## Final classification",
        "",
        f"- Disposition: `{disposition}`",
        f"- Interpretation: {_CLASSIFICATIONS[disposition]}.",
        "- Research-only: this classification does not authorize production use or strategy-default changes.",
        "",
        "## Provenance",
        "",
        f"- Source lineage: `{_value(provenance, 'source_lineage')}`",
        f"- Source authentication: `{_value(provenance, 'source_status')}`",
        f"- Upstream authentication: `{_value(provenance, 'upstream_status')}`",
        "- Historical years: New York named trading dates 2022-2025; 2026 excluded.",
        "",
        "## Eligibility and exclusions",
        "",
        f"- Constructed primary ranges: `{_value(counts, 'constructed_ranges', 0)}`",
        f"- Lifecycle eligible: `{_value(counts, 'lifecycle_eligible', 0)}`",
        f"- First causal touches: `{_value(counts, 'first_touches', 0)}`",
        f"- Endpoint-complete primary pairs: `{_value(counts, 'primary_pairs', 0)}`",
        f"- Exclusions: `{_value(counts, 'exclusions', {})}`",
        "",
        "## Primary findings",
        "",
        f"- Primary paired result: `{_value(statistics, 'primary_status')}`",
        f"- Primary mean difference: `{_value(statistics, 'primary_mean_difference')}`",
        f"- Primary 95% interval: `{_value(statistics, 'primary_interval')}`",
        "",
        "## Control findings",
        "",
        f"- Frozen control results: `{dict(controls)}`",
        "",
        "## 0.705 sensitivity and geometry",
        "",
        f"- Registered geometry family: `{dict(geometry)}`",
        "",
        "## Interactions",
        "",
        f"- Frozen six-member interaction family: `{dict(interactions)}`",
        "- D004 remains exploratory and D006 remains descriptive/non-decisional.",
        "",
        "## Redundancy and ablation",
        "",
        f"- Frozen structural and two-ablation results: `{dict(redundancy)}`",
        "",
        "## Adequacy",
        "",
        f"- Global adequacy: `{_value(adequacy, 'status', 'SAMPLE_INADEQUATE')}`",
        f"- Requirements: `{_value(adequacy, 'requirements', {})}`",
        "",
        "## Statistical validation",
        "",
        f"- Frozen inference summary: `{dict(statistics)}`",
        "",
        "## Limitations",
        "",
        "- This is an observational, research-only component study and contains no P&L, execution, sizing, stop, or target interpretation.",
        "- D006 evidence has distinct D003-v2 provenance and cannot affect a decisional D007 disposition.",
        "- A missing or inadequate frozen cell is not rescued by another cell.",
        "",
        "## Leakage and tuning declaration",
        "",
        "- Frozen upstream projections excluded unregistered outcome, later_*, retrospective_*, and endpoint-like columns.",
        "- No runtime methodology parameters, adaptive matching, threshold selection, horizon substitution, or outcome-based tuning were used.",
        "",
    ]
    return "\n".join(lines)


__all__ = ["render_historical_report"]
