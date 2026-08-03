"""Frozen, outcome-disabled configuration for D005_E6."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Final


E4_START: Final = "2026-01-01T00:00:00Z"
E4_END_EXCLUSIVE: Final = "2026-07-29T00:00:00Z"
PROPOSED_START: Final = "2027-01-01T00:00:00Z"
PROPOSED_END_EXCLUSIVE: Final = "2033-01-01T00:00:00Z"
ENDPOINT_BUFFER_HOURS: Final = 24
EARLIEST_PROPOSED_EXECUTION: Final = "2033-01-02T00:00:00Z"
SPEC_PATH: Final = "docs/D005_E6_FUTURE_BLIND_REPLICATION_SPEC.md"
SPEC_SHA256: Final = "1bba4d33adf8cefca81cd7b2cae1d9b3318494c49adb6de3fa1680928ec840fb"


FROZEN_TRACKED_SHA256: Final = {
    "docs/D005_E4_1H_5M_REVERSAL_REPLICATION_SPEC.md": "704c9e17072fa122ce27e9adcce510543dd265c43201e65fd432e816128d749b",
    "docs/D005_E4_2026_INDEPENDENT_REPLICATION_SPEC.md": "0cb5e4b4f55a63b4dac1591f1a8fe205ece9fde14cc871e318984fb87245ef03",
    "docs/D005_E5_REPORTING_HARDENING_SPEC.md": "440dcdb7edb344914a5a0dac43659b96ff48fe48dbee7827521084e93f503a15",
    "research/context_engine/bars.py": "44756989dedd90379b70d0530d847bfc228654bf1a82e38b47b2d0e02bd17761",
    "research/context_engine/config.py": "3b86421d5292987df8d646b67ab198c4a7c8b0e620837bbe2139f1a69bf3084e",
    "research/context_engine/engine.py": "e8e4f6a947af5446d16680ed985b74ce33dd754649953dfccb9deae1ae88613d",
    "research/context_engine/features.py": "018d3671452b626168d2e83d115a3f35a09491fa7a92c2bb6078ba67062f75e1",
    "research/context_engine/models.py": "56e7d189cb3a39e27e553fb946d0acfa9096d3719f384986515e4ecdfd62866b",
    "research/d005_e1_context_engine_empirical/config.py": "ce97b6ff9be41070ef7ad9d12346448a8bb9845770c10dafe38caca05479e088",
    "research/d005_e1_context_engine_empirical/pmh.py": "0f251e4108cd8f712d2a6a19060066b30a66d3877d9cc8fc0608850b07942443",
    "research/d005_e1_context_engine_empirical/schedule.py": "623a47b95a82a9b62a3283d8cf7f840902a242dc943ef00513c4daddf5d13a31",
    "research/d005_e2_reaction_anchor_diagnostic/config.py": "f767cc5ff99565af574b43e460388d9e918604e2deedcd61d05968a9ec5f45b6",
    "research/d005_e2_reaction_anchor_diagnostic/directions.py": "8f503b98952be68827aa234a2a5d9d7b6f33388a3363bf01b4ef4c58d3d54e8c",
    "research/d005_e2_reaction_anchor_diagnostic/reconstruction.py": "f5045a7de48bdcd2e381e8185de0135466e1d21a1c6f61f705784dbf905e9b7c",
    "research/d005_e3_early_context_anchor_study/anchors.py": "c6332aa949300171f44cfcd9a5d2b5afee24aef30529721c3d3e137c6d1ebc15",
    "research/d005_e3_early_context_anchor_study/outcomes.py": "ad293dfce3cfc325f9c6e925c34f18b2ab50ff585bcf88af2604ca9f7fc482a0",
    "research/d005_e4_1h_5m_reversal_replication/analysis.py": "f616312bd269840cab7b8ccea181992650c9a975a8d2d00ac1bc4a80a247ed15",
    "research/d005_e4_1h_5m_reversal_replication/config.py": "706755af2947fc9ec3d9cb06ffa179b38970b9c883ed9974dd15520699b8d833",
    "research/d005_e4_1h_5m_reversal_replication/pipeline.py": "a94dd4975933302b94f7a0cb5b8ae12ab46bce4b4d9dd4ea653d87b835a220a8",
    "research/d005_e4_1h_5m_reversal_replication/reporting.py": "dbd8ec98261c478662d4f7d963bf69359fbb3536934bdb05cac1c5a95108a007",
    "research/d005_e4_1h_5m_reversal_replication/selection.py": "6db53eb793874825f224bc2b0f9bce411b6474e94b320590d958865e63feddf4",
    "research/d005_e4_2026_independent_replication/__init__.py": "c15245cdc9ca3f2b9a825510c9998ba6bac1c487bc0fe1621076d6ae3d80f702",
    "research/d005_e4_2026_independent_replication/__main__.py": "9db149a6ab42290a8e2e9f5e94b80136ad5c64c33b3330e3359ad9114b86dcb8",
    "research/d005_e4_2026_independent_replication/anchor_inputs.py": "cd278987f0e8f5f00de10177a2877c3fd930d1c3d645f53a52b0c28262aaa8d7",
    "research/d005_e4_2026_independent_replication/cli.py": "b06cf5f6ffc7a4749cb6454375d12b4fc67cb83b19726da16a44e58d21d18cc3",
    "research/d005_e4_2026_independent_replication/config.py": "713c8a99e4cf87c25f3a0c39b0ddd9e1d083824182780990fbe1c38e0cc7c3d0",
    "research/d005_e4_2026_independent_replication/frozen_structural_loader.py": "abadd72410dc3db16ef7069361470783ef014089a378c458f6819776d3ecc9c5",
    "research/d005_e4_2026_independent_replication/preflight.py": "23563f32e34797ec5995fafa1a526e119045b6f71868fa265b8691a276639da5",
    "research/d005_e5_reporting_hardening/__init__.py": "78b321fe4e929b506b9dd1ed36e980e32606c541a32a098bbee163c888d40f73",
    "research/d005_e5_reporting_hardening/__main__.py": "78aca8512114193fc00d41c9820cc852928c0eb9a5033c9030e4052144a2f1c0",
    "research/d005_e5_reporting_hardening/review.py": "a16f57f1b2bc6fbbb7e83d10602f78ccbac7865c2840e48edc3b5e5faf271ba3",
    "research/manipulation_0830_0900/bars.py": "f094017b6b0571fd9861491f61ac613cb895a8f0a068b8670ddd06c003728101",
    "scripts/build_dukascopy_canonical.py": "0757ad89962f750997ad64f1344759f9b97bb7d0ac88fd8835eb7ad31fa4dba8",
    "scripts/validate_canonical_dataset.py": "f2ef81f4cda78675736b8ae6886b81b2dec012ea1e3eafd5b73aee31c6ff29af",
    "tests/test_d005_e4_1h_5m_reversal_replication.py": "b0ea206ad23bc1c0d441dffa2f80ea19e4af4b9e9e0a1441b73afa9a63c3e300",
    "tests/test_d005_e4_2026_independent_replication.py": "f49564b15c2dc377851b53cc88d5f655c1955ee1a412b306d500075d025dbd2b",
    "tests/test_d005_e5_reporting_hardening.py": "54e732206860053b9ce562c6eabe94305d10e218ed81c302bb556f951dbd3d80",
}

FROZEN_AGGREGATE_MANIFEST_SHA256: Final = {
    "research_outputs/D005_E4_2026_INDEPENDENT_REPLICATION/artifact_manifest.json": "30a42d32f8f4551f146c498f13d224fa5fee66454e0aa9bd320619abc9bf9876",
    "research_outputs/D005_E5_REPORTING_HARDENING/artifact_manifest.json": "5b96c3611070c02bf7b1e26868adb77dda385f3303e9c674540b2f1eb1a1b566",
}


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo != timezone.utc:
        raise ValueError("timestamp must be explicit UTC")
    return parsed


@dataclass(frozen=True)
class FixedIntervalPolicy:
    """A proposed fixed calendar policy; registration is fail-closed."""

    anchor_start: str = PROPOSED_START
    anchor_end_exclusive: str = PROPOSED_END_EXCLUSIVE
    endpoint_buffer_hours: int = ENDPOINT_BUFFER_HOURS
    earliest_execution: str = EARLIEST_PROPOSED_EXECUTION
    policy_kind: str = "FIXED_CALENDAR_INTERVAL"
    registration_status: str = "PROPOSED_UNREGISTERED"

    def validate(self) -> None:
        start = parse_utc(self.anchor_start)
        end = parse_utc(self.anchor_end_exclusive)
        execution = parse_utc(self.earliest_execution)
        if self.policy_kind != "FIXED_CALENDAR_INTERVAL":
            raise ValueError("E6 permits only the fixed calendar policy")
        if (start, end) != (parse_utc(PROPOSED_START), parse_utc(PROPOSED_END_EXCLUSIVE)):
            raise ValueError("the proposed E6 interval is immutable")
        if self.endpoint_buffer_hours != ENDPOINT_BUFFER_HOURS:
            raise ValueError("the endpoint buffer is immutable")
        if execution != end + timedelta(hours=self.endpoint_buffer_hours):
            raise ValueError("earliest execution must follow the complete endpoint buffer")
        if self.registration_status != "PROPOSED_UNREGISTERED":
            raise ValueError("E6 cannot register an interval while the blind boundary is unproven")


@dataclass(frozen=True)
class E6ReadinessConfig:
    """Scientific constants and permanent authorization blocks."""

    study_id: str = "D005_E6_FUTURE_BLIND_REPLICATION"
    version: str = "D005-E6-readiness-v1"
    primary_mapping: str = "1h_5m"
    primary_outcome_label: str = "reversal"
    primary_anchor: str = "displacement_confirmation"
    primary_horizon_minutes: int = 60
    minimum_total_primary: int = 1000
    minimum_bearish: int = 200
    minimum_bullish: int = 200
    complete_endpoint_coverage_required: bool = True
    blind_boundary_proven: bool = False
    interval_registered: bool = False
    primary_decision_rule_registered: bool = True
    scientific_execution_authorized: bool = False
    production_integration_authorized: bool = False
    output_writes_authorized: bool = False
    policy: FixedIntervalPolicy = field(default_factory=FixedIntervalPolicy)
    production_recommendation: str = "continue research only"

    def validate(self) -> None:
        self.policy.validate()
        if (self.primary_mapping, self.primary_outcome_label, self.primary_anchor) != (
            "1h_5m",
            "reversal",
            "displacement_confirmation",
        ):
            raise ValueError("the frozen primary claim cannot change")
        if self.primary_horizon_minutes != 60:
            raise ValueError("the frozen primary horizon is 60 minutes")
        if (self.minimum_total_primary, self.minimum_bearish, self.minimum_bullish) != (
            1000,
            200,
            200,
        ):
            raise ValueError("historical adequacy thresholds cannot change")
        if not self.complete_endpoint_coverage_required:
            raise ValueError("complete endpoint coverage is mandatory")
        if any(
            (
                self.blind_boundary_proven,
                self.interval_registered,
                self.scientific_execution_authorized,
                self.production_integration_authorized,
                self.output_writes_authorized,
            )
        ):
            raise ValueError("E6 planning cannot authorize registration, outcomes, output, or production")
        if not self.primary_decision_rule_registered:
            raise ValueError("the frozen non-temporal primary pass/fail rule is required")
        if self.production_recommendation != "continue research only":
            raise ValueError("production recommendation is frozen")

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self)
        payload["specification"] = {"path": SPEC_PATH, "sha256": SPEC_SHA256}
        payload["known_non_blind_interval"] = {
            "start": E4_START,
            "end_exclusive": E4_END_EXCLUSIVE,
        }
        payload["latest_exact_outcome_timestamp"] = "UNPROVEN"
        payload["earliest_proven_blind_start"] = "UNPROVEN"
        payload["protected_tracked_sha256"] = dict(sorted(FROZEN_TRACKED_SHA256.items()))
        payload["protected_aggregate_manifest_sha256"] = dict(
            sorted(FROZEN_AGGREGATE_MANIFEST_SHA256.items())
        )
        return payload

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.snapshot(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
