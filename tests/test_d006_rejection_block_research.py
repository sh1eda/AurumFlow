from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path
import shutil

import pandas as pd
import pytest

from research.d006_rejection_block_research.config import (
    D006Config,
    FIXED_CONTROLS_REGISTRY,
    FIXED_INTERACTIONS,
    FIXED_MULTIPLE_TESTING,
    config_fingerprint,
)
from research.d006_rejection_block_research.detector import _attach_relationships, detect_rejection_blocks
from research.d006_rejection_block_research.lifecycle import combine_structural_records, evaluate_lifecycle
from research.d006_rejection_block_research.models import Direction, LifecycleRecord, RejectionBlock
from research.d006_rejection_block_research.preflight import (
    assert_allowed_changed_paths,
    assert_no_scientific_output_dir,
    inspect_static_package,
    run_preflight,
)
from research.d006_rejection_block_research.schemas import (
    AGGREGATE_AUDIT_FIELDS,
    CONTROL_KEYS,
    DEFINITION_KEYS,
    DENOMINATOR_KEYS,
    EXCLUSION_KEYS,
    GEOMETRY_KEYS,
    INTERACTION_KEYS,
    SESSION_KEYS,
    STRUCTURAL_DETECTOR_FIELDS,
    YEAR_KEYS,
    SchemaError,
    validate_aggregate_audit,
    validate_bars,
    validate_fail_report,
)


def _bars(direction: Direction = Direction.BULLISH, cluster: bool = False) -> pd.DataFrame:
    index = pd.date_range("2024-01-02 00:00", periods=24, freq="5min", tz="UTC", name="timestamp_utc")
    rows = [dict(open=100.0, high=106.0, low=94.0, close=100.0) for _ in index]
    rows[14] = dict(open=100.0, high=106.0, low=94.0, close=104.0)
    if direction is Direction.BULLISH:
        rows[15] = dict(open=95.0, high=105.0, low=85.0, close=102.0)
        if cluster:
            rows[16] = dict(open=94.0, high=104.0, low=84.0, close=97.0)
            rows[17] = dict(open=103.0, high=121.0, low=101.0, close=119.0)
        else:
            rows[16] = dict(open=103.0, high=121.0, low=101.0, close=119.0)
    else:
        rows[15] = dict(open=105.0, high=115.0, low=95.0, close=98.0)
        if cluster:
            rows[16] = dict(open=106.0, high=116.0, low=96.0, close=103.0)
            rows[17] = dict(open=97.0, high=99.0, low=79.0, close=81.0)
        else:
            rows[16] = dict(open=97.0, high=99.0, low=79.0, close=81.0)
    frame = pd.DataFrame(rows, index=index)
    frame["available_at"] = index + pd.Timedelta(minutes=5)
    frame["is_complete"] = True
    frame["bar_id"] = [f"synthetic-{position:03d}" for position in range(len(frame))]
    return frame


def _block(direction: Direction = Direction.BULLISH, availability: str = "2024-01-02 02:00+00:00", distal: float = 90.0, proximal: float = 100.0, creation: str = "2024-01-02 01:00+00:00", block_id: str = "block") -> RejectionBlock:
    timestamp = pd.Timestamp(creation)
    availability_at = pd.Timestamp(availability)
    trading_date = (
        availability_at.tz_convert("America/New_York") + pd.Timedelta(hours=6)
    ).date().isoformat()
    return RejectionBlock(
        block_id=block_id, definition_name="single_wick_50_d3_v1", direction=direction,
        timeframe="5min", source_bar_ids=(block_id + "-bar",), expansion_bar_id=block_id + "-expansion",
        creation_timestamp=timestamp, confirmation_timestamp=availability_at,
        causal_availability=availability_at, distal=distal, proximal=proximal,
        midpoint=(distal + proximal) / 2, range=abs(distal - proximal), normalized_range=1.0,
        session="asia", trading_date=trading_date, context_keys=(),
        preavailability_interaction=False,
    )


@pytest.mark.parametrize("direction", [Direction.BULLISH, Direction.BEARISH])
def test_detects_bullish_and_bearish_synthetic_blocks_with_causal_availability(direction: Direction) -> None:
    bars = _bars(direction)
    blocks = detect_rejection_blocks(bars, bars["available_at"].iloc[-1])
    assert len(blocks) == 1
    block = blocks[0]
    assert block.direction is direction
    assert block.confirmation_timestamp == block.causal_availability
    assert block.causal_availability == bars.loc[bars["bar_id"] == block.expansion_bar_id, "available_at"].iloc[0]
    assert block.creation_timestamp < block.causal_availability
    assert block.trading_date == "2024-01-02"
    assert block.context_keys == ()
    if direction is Direction.BULLISH:
        assert (block.distal, block.proximal, block.midpoint) == (85.0, 95.0, 90.0)
    else:
        assert (block.proximal, block.distal, block.midpoint) == (105.0, 115.0, 110.0)


