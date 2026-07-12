from pathlib import Path

from xauusd_signal.backtest import BacktestResult, Trade
from xauusd_signal.models import ModelAdapter, ModelManifest, feature_hash
from xauusd_signal.paper import PaperLedger, place_real_order
from xauusd_signal.types import Decision, MLDirection, OperatingMode, Signal, ValidationStatus
from xauusd_signal.validation import evaluate_hybrid_validated_gate


def trades(count, r):
    return [
        Trade(Decision.BUY, 0, 1, 2, 10, 12, 9, 12, r, "target")
        for _ in range(count)
    ]


def test_hybrid_gate_insufficient_evidence_before_trade_threshold():
    report = evaluate_hybrid_validated_gate(
        BacktestResult(trades=trades(100, 0.1)),
        BacktestResult(trades=trades(99, 0.5)),
        fold_count=5,
    )
    assert report.status == ValidationStatus.INSUFFICIENT_EVIDENCE


def test_hybrid_gate_rejects_when_primary_expectancy_worsens():
    report = evaluate_hybrid_validated_gate(
        BacktestResult(trades=trades(100, 0.3)),
        BacktestResult(trades=trades(100, 0.2)),
        fold_count=5,
    )
    assert report.status == ValidationStatus.REJECTED


def test_feature_hash_is_stable_by_manifest_order():
    values = {"b": 2, "a": 1}
    assert feature_hash(values, ["a", "b"]) == feature_hash({"a": 1, "b": 2}, ["a", "b"])


def test_missing_model_artifact_returns_unavailable(tmp_path):
    manifest = ModelManifest(
        model_path=tmp_path / "missing.pkl",
        model_version="test",
        feature_names=["a"],
        target_horizon=5,
        class_semantics={"1": "UP_HORIZON", "0": "NOT_UP_HORIZON"},
        calibration_status="uncalibrated",
        preprocessing={},
        training_window="unknown",
    )
    prediction = ModelAdapter(manifest).predict({"a": 1.0})
    assert prediction.direction == MLDirection.UNAVAILABLE


def test_model_feature_mismatch_returns_unavailable(tmp_path):
    manifest = ModelManifest(
        model_path=tmp_path / "missing.pkl",
        model_version="test",
        feature_names=["a", "b"],
        target_horizon=5,
        class_semantics={"1": "UP_HORIZON", "0": "NOT_UP_HORIZON"},
        calibration_status="uncalibrated",
        preprocessing={},
        training_window="unknown",
    )
    prediction = ModelAdapter(manifest).predict({"a": 1.0})
    assert prediction.raw_prediction == "model_feature_mismatch"


def test_missing_predict_proba_returns_unavailable(tmp_path):
    model_path = tmp_path / "model.pkl"
    model_path.write_text("placeholder")
    manifest = ModelManifest(
        model_path=model_path,
        model_version="test",
        feature_names=["a"],
        target_horizon=5,
        class_semantics={"1": "UP_HORIZON", "0": "NOT_UP_HORIZON"},
        calibration_status="uncalibrated",
        preprocessing={},
        training_window="unknown",
    )
    prediction = ModelAdapter(manifest, object()).predict({"a": 1.0})
    assert prediction.raw_prediction == "model_probability_unavailable"


def test_ambiguous_model_class_mapping_returns_unavailable(tmp_path):
    class ReversedClassesModel:
        classes_ = [1, 0]

        def predict_proba(self, values):
            return [[0.2, 0.8]]

    model_path = tmp_path / "model.pkl"
    model_path.write_text("placeholder")
    manifest = ModelManifest(
        model_path=model_path,
        model_version="test",
        feature_names=["a"],
        target_horizon=5,
        class_semantics={"1": "UP_HORIZON", "0": "NOT_UP_HORIZON"},
        calibration_status="uncalibrated",
        preprocessing={},
        training_window="unknown",
    )
    prediction = ModelAdapter(manifest, ReversedClassesModel()).predict({"a": 1.0})
    assert prediction.raw_prediction == "model_class_mapping_ambiguous"


def test_valid_injected_model_prediction_uses_manifest_feature_order(tmp_path):
    class ValidModel:
        classes_ = [0, 1]

        def predict_proba(self, values):
            assert values == [[1.0, 2.0]]
            return [[0.25, 0.75]]

    model_path = tmp_path / "model.pkl"
    model_path.write_text("placeholder")
    manifest = ModelManifest(
        model_path=model_path,
        model_version="test",
        feature_names=["a", "b"],
        target_horizon=5,
        class_semantics={"1": "UP_HORIZON", "0": "NOT_UP_HORIZON"},
        calibration_status="uncalibrated",
        preprocessing={},
        training_window="unknown",
    )
    prediction = ModelAdapter(manifest, ValidModel()).predict({"b": 2.0, "a": 1.0})
    assert prediction.direction == MLDirection.UP_HORIZON
    assert prediction.confidence == 0.75
    assert prediction.model_version == "test"


def test_paper_ledger_records_signal_and_real_order_is_blocked(tmp_path):
    ledger = PaperLedger(tmp_path / "ledger.jsonl")
    signal = Signal(decision=Decision.NO_TRADE, operating_mode=OperatingMode.RULE_ONLY, timestamp="t")
    ledger.record_signal(signal)
    assert ledger.read_events()[0]["payload"]["decision"] == "NO_TRADE"
    try:
        place_real_order()
    except RuntimeError as exc:
        assert "Real-money execution" in str(exc)
    else:
        raise AssertionError("real order function did not fail")
