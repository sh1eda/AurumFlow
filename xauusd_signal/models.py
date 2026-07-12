from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import MLDirection, ModelPrediction


@dataclass(frozen=True)
class ModelManifest:
    model_path: Path
    model_version: str
    feature_names: list[str]
    target_horizon: int
    class_semantics: dict[str, str]
    calibration_status: str
    preprocessing: dict[str, Any]
    training_window: str
    validation_report_path: Path | None = None


def feature_hash(feature_values: dict[str, Any], feature_names: list[str]) -> str:
    ordered = {name: feature_values[name] for name in feature_names}
    payload = json.dumps(ordered, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ModelAdapter:
    def __init__(self, manifest: ModelManifest, model: Any | None = None):
        self.manifest = manifest
        self.model = model

    def predict(self, feature_values: dict[str, Any], feature_timestamp: str = "") -> ModelPrediction:
        missing = [name for name in self.manifest.feature_names if name not in feature_values]
        if missing:
            return ModelPrediction.unavailable("model_feature_mismatch")
        if self.model is None or not self.manifest.model_path.exists():
            return ModelPrediction.unavailable("model_unavailable")
        if not hasattr(self.model, "predict_proba"):
            return ModelPrediction.unavailable("model_probability_unavailable")
        if self.manifest.class_semantics.get("0") != "NOT_UP_HORIZON":
            return ModelPrediction.unavailable("model_class_mapping_ambiguous")
        if self.manifest.class_semantics.get("1") != "UP_HORIZON":
            return ModelPrediction.unavailable("model_class_mapping_ambiguous")
        classes = list(getattr(self.model, "classes_", []))
        if classes != [0, 1]:
            return ModelPrediction.unavailable("model_class_mapping_ambiguous")
        values = [[feature_values[name] for name in self.manifest.feature_names]]
        probabilities_raw = self.model.predict_proba(values)[0]
        probabilities = {"0": float(probabilities_raw[0]), "1": float(probabilities_raw[1])}
        direction = MLDirection.UP_HORIZON if probabilities["1"] >= probabilities["0"] else MLDirection.NOT_UP_HORIZON
        return ModelPrediction(
            direction=direction,
            confidence=max(probabilities.values()),
            raw_prediction=1 if direction == MLDirection.UP_HORIZON else 0,
            probabilities=probabilities,
            model_version=self.manifest.model_version,
            feature_timestamp=feature_timestamp,
            feature_hash=feature_hash(feature_values, self.manifest.feature_names),
        )