def test_block_is_unavailable_until_expansion_bar_closes() -> None:
    bars = _bars()
    prefix = bars.iloc[:16]
    assert detect_rejection_blocks(prefix, prefix["available_at"].iloc[-1]) == []
    confirmed = bars.iloc[:17]
    blocks = detect_rejection_blocks(confirmed, confirmed["available_at"].iloc[-1])
    assert len(blocks) == 1
    assert blocks[0].causal_availability == confirmed["available_at"].iloc[-1]


def test_exact_two_candle_cluster_is_registered_without_a_grid() -> None:
    blocks = detect_rejection_blocks(_bars(cluster=True), "2024-01-02 02:00+00:00")
    assert {block.definition_name for block in blocks} == {
        "single_wick_50_d3_v1", "cluster2_wick_50_d3_v1"
    }
    assert any(len(block.source_bar_ids) == 2 for block in blocks)
    config = D006Config()
    assert [definition.rejection_bar_count for definition in config.definitions] == [1, 2]
    with pytest.raises(ValueError, match="fixed"):
        D006Config(definitions=(config.definitions[0],))
    with pytest.raises(ValueError, match="without a grid"):
        replace(config, wick_fraction_minimum=0.40)
    with pytest.raises(ValueError, match="without a grid"):
        replace(config, confirmation_bars=5)


def test_bar_schema_fails_closed_for_utc_missing_duplicate_out_of_order_and_incomplete() -> None:
    bars = _bars()
    with pytest.raises(SchemaError, match="explicit UTC"):
        validate_bars(bars.set_axis(bars.index.tz_localize(None), axis=0), bars["available_at"].iloc[-1])
    with pytest.raises(SchemaError, match="missing"):
        validate_bars(bars.drop(columns="open"), bars["available_at"].iloc[-1])
    duplicated = pd.concat([bars, bars.iloc[[0]]]).sort_index()
    with pytest.raises(SchemaError, match="unique"):
        validate_bars(duplicated, bars["available_at"].iloc[-1])
    with pytest.raises(SchemaError, match="ordered"):
        validate_bars(bars.iloc[::-1], bars["available_at"].iloc[-1])
    gapped = bars.drop(bars.index[14])
    validate_bars(gapped, bars["available_at"].iloc[-1])
    assert detect_rejection_blocks(gapped, bars["available_at"].iloc[-1]) == []
    unordered_ids = bars.copy()
    unordered_ids["bar_id"] = unordered_ids["bar_id"].iloc[::-1].to_list()
    with pytest.raises(SchemaError, match="strictly ordered"):
        validate_bars(unordered_ids, bars["available_at"].iloc[-1])
    incomplete = bars.copy()
    incomplete.loc[incomplete.index[0], "is_complete"] = False
    with pytest.raises(SchemaError, match="complete"):
        validate_bars(incomplete, bars["available_at"].iloc[-1])
    with pytest.raises(SchemaError, match="after evaluation"):
        validate_bars(bars, bars.index[-1])
    null_available = bars.copy()
    null_available.loc[null_available.index[0], "available_at"] = pd.NaT
    with pytest.raises(SchemaError, match="non-null"):
        validate_bars(null_available, bars["available_at"].iloc[-1])
    mixed_ids = bars.copy()
    mixed_ids["bar_id"] = mixed_ids["bar_id"].astype(object)
    mixed_ids.loc[mixed_ids.index[0], "bar_id"] = 1
    with pytest.raises(SchemaError, match="strings"):
        validate_bars(mixed_ids, bars["available_at"].iloc[-1])


