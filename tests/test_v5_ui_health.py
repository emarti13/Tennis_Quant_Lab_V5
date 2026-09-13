from __future__ import annotations

import json


def test_load_model_health_does_not_treat_missing_evidence_as_green(tmp_path):
    from v5_ui_health import load_model_health
    health = load_model_health(tmp_path)
    assert health["winner_models"]["MEN"] == "Unavailable"
    assert health["winner_models"]["WTA"] == "Unavailable"
    assert health["score_models"]["MEN"] == "Unavailable"
    assert health["score_models"]["WTA"] == "Unavailable"
    assert health["full_regression"] == "unknown"
    assert health["streamlit_smoke"] == "unknown"
    assert health["overall"] != "healthy"
    assert health["production_overall"] != "healthy"


def test_load_model_health_reads_production_and_verification_artifacts(tmp_path):
    from v5_ui_health import load_model_health
    acceptance = tmp_path / "experiments" / "acceptance"
    acceptance.mkdir(parents=True)
    (acceptance / "production_candidate.json").write_text(
        json.dumps({"MEN": {"selected_candidate": "ensemble"}, "WTA": {"selected_candidate": "residual"}}), encoding="utf-8"
    )
    (acceptance / "score_production_candidate.json").write_text(
        json.dumps({"MEN": {"selected_candidate": "gaussian_contextual"}, "WTA": {"selected_candidate": "gaussian_contextual"}}), encoding="utf-8"
    )
    (acceptance / "full_regression_status.json").write_text(json.dumps({"status": "success", "expected": "success"}), encoding="utf-8")
    (acceptance / "streamlit_smoke_status.json").write_text(json.dumps({"status": "success", "expected": "success"}), encoding="utf-8")
    (acceptance / "score_acceptance_status.json").write_text(json.dumps({"status": "success", "expected": "success"}), encoding="utf-8")

    health = load_model_health(tmp_path)
    assert health["winner_models"] == {"MEN": "ensemble", "WTA": "residual"}
    assert health["score_models"] == {"MEN": "gaussian_contextual", "WTA": "gaussian_contextual"}
    assert health["full_regression"] == "success"
    assert health["streamlit_smoke"] == "success"
    assert health["score_validation"] == "success"
    assert health["overall"] == "healthy"


def test_production_health_reads_each_canonical_stage_and_requires_all_ready(tmp_path):
    from v5_ui_health import load_model_health

    (tmp_path / "v5_refresh_last.json").write_text(json.dumps({"status": "SUCCESS", "last_successful_utc": "2026-09-12T14:00:00+00:00"}), encoding="utf-8")
    results = tmp_path / "v5_results_ready"
    results.mkdir(parents=True)
    (results / "results_status.json").write_text(json.dumps({"state": "READY", "rows": 100}), encoding="utf-8")
    daily = tmp_path / "v5_daily_ready"
    daily.mkdir(parents=True)
    (daily / "forecast_status.json").write_text(json.dumps({"state": "success", "freshness": "READY"}), encoding="utf-8")
    (daily / "repricing_status.json").write_text(json.dumps({"state": "success", "freshness": "READY"}), encoding="utf-8")
    (daily / "official_settlement_status.json").write_text(json.dumps({"state": "success", "freshness": "READY"}), encoding="utf-8")

    health = load_model_health(tmp_path)
    assert health["production_pipeline"] == {
        "history": "ready",
        "results_cache": "ready",
        "forecast": "ready",
        "repricing": "ready",
        "settlement": "ready",
    }
    assert health["production_overall"] == "healthy"

    (daily / "repricing_status.json").write_text(json.dumps({"state": "blocked", "freshness": "STALE_PRICES"}), encoding="utf-8")
    health = load_model_health(tmp_path)
    assert health["production_pipeline"]["repricing"] == "stale_prices"
    assert health["production_overall"] == "degraded"
