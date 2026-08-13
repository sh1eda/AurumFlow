from __future__ import annotations

import pytest

from research.d007_ote_historical_contract.reporting import render_historical_report


@pytest.mark.parametrize(
    ("disposition", "phrase"),
    [
        ("NON_REDUNDANT_COMPONENT_CANDIDATE", "positive non-redundant"),
        ("CONDITIONAL_CANDIDATE", "context-dependent"),
        ("GEOMETRY_CANDIDATE", "geometry candidate"),
        ("REJECT_COMPONENT", "negative result"),
        ("STRUCTURALLY_VALID_EMPIRICALLY_WEAK", "null or mixed"),
        ("INSUFFICIENT_EVIDENCE", "sample inadequate"),
        ("REPRODUCIBILITY_DEFECT", "reproducibility defect"),
    ],
)
def test_report_language_is_derived_from_frozen_disposition(disposition: str, phrase: str) -> None:
    report = render_historical_report({"disposition": disposition})
    assert phrase in report
    assert "does not authorize production" in report
    assert "Leakage and tuning declaration" in report


def test_report_rejects_unknown_disposition_and_invalid_sections() -> None:
    with pytest.raises(ValueError, match="unregistered"):
        render_historical_report({"disposition": "VERY_GOOD"})
    with pytest.raises(ValueError, match="mappings"):
        render_historical_report({"controls": []})