def test_lifecycle_excludes_confirmation_bar_and_applies_precedence() -> None:
    block = _block(availability="2024-01-02 01:25+00:00", distal=90.0, proximal=100.0)
    bars = _bars().iloc[15:20].copy()
    # The confirmation bar begins before causal availability and cannot touch the block.
    bars.loc[bars.index[0], ["low", "high", "close"]] = [80.0, 105.0, 80.0]
    # At the eligible bar, invalidation wins over midpoint reach and any touch.
    bars.loc[bars.index[2], ["low", "high", "close"]] = [89.0, 101.0, 89.0]
    record = evaluate_lifecycle(block, bars, bars["available_at"].iloc[-1])
    assert record.status == "INVALIDATED"
    assert record.invalidation_timestamp == bars["available_at"].iloc[2]
    assert record.first_touch_timestamp is None
    assert record.touch_count == 0


def test_lifecycle_retains_first_touch_then_mitigates_and_expires() -> None:
    block = _block(availability="2024-01-02 01:25+00:00")
    bars = _bars().iloc[15:20].copy()
    bars.loc[bars.index[2], ["low", "high", "close"]] = [99.0, 108.0, 106.0]
    bars.loc[bars.index[3], ["low", "high", "close"]] = [99.0, 108.0, 106.0]
    record = evaluate_lifecycle(block, bars, bars["available_at"].iloc[-1])
    assert record.status == "MITIGATED"
    assert record.first_touch_timestamp == bars["available_at"].iloc[2]
    assert record.mitigation_timestamp == bars["available_at"].iloc[4]
    assert record.touch_count == 3
    midpoint_block = _block(availability="2024-01-02 01:25+00:00")
    midpoint_bars = _bars().iloc[15:18].copy()
    midpoint_bars.loc[midpoint_bars.index[2], ["low", "high", "close"]] = [95.0, 108.0, 106.0]
    midpoint = evaluate_lifecycle(midpoint_block, midpoint_bars, midpoint_bars["available_at"].iloc[-1])
    assert midpoint.status == "MITIGATED"
    assert midpoint.first_touch_timestamp == midpoint.mitigation_timestamp
    assert midpoint.touch_count == 1
    expiry_block = _block(
        availability="2024-01-01 00:00+00:00",
        creation="2023-12-31 23:30+00:00",
    )
    expiry_bars = _bars()
    expired = evaluate_lifecycle(expiry_block, expiry_bars, expiry_bars["available_at"].iloc[-1])
    assert expired.status == "EXPIRED"
    assert expired.expiry_timestamp == pd.Timestamp("2024-01-02 00:00+00:00")
    assert expired.expiry_deadline == pd.Timestamp("2024-01-02 00:00+00:00")
    with pytest.raises(ValueError, match="precede causal availability"):
        evaluate_lifecycle(block, bars, "2024-01-02 01:20+00:00")
    with pytest.raises(ValueError, match="first touch cannot follow"):
        LifecycleRecord(
            "bad-order",
            "MITIGATED",
            pd.Timestamp("2024-01-02 01:25+00:00"),
            pd.Timestamp("2024-01-02 01:40+00:00"),
            pd.Timestamp("2024-01-02 01:35+00:00"),
            None,
            None,
            pd.Timestamp("2024-01-03 01:25+00:00"),
            1,
        )


def test_overlap_nesting_ids_and_order_are_deterministic() -> None:
    early = _block(block_id="early", distal=80.0, proximal=105.0)
    later_same = _block(block_id="later", distal=90.0, proximal=100.0, creation="2024-01-02 01:35+00:00")
    opposite = _block(Direction.BEARISH, block_id="opposite", distal=102.0, proximal=92.0, creation="2024-01-02 01:40+00:00")
    related = _attach_relationships([opposite, later_same, early])
    assert [item.block_id for item in related] == ["early", "later", "opposite"]
    assert len({item.overlap_group_id for item in related}) == 1
    assert related[1].parent_block_id == "early"
    assert related[2].parent_block_id is None
    assert len({item.block_id for item in detect_rejection_blocks(_bars(cluster=True), "2024-01-02 02:00+00:00")}) == 3
    first = detect_rejection_blocks(_bars(cluster=True), "2024-01-02 02:00+00:00")
    second = detect_rejection_blocks(_bars(cluster=True), "2024-01-02 02:00+00:00")
    assert first == second
    assert [item.block_id for item in first] == [item.block_id for item in second]
    mutated = [replace(item, overlap_group_id="later-lifecycle-mutation") for item in first]
    assert [item.block_id for item in mutated] == [item.block_id for item in first]


