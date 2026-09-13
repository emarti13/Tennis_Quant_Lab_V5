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


def _production_stage(payload: dict[str, Any] | None, *, history: bool = False) -> str:
    if not payload:
        return "unknown"
    if history:
        status = str(payload.get("status") or "").upper()
        if status == "SUCCESS":
            return "ready"
        if status in {"FAILED", "FAILURE", "ERROR"}:
            return "degraded"
        return "unknown"
    freshness = str(payload.get("freshness") or "").strip().lower()
    if freshness:
        return "ready" if freshness == "ready" else freshness
    state = str(payload.get("state") or payload.get("status") or "").strip().lower()
    if state in {"ready", "success"}:
        return "ready"
    if state in {"failed", "failure", "error", "blocked"}:
        return state
    return state or "unknown"


def load_model_health(base_dir: str | Path = ".") -> dict[str, Any]:
    base = Path(base_dir)
    acceptance = base / "experiments" / "acceptance"

    winner_payload = _read_json(acceptance / "production_candidate.json")
    score_payload = _read_json(acceptance / "score_production_candidate.json")
    regression_payload = _read_json(acceptance / "full_regression_status.json")
    smoke_payload = _read_json(acceptance / "streamlit_smoke_status.json")
    score_status_payload = _read_json(acceptance / "score_acceptance_status.json")

    winner_models = {"MEN": _candidate(winner_payload, "MEN"), "WTA": _candidate(winner_payload, "WTA")}
    score_models = {"MEN": _candidate(score_payload, "MEN"), "WTA": _candidate(score_payload, "WTA")}
    full_regression = _artifact_status(regression_payload)
    streamlit_smoke = _artifact_status(smoke_payload)
    score_validation = _artifact_status(score_status_payload)

    candidate_evidence_complete = all(
        value != _UNAVAILABLE
        for value in (winner_models["MEN"], winner_models["WTA"], score_models["MEN"], score_models["WTA"])
    )
    verification_green = all(value == "success" for value in (full_regression, streamlit_smoke, score_validation))
    if candidate_evidence_complete and verification_green:
        overall = "healthy"
    elif any(value in {"failure", "failed", "error", "cancelled"} for value in (full_regression, streamlit_smoke, score_validation)):
        overall = "degraded"
    else:
        overall = "unknown"

    production_payloads = {
        "history": _read_json(base / "v5_refresh_last.json"),
        "results_cache": _read_json(base / "v5_results_ready" / "results_status.json"),
        "forecast": _read_json(base / "v5_daily_ready" / "forecast_status.json"),
        "repricing": _read_json(base / "v5_daily_ready" / "repricing_status.json"),
        "settlement": _read_json(base / "v5_daily_ready" / "official_settlement_status.json"),
    }
    production_pipeline = {
        "history": _production_stage(production_payloads["history"], history=True),
        "results_cache": _production_stage(production_payloads["results_cache"]),
        "forecast": _production_stage(production_payloads["forecast"]),
        "repricing": _production_stage(production_payloads["repricing"]),
        "settlement": _production_stage(production_payloads["settlement"]),
    }
    stage_values = list(production_pipeline.values())
    if stage_values and all(value == "ready" for value in stage_values):
        production_overall = "healthy"
    elif any(value not in {"ready", "unknown"} for value in stage_values):
        production_overall = "degraded"
    else:
        production_overall = "unknown"

    return {
        "overall": overall,
        "production_overall": production_overall,
        "production_pipeline": production_pipeline,
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
            "history": str(base / "v5_refresh_last.json"),
            "results_cache": str(base / "v5_results_ready" / "results_status.json"),
            "forecast": str(base / "v5_daily_ready" / "forecast_status.json"),
            "repricing": str(base / "v5_daily_ready" / "repricing_status.json"),
            "settlement": str(base / "v5_daily_ready" / "official_settlement_status.json"),
        },
    }


def _label(value: Any) -> str:
    text = str(value or "unknown")
    return text.replace("_", " ").title()


def render_model_health_page(st_module, health: dict[str, Any] | None) -> None:
    health = health or {}
    st_module.markdown("## Model Health")
    st_module.caption("Model acceptance and live production stages are read from persisted source-of-truth artifacts.")

    production_overall = str(health.get("production_overall") or "unknown").lower()
    pipeline = health.get("production_pipeline") or {}
    st_module.markdown("### Live production pipeline")
    if production_overall == "degraded":
        st_module.warning("One or more live production stages are degraded. The system preserves last-known-good artifacts and blocks invalid new recommendations.")
    elif production_overall == "unknown":
        st_module.info("Live production health is incomplete because one or more stage artifacts have not been published yet.")
    prod_cols = st_module.columns(5)
    for column, key, label in zip(prod_cols, ("history", "results_cache", "forecast", "repricing", "settlement"), ("History", "Results", "Forecast", "Repricing", "Settlement")):
        column.metric(label, _label(pipeline.get(key)))

    overall = str(health.get("overall") or "unknown").lower()
    if overall == "degraded":
        st_module.warning("One or more model verification checks are degraded.")
    elif overall == "unknown":
        st_module.info("Model acceptance health is unknown because required verification evidence is incomplete.")

    winner = health.get("winner_models") or {}
    score = health.get("score_models") or {}
    st_module.markdown("### Production candidates")
    cols = st_module.columns(4)
    cols[0].metric("MEN winner", str(winner.get("MEN", _UNAVAILABLE)))
    cols[1].metric("WTA winner", str(winner.get("WTA", _UNAVAILABLE)))
    cols[2].metric("MEN score", str(score.get("MEN", _UNAVAILABLE)))
    cols[3].metric("WTA score", str(score.get("WTA", _UNAVAILABLE)))

    st_module.markdown("### Verification")
    verify = st_module.columns(4)
    verify[0].metric("Model acceptance", _label(overall))
    verify[1].metric("Full regression", _label(health.get("full_regression")))
    verify[2].metric("Streamlit smoke", _label(health.get("streamlit_smoke")))
    verify[3].metric("Score validation", _label(health.get("score_validation")))

    artifacts = health.get("artifacts") or {}
    if artifacts:
        with st_module.expander("Evidence paths", expanded=False):
            st_module.json(artifacts)
