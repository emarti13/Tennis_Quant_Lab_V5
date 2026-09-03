from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_UNAVAILABLE = "Unavailable"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _candidate(payload: dict[str, Any] | None, tour: str) -> str:
    if not payload:
        return _UNAVAILABLE
    value = payload.get(tour)
    if isinstance(value, dict):
        selected = value.get("selected_candidate")
        if selected not in (None, ""):
            return str(selected)
    return _UNAVAILABLE


def _artifact_status(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "unknown"
    status = str(payload.get("status") or "unknown").lower()
    expected = str(payload.get("expected") or "success").lower()
    if status == expected:
        return "success"
    if status in {"failure", "failed", "error", "cancelled", "skipped"}:
        return status
    return status or "unknown"


def load_model_health(base_dir: str | Path = ".") -> dict[str, Any]:
    base = Path(base_dir)
    acceptance = base / "experiments" / "acceptance"

    winner_payload = _read_json(acceptance / "production_candidate.json")
    score_payload = _read_json(acceptance / "score_production_candidate.json")
    regression_payload = _read_json(acceptance / "full_regression_status.json")
    smoke_payload = _read_json(acceptance / "streamlit_smoke_status.json")
    score_status_payload = _read_json(acceptance / "score_acceptance_status.json")

    winner_models = {
        "MEN": _candidate(winner_payload, "MEN"),
        "WTA": _candidate(winner_payload, "WTA"),
    }
    score_models = {
        "MEN": _candidate(score_payload, "MEN"),
        "WTA": _candidate(score_payload, "WTA"),
    }

    full_regression = _artifact_status(regression_payload)
    streamlit_smoke = _artifact_status(smoke_payload)
    score_validation = _artifact_status(score_status_payload)

    candidate_evidence_complete = all(
        value != _UNAVAILABLE
        for value in (
            winner_models["MEN"],
            winner_models["WTA"],
            score_models["MEN"],
            score_models["WTA"],
        )
    )
    verification_green = all(
        value == "success"
        for value in (full_regression, streamlit_smoke, score_validation)
    )

    if candidate_evidence_complete and verification_green:
        overall = "healthy"
    elif any(
        value in {"failure", "failed", "error", "cancelled"}
        for value in (full_regression, streamlit_smoke, score_validation)
    ):
        overall = "degraded"
    else:
        overall = "unknown"

    return {
        "overall": overall,
        "winner_models": winner_models,
        "score_models": score_models,
        "full_regression": full_regression,
        "streamlit_smoke": streamlit_smoke,
        "score_validation": score_validation,
        "artifacts": {
            "winner_candidate": str(acceptance / "production_candidate.json"),
            "score_candidate": str(acceptance / "score_production_candidate.json"),
            "full_regression": str(acceptance / "full_regression_status.json"),
            "streamlit_smoke": str(acceptance / "streamlit_smoke_status.json"),
            "score_validation": str(acceptance / "score_acceptance_status.json"),
        },
    }