def test_interval_sweep_preserves_transitive_closed_overlap_components() -> None:
    left = _block(block_id="left", distal=80.0, proximal=90.0)
    bridge = _block(
        block_id="bridge", distal=90.0, proximal=100.0,
        creation="2024-01-02 01:30+00:00",
    )
    right = _block(
        block_id="right", distal=100.0, proximal=110.0,
        creation="2024-01-02 01:35+00:00",
    )
    separate = _block(
        block_id="separate", distal=111.0, proximal=120.0,
        creation="2024-01-02 01:40+00:00",
    )
    related = _attach_relationships([right, separate, left, bridge])
    groups = {item.block_id: item.overlap_group_id for item in related}
    assert groups["left"] == groups["bridge"] == groups["right"]
    assert groups["separate"] != groups["right"]


def test_preavailability_accounting_and_combined_parent_lifecycle_are_structural() -> None:
    bars = _bars()
    bars.loc[bars.index[16], ["high", "low", "close"]] = [120.0, 94.0, 119.0]
    detected = detect_rejection_blocks(bars, bars["available_at"].iloc[-1])
    assert detected[0].preavailability_interaction is True
    parent = _block(
        block_id="parent",
        availability="2024-01-02 01:25+00:00",
        distal=80.0,
        proximal=105.0,
    )
    child = replace(
        _block(
            block_id="child",
            availability="2024-01-02 02:00+00:00",
            creation="2024-01-02 01:30+00:00",
        ),
        parent_block_id="parent",
    )
    parent_lifecycle = LifecycleRecord(
        "parent", "ACTIVE_UNTOUCHED", parent.causal_availability,
        None, None, None, None, parent.causal_availability + pd.Timedelta(hours=24), 0,
    )
    child_lifecycle = LifecycleRecord(
        "child", "ACTIVE_UNTOUCHED", child.causal_availability,
        None, None, None, None, child.causal_availability + pd.Timedelta(hours=24), 0,
    )
    combined = combine_structural_records(
        [parent, child], [child_lifecycle, parent_lifecycle]
    )
    assert combined[0].parent_active_at_availability is None
    assert combined[1].parent_active_at_availability is True


def test_structural_models_and_fixed_registries_exclude_trade_and_outcome_content() -> None:
    names = tuple(field.name for field in fields(RejectionBlock))
    assert names == STRUCTURAL_DETECTOR_FIELDS
    lowered = " ".join(names).lower()
    assert all(token not in lowered for token in ("trade", "pnl", "profit", "outcome"))
    assert [item.name for item in FIXED_INTERACTIONS] == [
        "rb_alone", "aligned_d005_context", "after_d004_manipulation", "frozen_liquidity_sweep",
        "displacement_confirmation", "refinement_confirmation", "against_d005_context_negative_control",
    ]
    assert [(item.name, item.hypotheses, item.adjustment) for item in FIXED_MULTIPLE_TESTING] == [
        ("primary", 1, "unadjusted"), ("definition_sensitivity", 1, "BH"),
        ("interactions", 6, "BH"), ("incremental_controls", 4, "BH"), ("geometry", 10, "BH"),
    ]
    with pytest.raises(ValueError, match="version is fixed"):
        D006Config(version="d006-v2")
    assert tuple(item.name for item in FIXED_CONTROLS_REGISTRY) == D006Config().controls
    assert all("120 minutes" in item.exclusions or item.role == "audit" for item in FIXED_CONTROLS_REGISTRY)
    config = D006Config()
    assert (
        config.primary_horizon_minutes,
        config.control_window_days,
        config.control_exclusion_minutes,
        config.volatility_median_days,
        config.volatility_bucket_boundaries,
        config.control_hash_seed,
    ) == (60, 30, 120, 20, (0.75, 1.25), 6006)


