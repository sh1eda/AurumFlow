"""Frozen, research-only D007 configuration and registries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path


SPEC_PATH = Path("docs/D007_OTE_RESEARCH_SPEC.md")
SPEC_SHA256 = "adb093f40b0a3a43a6174e81763e3625d38e88ba223f4b392076a240918d364f"

PROVENANCE_CLASSES = (
    "DIRECT_SOURCE_DEFINITION",
    "INHERITED_FROZEN_PROJECT_CONVENTION",
    "NEW_D007_PREREGISTERED_OPERATIONALIZATION",
    "UNSUPPORTED",
)

COMPONENT_DISPOSITIONS = (
    "REPRODUCIBILITY_DEFECT",
    "INSUFFICIENT_EVIDENCE",
    "NON_REDUNDANT_COMPONENT_CANDIDATE",
    "CONDITIONAL_CANDIDATE",
    "GEOMETRY_CANDIDATE",
    "REJECT_COMPONENT",
    "STRUCTURALLY_VALID_EMPIRICALLY_WEAK",
)

FIXED_CONTROLS = (
    "matched_equilibrium_50",
    "upstream_no_ote_touch",
    "matched_context_without_ote",
    "matched_displacement_availability",
    "matched_time_session_volatility",
    "direction_balanced",
)

PROTECTED_TRACKED_SHA256 = (
    ("docs/D003_ACCEPTANCE_REPORT.md", "b2635064c313013e2c191b1cea127a059781de7c042dd4f188778d0a08820eda"),
    ("docs/D004_XAUUSD_0830_0900_MANIPULATION_RESEARCH.md", "e7542c88789801407e67aafefcddf11beb6a55f75d8d71cebc33052b98f21968"),
    ("docs/D005_CONTEXT_ENGINE_TECHNICAL_SPEC.md", "85585f48757cb125fb08591a68853927788f21f9223ec88173d13383bef6233a"),
    ("docs/D005_CONTEXT_ENGINE_RESEARCH_REPORT.md", "d4aeb78a59c2031958ccdb36bde5b55da2253cdb617b57566f20911cb69ea2ff"),
    ("docs/D005_STRATEGY_SOURCE_AUDIT.md", "b9fcbc36efb51ef2a77ef2bfa09dea1df092e007bf18f7d4240d274c0e47fddd"),
    ("docs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY_SPEC.md", "885f967f9038c4fd61ca8222baebead36819b5dd805b802d5b9683e79c57095b"),
    ("docs/D005_E2_REACTION_ANCHOR_DIAGNOSTIC_SPEC.md", "1c68d10a4c7b1b33ef25412fedfdf95bfab8a7fad3587d96a9d0afb29a7ef7c6"),
    ("docs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY_SPEC.md", "b381b26387a47669caf30739b7b04447e214bfa108c0172d4b1cf692564c43d7"),
    ("docs/D005_E4_1H_5M_REVERSAL_REPLICATION_SPEC.md", "704c9e17072fa122ce27e9adcce510543dd265c43201e65fd432e816128d749b"),
    ("docs/D005_E5_REPORTING_HARDENING_SPEC.md", "440dcdb7edb344914a5a0dac43659b96ff48fe48dbee7827521084e93f503a15"),
    ("docs/D005_E6_FUTURE_BLIND_REPLICATION_SPEC.md", "1bba4d33adf8cefca81cd7b2cae1d9b3318494c49adb6de3fa1680928ec840fb"),
    ("docs/D006_REJECTION_BLOCK_RESEARCH_SPEC.md", "c0c16fcc250204c2946c0525f600dc5ba4833163bf193d164175824c77948119"),
    ("research/context_engine/config.py", "3b86421d5292987df8d646b67ab198c4a7c8b0e620837bbe2139f1a69bf3084e"),
    ("research/context_engine/bars.py", "44756989dedd90379b70d0530d847bfc228654bf1a82e38b47b2d0e02bd17761"),
    ("research/context_engine/features.py", "018d3671452b626168d2e83d115a3f35a09491fa7a92c2bb6078ba67062f75e1"),
    ("research/context_engine/models.py", "56e7d189cb3a39e27e553fb946d0acfa9096d3719f384986515e4ecdfd62866b"),
    ("research/context_engine/source_rule_catalog.json", "13e71c4a1cfea76c3124ef9473b8f426abae252421ae9c0c619b673a5b8e3d3e"),
    ("research/event_study_0830_0930/concept_definitions.md", "0f6d813243eb658138419d8f7664209de0b1ef192bca7a3c632f9fd141352176"),
    ("research/event_study_0830_0930/research_gate_assessment.md", "8f1f48970122942554e8d33fc133d12084e06a4456348b7892ee94a65fcbd750"),
    ("research/event_study_0830_0930/strategies.py", "878817202e39958ce47d1110557283a943fca40fb11769d6d076e1ce711a4eec"),
    ("research/event_study_0830_0930/structures.py", "915e75a18c484daac25d2200a773bda688aa7975771695031094ff8abe42ce74"),
    ("research/OTE/README.md", "d8b2ddc5bb7cdf7632ea3b7441886d7bc4b3b4f508e4501c0e4e5078089e2d11"),
    ("research/OTE/object.toml", "4055d4033ebe2105f297aa80e18b3610e74d66b6c36909354e92f2ee8a5453eb"),
    ("xauusd_signal/strategy.py", "ba610b148ec0197a5f6144bdc40ef8ce938f61709ad7c3ee644d19fa077d883e"),
    ("research/d006_rejection_block_research/__init__.py", "10e6ca49761c1b7a382b66740663668a3b3990eae07ed93e6e7b7b95d1ad6231"),
    ("research/d006_rejection_block_research/__main__.py", "5dca239ba9893497c0da4ff77829203ebe00c8d221a9d1371bcf44103bd86cae"),
    ("research/d006_rejection_block_research/config.py", "34803f433266a41f6e3929bd7db174f7593d6cd376ef78a220880adc492efd6e"),
    ("research/d006_rejection_block_research/context.py", "01ae3ea52d04dd14c73de4c5c146efbbe1a7f2ca97cdfb9bab3d0345554a7195"),
    ("research/d006_rejection_block_research/detector.py", "eda11fcb1aae65b145062cb5435ae643c57fbfb75893d261618a4b7d69363202"),
    ("research/d006_rejection_block_research/lifecycle.py", "ea5114ed3d8b976cda51edc28b897dda2d777e6382fe15408d82dbd13fa87f98"),
    ("research/d006_rejection_block_research/models.py", "554dd0f280354a370b688782b250b0def3820a529140a8adb65a1663e7548304"),
    ("research/d006_rejection_block_research/outcomes.py", "9de04e9a35e6e182e205729ad349dccd852c4f89e3621ff1a3e831999247361e"),
    ("research/d006_rejection_block_research/pipeline.py", "7d9bdd446a3104e6e2191574252346f8406397305f1ae7762896c405105b8237"),
    ("research/d006_rejection_block_research/preflight.py", "d60459e8633248cc1cc5e9aaf349af9a83372f27bc73ae47621fec9786bdf85c"),
    ("research/d006_rejection_block_research/reporting.py", "f05c37a071c0fc249f2eb89c1d6190761562c3d8f4a5322a14769199005b3d7f"),
    ("research/d006_rejection_block_research/schemas.py", "7dab75f08b2eb9ce8727cf04299a365966882b23ad463f2dfed75e62b91cfdea"),
    ("research/d006_rejection_block_research/source.py", "7b2a499ae4a99d20b812eef70289524e11c9064c3f61568e7f811c8be44e9d19"),
    ("research/d006_rejection_block_research/statistics.py", "2ad4537a673c0e2fd496f1cc90cf9b2e0ef28521d4abe23a1dd669034e0bf4a3"),
)

FROZEN_DATA_METADATA_SHA256 = (
    ("data/canonical/xauusd_ticks_d003-v2/canonical_manifest.json", "a687c7acd95a6c4533528ab04a96373fc20000b826167ddd51bc57da34a2346d"),
    ("data/releases/d003-v2/canonical_manifest.json", "a687c7acd95a6c4533528ab04a96373fc20000b826167ddd51bc57da34a2346d"),
    ("data/releases/d003-v2/full_verification.json", "fbf0d909d60f9c906911d06aa21b5f125d4a68dbc2d65e444a559d89a1211efe"),
    ("data/releases/d003-v2/parquet_sha256.txt", "f7d941278428a5e7a2f6890a22bf76e9da2af120f419242b5ba817125354173f"),
    ("data/releases/d003-v2/release_sha256.txt", "dac7f92993882f989dc04321d2df969efc383c7924edab5bc9bc9ac41a3266df"),
)

FROZEN_IGNORED_ARTIFACT_COUNT = 242
FROZEN_IGNORED_ARTIFACT_FINGERPRINT = "59e41b2c69a9837dedbcbc3436dfbee815339b7413a3bba54650a7f3ed0e1777"


@dataclass(frozen=True)
class GeometryDefinition:
    """A fixed source-supported retracement geometry, never a search grid."""

    geometry_id: str
    proximal_depth: float
    reference_depth: float
    distal_depth: float
    role: str

    def __post_init__(self) -> None:
        if not 0 < self.proximal_depth <= self.reference_depth <= self.distal_depth < 1:
            raise ValueError("OTE depths must be ordered inside (0, 1)")
        if self.role not in {"primary", "preregistered_sensitivity"}:
            raise ValueError("unknown geometry role")


FIXED_GEOMETRIES = (
    GeometryDefinition("ote_band_62_79", 0.62, 0.705, 0.79, "primary"),
    GeometryDefinition("ote_reference_705", 0.705, 0.705, 0.705, "preregistered_sensitivity"),
)


@dataclass(frozen=True)
class ProvenanceCriterion:
    criterion_id: str
    classification: str
    source: str

    def __post_init__(self) -> None:
        if self.classification not in PROVENANCE_CLASSES:
            raise ValueError("unknown D007 provenance classification")


CRITERION_PROVENANCE = (
    ProvenanceCriterion("ote_concept", "DIRECT_SOURCE_DEFINITION", "ICT 2022 Mentorship PDF pp. 221-227; EKINYZBB BOOTCAMP PDF p. 12"),
    ProvenanceCriterion("ote_band_62_79", "DIRECT_SOURCE_DEFINITION", "ICT 2022 Mentorship PDF p. 222"),
    ProvenanceCriterion("ote_reference_705", "DIRECT_SOURCE_DEFINITION", "ICT 2022 Mentorship PDF p. 222"),
    ProvenanceCriterion("bull_bear_orientation", "DIRECT_SOURCE_DEFINITION", "ICT 2022 Mentorship PDF pp. 224-227; EKINYZBB BOOTCAMP PDF p. 12"),
    ProvenanceCriterion("equilibrium_50", "DIRECT_SOURCE_DEFINITION", "ICT 2022 Mentorship PDF pp. 224, 227"),
    ProvenanceCriterion("closed_five_minute_bars", "INHERITED_FROZEN_PROJECT_CONVENTION", "D005 context-engine closed-bar contract"),
    ProvenanceCriterion("primary_1h_5m_displacement_sequence", "INHERITED_FROZEN_PROJECT_CONVENTION", "D005_E4 frozen 1h_5m displacement sequence"),
    ProvenanceCriterion("confirmed_opposite_swing_origin", "NEW_D007_PREREGISTERED_OPERATIONALIZATION", "D007 primary causal range rule"),
    ProvenanceCriterion("furthest_directional_extreme_endpoint", "NEW_D007_PREREGISTERED_OPERATIONALIZATION", "D007 primary causal range rule through frozen displacement availability"),
    ProvenanceCriterion("no_post_availability_extension", "NEW_D007_PREREGISTERED_OPERATIONALIZATION", "D007 range immutability rule"),
    ProvenanceCriterion("origin_close_invalidation", "NEW_D007_PREREGISTERED_OPERATIONALIZATION", "D007 lifecycle rule"),
    ProvenanceCriterion("expiry_24h", "INHERITED_FROZEN_PROJECT_CONVENTION", "D006 elapsed-UTC lifecycle convention"),
    ProvenanceCriterion("first_touch_precedence", "NEW_D007_PREREGISTERED_OPERATIONALIZATION", "D007 lifecycle rule"),
    ProvenanceCriterion("matching_and_statistics", "INHERITED_FROZEN_PROJECT_CONVENTION", "D005_E4 and D006 registered inference conventions"),
    ProvenanceCriterion("bootstrap_and_control_seed_7007", "NEW_D007_PREREGISTERED_OPERATIONALIZATION", "D007 deterministic seed selected before outcome access"),
)


@dataclass(frozen=True)
class InteractionSpec:
    name: str
    timing: str
    role: str
    minimum_pairs: int


FIXED_INTERACTIONS = (
    InteractionSpec("ote_alone", "first causal band touch", "primary", 500),
    InteractionSpec("aligned_d005_context", "context available no later than range availability", "confirmatory", 200),
    InteractionSpec("after_d004_manipulation", "causal state complete before range availability", "exploratory", 100),
    InteractionSpec("frozen_liquidity_sweep", "available and valid at range availability", "confirmatory", 200),
    InteractionSpec("refinement_confirmation", "available no later than first touch", "confirmatory", 200),
    InteractionSpec("d006_rejection_block", "available no later than first touch", "exploratory_descriptive", 100),
    InteractionSpec("against_d005_context_negative_control", "opposed context available by range availability", "negative_control", 200),
)


@dataclass(frozen=True)
class MultipleTestingFamily:
    name: str
    hypotheses: int
    adjustment: str
    q: float = 0.05


FIXED_MULTIPLE_TESTING = (
    MultipleTestingFamily("primary", 1, "unadjusted"),
    MultipleTestingFamily("interactions", 6, "BH"),
    MultipleTestingFamily("incremental_controls", 2, "BH"),
    MultipleTestingFamily("geometry", 3, "BH"),
)


@dataclass(frozen=True)
class D007Config:
    """All D007 values are fixed before historical OTE outcome access."""

    version: str = "d007-v1"
    research_only: bool = True
    production_authorized: bool = False
    historical_execution_authorized: bool = False
    outcome_authorized: bool = False
    output_authorized: bool = False
    timeframe: str = "5min"
    bar_minutes: int = 5
    upstream_mapping: str = "1h_5m"
    upstream_event_type: str = "displacement_confirmation"
    validation_years: tuple[int, ...] = (2022, 2023, 2024, 2025)
    forbidden_years: tuple[int, ...] = (2026,)
    geometries: tuple[GeometryDefinition, ...] = FIXED_GEOMETRIES
    lifecycle_expiry_hours: int = 24
    primary_horizon_minutes: int = 60
    endpoint_reference: str = "first_touch_bar_close"
    confidence_level: float = 0.95
    bootstrap_resamples: int = 2000
    bootstrap_seed: int = 7007
    fdr_q: float = 0.05
    control_window_days: int = 30
    control_exclusion_minutes: int = 120
    control_seed: int = 7007
    matching_variables: tuple[str, ...] = (
        "validation_year",
        "d005_session",
        "direction",
        "causal_volatility_bucket",
        "upstream_mapping",
        "elapsed_to_event_bucket",
    )
    minimum_constructed_ranges: int = 1000
    minimum_lifecycle_eligible: int = 800
    minimum_first_touches: int = 500
    minimum_untouched_controls: int = 200
    minimum_primary_pairs: int = 500
    minimum_pairs_per_year: int = 100
    minimum_per_direction: int = 200
    minimum_per_required_session: int = 50
    minimum_confirmatory_interaction_pairs: int = 200
    minimum_geometry_cohort: int = 200
    endpoint_coverage_required: float = 1.0
    required_sessions: tuple[str, ...] = (
        "asia",
        "premarket",
        "ny_observation",
        "ny_afternoon",
    )
    provenance: tuple[ProvenanceCriterion, ...] = CRITERION_PROVENANCE
    interactions: tuple[InteractionSpec, ...] = FIXED_INTERACTIONS
    multiple_testing: tuple[MultipleTestingFamily, ...] = FIXED_MULTIPLE_TESTING
    dispositions: tuple[str, ...] = COMPONENT_DISPOSITIONS
    controls: tuple[str, ...] = FIXED_CONTROLS
    protected_tracked_sha256: tuple[tuple[str, str], ...] = PROTECTED_TRACKED_SHA256
    frozen_data_metadata_sha256: tuple[tuple[str, str], ...] = FROZEN_DATA_METADATA_SHA256
    frozen_ignored_artifact_count: int = FROZEN_IGNORED_ARTIFACT_COUNT
    frozen_ignored_artifact_fingerprint: str = FROZEN_IGNORED_ARTIFACT_FINGERPRINT

    def __post_init__(self) -> None:
        if self.version != "d007-v1":
            raise ValueError("D007 version is fixed")
        if not self.research_only or any(
            (
                self.production_authorized,
                self.historical_execution_authorized,
                self.outcome_authorized,
                self.output_authorized,
            )
        ):
            raise ValueError("D007 preflight has no production, history, outcome, or output authority")
        if (self.timeframe, self.bar_minutes, self.upstream_mapping) != ("5min", 5, "1h_5m"):
            raise ValueError("D007 primary upstream construction is fixed")
        if self.upstream_event_type != "displacement_confirmation":
            raise ValueError("D007 upstream event type is fixed")
        if self.validation_years != (2022, 2023, 2024, 2025) or self.forbidden_years != (2026,):
            raise ValueError("D007 validation years are fixed and exclude outcome-known 2026")
        if self.geometries != FIXED_GEOMETRIES:
            raise ValueError("D007 geometry family is fixed without a grid")
        if (
            self.lifecycle_expiry_hours,
            self.primary_horizon_minutes,
            self.endpoint_reference,
            self.confidence_level,
            self.bootstrap_resamples,
            self.bootstrap_seed,
            self.fdr_q,
            self.control_window_days,
            self.control_exclusion_minutes,
            self.control_seed,
        ) != (24, 60, "first_touch_bar_close", 0.95, 2000, 7007, 0.05, 30, 120, 7007):
            raise ValueError("D007 lifecycle, endpoint, inference, and control values are fixed")
        if self.matching_variables != (
            "validation_year",
            "d005_session",
            "direction",
            "causal_volatility_bucket",
            "upstream_mapping",
            "elapsed_to_event_bucket",
        ):
            raise ValueError("D007 matching variables are fixed")
        if (
            self.minimum_constructed_ranges,
            self.minimum_lifecycle_eligible,
            self.minimum_first_touches,
            self.minimum_untouched_controls,
            self.minimum_primary_pairs,
            self.minimum_pairs_per_year,
            self.minimum_per_direction,
            self.minimum_per_required_session,
            self.minimum_confirmatory_interaction_pairs,
            self.minimum_geometry_cohort,
            self.endpoint_coverage_required,
        ) != (1000, 800, 500, 200, 500, 100, 200, 50, 200, 200, 1.0):
            raise ValueError("D007 adequacy thresholds are fixed")
        if self.required_sessions != (
            "asia",
            "premarket",
            "ny_observation",
            "ny_afternoon",
        ):
            raise ValueError("D007 required sessions are fixed")
        if any(item.classification == "UNSUPPORTED" for item in self.provenance):
            raise ValueError("unsupported provenance fails closed")
        if (
            self.provenance != CRITERION_PROVENANCE
            or self.interactions != FIXED_INTERACTIONS
            or self.multiple_testing != FIXED_MULTIPLE_TESTING
        ):
            raise ValueError("D007 provenance and interaction registries are fixed")
        if self.dispositions != COMPONENT_DISPOSITIONS:
            raise ValueError("D007 disposition hierarchy is fixed")
        if self.controls != FIXED_CONTROLS:
            raise ValueError("D007 control family is fixed")
        if self.protected_tracked_sha256 != PROTECTED_TRACKED_SHA256:
            raise ValueError("D007 protected tracked hashes are fixed")
        if self.frozen_data_metadata_sha256 != FROZEN_DATA_METADATA_SHA256:
            raise ValueError("D007 protected data-metadata hashes are fixed")
        if (
            self.frozen_ignored_artifact_count,
            self.frozen_ignored_artifact_fingerprint,
        ) != (
            FROZEN_IGNORED_ARTIFACT_COUNT,
            FROZEN_IGNORED_ARTIFACT_FINGERPRINT,
        ):
            raise ValueError("D007 ignored-artifact aggregate is fixed")

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self)
        payload["spec_path"] = str(SPEC_PATH)
        return payload


def config_fingerprint(config: D007Config = D007Config()) -> str:
    encoded = json.dumps(
        config.snapshot(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
