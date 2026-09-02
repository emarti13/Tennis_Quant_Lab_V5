from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any


@dataclass(frozen=True)
class ExperimentConfig:
    experiment_id: str
    git_sha: str
    feature_set_version: str
    model_version: str
    training_window: str
    validation_window: str
    baseline_metrics: dict[str, float]
    candidate_metrics: dict[str, float]
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    random_seeds: list[int] = field(default_factory=list)
    segment_metrics: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: str
    promoted: bool
    reason: str
    record_path: str


def _promotion_decision(config: ExperimentConfig) -> tuple[bool, str]:
    base = config.baseline_metrics
    cand = config.candidate_metrics
    required = ("brier", "log_loss")
    if any(key not in base or key not in cand for key in required):
        return False, "missing required probability metrics"
    brier_gain = float(base["brier"]) - float(cand["brier"])
    log_gain = float(base["log_loss"]) - float(cand["log_loss"])
    base_acc = float(base.get("accuracy", 0.0))
    cand_acc = float(cand.get("accuracy", base_acc))
    accuracy_delta = cand_acc - base_acc
    promoted = brier_gain > 0.0 and log_gain > 0.0 and accuracy_delta >= -0.005
    if promoted:
        return True, f"later-period Brier improved {brier_gain:.6f}, log loss improved {log_gain:.6f}, accuracy delta {accuracy_delta:.6f}"
    return False, f"promotion gate failed: Brier gain {brier_gain:.6f}, log-loss gain {log_gain:.6f}, accuracy delta {accuracy_delta:.6f}"


def run_experiment(config: ExperimentConfig, *, registry_dir: str | Path = "experiments/registry") -> ExperimentResult:
    """Record a chronological experiment and preserve both accepted and rejected results."""
    promoted, reason = _promotion_decision(config)
    out_dir = Path(registry_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {
        **asdict(config),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "promotion_decision": "promote" if promoted else "reject",
        "promotion_reason": reason,
    }
    path = out_dir / f"{config.experiment_id}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    return ExperimentResult(config.experiment_id, promoted, reason, str(path))