def _audit() -> dict[str, object]:
    controls = {
        key: {
            "candidate_count": 1,
            "matched_count": 1,
            "unmatched_count": 0,
            "endpoint_complete_pair_count": 1,
        }
        for key in CONTROL_KEYS
    }
    return {
        "detected": 4, "duplicate_id_excluded": 0, "lifecycle_eligible": 3,
        "endpoint_eligible": 1, "endpoint_complete_count": 1,
        "touched": 1, "untouched": 2,
        "invalidated": 1, "mitigated": 1, "expired": 0, "active_censored": 1, "overlapping": 2, "nested": 1,
        "bullish": 2, "bearish": 2, "preavailability_count": 0,
        "endpoint_coverage_complete": True,
        "expected_primary_pairs": 1, "observed_primary_pairs": 1,
        "controls_expected": 1, "controls_observed": 1, "controls_matched": 1, "controls_unmatched": 0,
        "by_definition": {key: 2 for key in DEFINITION_KEYS},
        "by_year": {key: 1 for key in YEAR_KEYS},
        "by_session": {key: (4 if key == "asia" else 0) for key in SESSION_KEYS},
        "by_direction": {"bullish": 2, "bearish": 2},
        "by_terminal_state": {
            "MITIGATED": 1, "INVALIDATED": 1, "EXPIRED": 0, "ACTIVE_CENSORED": 1,
        },
        "exclusions_by_reason": {
            key: (1 if key == "incomplete_endpoint" else 0)
            for key in EXCLUSION_KEYS
        },
        "primary_exclusions_by_reason": {key: 0 for key in EXCLUSION_KEYS},
        "treatment_control_reconciliation": controls,
        "interactions": {
            key: {
                "candidate_count": 0, "eligible_count": 0, "endpoint_complete_count": 0,
                "matched_count": 0, "excluded_count": 0,
            }
            for key in INTERACTION_KEYS
        },
        "geometry": {
            key: {"eligible_count": 0, "touched_count": 0, "endpoint_complete_count": 0}
            for key in GEOMETRY_KEYS
        },
        "denominator_definitions": {
            key: f"frozen denominator for {key}" for key in DENOMINATOR_KEYS
        },
    }


def test_aggregate_and_fail_report_schemas_reconcile_and_fail_non_decisionally() -> None:
    audit = _audit()
    assert tuple(audit) == AGGREGATE_AUDIT_FIELDS
    validate_aggregate_audit(audit)
    audit["touched"] = 2
    with pytest.raises(SchemaError, match="reconcile"):
        validate_aggregate_audit(audit)
    boolean_audit = _audit()
    boolean_audit["detected"] = True
    with pytest.raises(SchemaError, match="non-negative integers"):
        validate_aggregate_audit(boolean_audit)
    validate_fail_report({
        "integrity": {"status": "INTEGRITY_VERIFIED"},
        "adequacy": {"status": "SAMPLE_INADEQUATE"},
        "primary": {
            "status": "NOT_EVALUATED",
            "mode": "DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE",
        },
    })
    with pytest.raises(SchemaError, match="primary status"):
        validate_fail_report({
            "integrity": {"status": "INTEGRITY_VERIFIED"},
            "adequacy": {"status": "SAMPLE_INADEQUATE"},
            "primary": {"status": "EVALUATED", "mode": "DECISIONAL"},
        })
    validate_fail_report({
        "integrity": {"status": "REPRODUCIBILITY_DEFECT"},
        "adequacy": {"status": "NOT_EVALUATED"},
        "primary": {"status": "NOT_EVALUATED", "mode": "SAFE_AUDIT_ONLY"},
    })
    with pytest.raises(SchemaError, match="closed"):
        validate_fail_report({
            "integrity": {"status": "INTEGRITY_VERIFIED"},
            "adequacy": {"status": "SAMPLE_INADEQUATE"},
            "primary": {
                "status": "NOT_EVALUATED",
                "mode": "DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE",
                "returns": [1.0],
            },
        })
    with pytest.raises(SchemaError, match="forbidden"):
        validate_fail_report({
            "integrity": {"status": "INTEGRITY_VERIFIED"},
            "adequacy": {"status": "SAMPLE_INADEQUATE"},
            "primary": {
                "status": "NOT_EVALUATED",
                "mode": "DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE",
                "profit_factor": 1.5,
            },
        })


