from __future__ import annotations

import json
from pathlib import Path


def build_readiness(context: dict, advanced: dict, score: dict) -> dict:
    winner_models = {}
    winner_validation_ok = True
    for tour in ("MEN", "WTA"):
        ctx = (context.get("tours") or {}).get(tour, {})
        validated = ctx.get("status") == "evaluated"
        winner_validation_ok = winner_validation_ok and validated
        gate = (advanced.get("production_gate") or {}).get(tour, {})
        selected = gate.get("selected_candidate") or "accepted_baseline"
        if not gate.get("candidate_beats_baseline", False):
            selected = "accepted_baseline"
        winner_models[tour] = {
            "validated_2026": bool(validated),
            "production_model": selected,
            "advanced_candidate_beats_baseline": bool(gate.get("candidate_beats_baseline", False)),
            "validation_metrics": gate.get("metrics"),
        }

    score_markets = {}
    expected_segments = ("MEN_BO3", "MEN_BO5", "WTA_BO3")
    for segment in expected_segments:
        data = (score.get("segments") or {}).get(segment, {})
        gate = data.get("production_gate") or {}
        score_markets[segment] = {
            "enabled": bool(gate.get("accepted", False)),
            "validation_gate": gate,
            "selected_parameters": data.get("selected_from_2025"),
        }
    full_score = all(score_markets[s]["enabled"] for s in expected_segments)
    return {
        "version": "v5-production-readiness-1",
        "ready_for_main": bool(winner_validation_ok),
        "full_score_market_promotion": bool(full_score),
        "winner_models": winner_models,
        "score_markets": score_markets,
        "policy": {
            "winner_probability": "Use advanced candidate only when it beats accepted baseline on untouched 2026 Brier and log loss without material accuracy degradation; otherwise retain accepted baseline.",
            "score_markets": "Enable each tour/best-of segment only when its independent 2026 score-distribution gate passes. Failed segments remain disabled rather than being force-fit.",
            "market_prices_used_for_tennis_model_fit": False,
        },
    }


def main(base_dir: str | Path = ".") -> int:
    base = Path(base_dir)
    context_path = base / "v5_context_diagnostic" / "report.json"
    advanced_path = base / "v5_advanced_diagnostic" / "report.json"
    score_path = base / "v5_score_diagnostic" / "report.json"
    for path in (context_path, advanced_path, score_path):
        if not path.exists():
            raise FileNotFoundError(str(path))
    readiness = build_readiness(
        json.loads(context_path.read_text(encoding="utf-8")),
        json.loads(advanced_path.read_text(encoding="utf-8")),
        json.loads(score_path.read_text(encoding="utf-8")),
    )
    out = base / "v5_production_candidate"
    out.mkdir(parents=True, exist_ok=True)
    (out / "readiness.json").write_text(json.dumps(readiness, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(readiness, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