def test_preflight_is_static_hash_only_and_historical_phase_aware(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path.cwd()
    source_hashes = inspect_static_package(root / "research/d006_rejection_block_research")
    assert source_hashes
    copied_package = tmp_path / "relocated_package"
    shutil.copytree(root / "research/d006_rejection_block_research", copied_package)
    assert inspect_static_package(copied_package) == source_hashes
    assert {"source", "context", "outcomes", "statistics", "reporting", "pipeline"}.issubset(
        {Path(path).stem for path in source_hashes}
    )
    forbidden_package = tmp_path / "forbidden_package"
    forbidden_package.mkdir()
    (forbidden_package / "detector.py").write_text("import pandas as pd\npd.read_parquet('forbidden')\n", encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden historical/outcome call"):
        inspect_static_package(forbidden_package)
    (forbidden_package / "detector.py").unlink()
    (forbidden_package / "discovery_grid.py").write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden D006 module"):
        inspect_static_package(forbidden_package)
    (forbidden_package / "discovery_grid.py").unlink()
    nested = forbidden_package / "nested"
    nested.mkdir()
    (nested / "bad.py").write_text(
        "import polars as pl\npl.scan_parquet('x')\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="forbidden"):
        inspect_static_package(forbidden_package)
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path.suffix.lower() == ".parquet":
            raise AssertionError(f"canonical Parquet payload opened: {path}")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    result = run_preflight(
        root,
        ["research/d006_rejection_block_research/config.py", "tests/test_d006_rejection_block_research.py"],
        historical_execution_authorized=True,
    )
    assert result.spec_hash_status == "VERIFIED"
    assert result.protected_hashes and result.data_metadata_hashes
    assert len(result.implementation_fingerprint) == 64
    assert result.accessed_parquet is result.accessed_historical_outcomes is result.wrote_outputs is False
    assert config_fingerprint() == config_fingerprint(D006Config())
    with pytest.raises(ValueError, match="outside"):
        assert_allowed_changed_paths(["xauusd_signal/strategy.py"])
    with pytest.raises(ValueError, match="output"):
        assert_no_scientific_output_dir(tmp_path / "missing") if False else _output_dir_error(tmp_path)


def _output_dir_error(root: Path) -> None:
    (root / "research/d006_rejection_block_research/outputs").mkdir(parents=True)
    assert_no_scientific_output_dir(root)


def test_d006_write_scope_is_milestone_scoped_and_protects_prior_work() -> None:
    """Exercise the active-D006 scope guard without policing later worktrees."""

    assert_allowed_changed_paths(
        (
            "docs/D006_REJECTION_BLOCK_RESEARCH_SPEC.md",
            "research/d006_rejection_block_research/config.py",
            "tests/test_d006_rejection_block_research.py",
        )
    )

    forbidden_during_d006 = (
        "docs/D003_ACCEPTANCE_REPORT.md",
        "docs/D004_XAUUSD_0830_0900_MANIPULATION_RESEARCH.md",
        "docs/D005_STRATEGY_SOURCE_AUDIT.md",
        "docs/D005_E4_1H_5M_REVERSAL_REPLICATION_SPEC.md",
        "docs/D005_E5_REPORTING_HARDENING_SPEC.md",
        "docs/D005_E6_FUTURE_BLIND_REPLICATION_SPEC.md",
        "xauusd_signal/strategy.py",
        "xauusd_signal/cli.py",
        "data/canonical/xauusd_ticks_d003-v2/canonical_manifest.json",
        "data/releases/d003-v2/canonical_manifest.json",
        "data/releases/d003-v2/full_verification.json",
        "data/releases/d003-v2/parquet_sha256.txt",
        "data/releases/d003-v2/release_sha256.txt",
        "README.md",
        "docs/D007_OTE_RESEARCH_SPEC.md",
        "research/d007_ote_research/config.py",
        "tests/test_d007_ote_research.py",
    )
    for path in forbidden_during_d006:
        with pytest.raises(ValueError, match="outside D006 ownership"):
            assert_allowed_changed_paths((path,))


def test_spec_records_criterion_level_provenance_without_source_overclaim() -> None:
    spec = Path("docs/D006_REJECTION_BLOCK_RESEARCH_SPEC.md").read_text(encoding="utf-8")
    assert "underlying PDF is documented but absent" not in spec
    assert "absent from current tracked checkout" not in spec
    assert "ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf" in spec
    assert "0cc50fcd129d22d3c68704ffa115cd3b6bc53c93b399c39c55a349d9034e96a0" in spec
    assert "DIRECT_SOURCE_DEFINITION" in spec
    assert "INHERITED_FROZEN_PROJECT_CONVENTION" in spec
    assert "NEW_D006_PREREGISTERED_OPERATIONALIZATION" in spec
    assert "No frozen primary-definition criterion is `UNSUPPORTED`" in spec
    for criterion in (
        "Strict two-bar left swing",
        "Wick/range threshold `0.50`",
        "Candidate true-range/prior-ATR threshold `1.00`",
        "Prior ATR lookback `14`",
        "Minimum prior ATR observations `10`",
        "Expansion within the next `3` closed bars",
        "Expansion body/range threshold `0.60`",
        "Expansion true-range/prior-ATR threshold `1.25`",
        "Expiry at `24` elapsed UTC hours",
        "Proximal, midpoint, and distal geometry set",
    ):
        assert criterion in spec
    assert "No numeric value was changed" in spec
    assert "during\nthis provenance review" in spec
    assert "no re-registration is required" in spec
