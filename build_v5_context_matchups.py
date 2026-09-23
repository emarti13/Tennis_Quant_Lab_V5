from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from v5_context_model import orient_matchup_row
from v5_model_calibration import calibrated_match_probability
from v5_player_state import add_trajectory_features, build_player_state
from v5_rolling_stats import build_rolling_stats
from v5_settlement import canonical_name
from v5_travel_features import build_travel_features
from v5_workload_features import build_workload_features


def _clip_probability(value: float) -> float:
    return min(max(float(value), 1e-8), 1.0 - 1e-8)


def _logit(value: float) -> float:
    p = _clip_probability(value)
    return math.log(p / (1.0 - p))


def enrich_player_history(player_rows: pd.DataFrame, tournament_registry: pd.DataFrame | None = None) -> pd.DataFrame:
    if player_rows is None or player_rows.empty:
        return player_rows.copy() if player_rows is not None else pd.DataFrame()
    enriched = build_rolling_stats(player_rows)
    enriched = build_workload_features(enriched)
    enriched = add_trajectory_features(enriched)
    if tournament_registry is not None and not tournament_registry.empty:
        enriched = build_travel_features(enriched, tournament_registry)
    return enriched


def _winner_loser_columns(frame: pd.DataFrame) -> tuple[str, str]:
    winner = "winner" if "winner" in frame.columns else "winner_name"
    loser = "loser" if "loser" in frame.columns else "loser_name"
    if winner not in frame.columns or loser not in frame.columns:
        raise ValueError("Walk-forward data requires winner/loser names")
    return winner, loser


def _normalize_calendar_date(value) -> pd.Timestamp:
    if pd.isna(value):
        return pd.NaT
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is not None:
        parsed = parsed.tz_localize(None)
    return parsed.normalize()


def _parse_walkforward_date(value) -> pd.Timestamp:
    if pd.isna(value):
        return pd.NaT
    text = str(value).strip()
    if re.fullmatch(r"\d{8}(?:\.0+)?", text):
        text = text.split(".", 1)[0]
        parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    else:
        parsed = pd.to_datetime(value, errors="coerce")
    return pd.NaT if pd.isna(parsed) else _normalize_calendar_date(parsed)


def _prepare_walkforward(walkforward: pd.DataFrame, target_years: tuple[int, ...]) -> pd.DataFrame:
    wf = walkforward.copy()
    winner_col, loser_col = _winner_loser_columns(wf)
    if "date" not in wf.columns:
        raise ValueError("Walk-forward data requires date")
    if "tour" not in wf.columns:
        raise ValueError("Walk-forward data requires tour")
    wf["_date"] = wf["date"].map(_parse_walkforward_date)
    wf["_year"] = wf["_date"].dt.year
    wf["_winner_key"] = wf[winner_col].map(canonical_name)
    wf["_loser_key"] = wf[loser_col].map(canonical_name)
    wf["_tour_key"] = wf["tour"].astype(str).str.upper().replace({"ATP": "MEN"})
    wf["_key"] = list(zip(wf["_date"], wf["_tour_key"], wf["_winner_key"], wf["_loser_key"]))
    return wf[wf["_year"].isin([int(y) for y in target_years])].copy()


def _shared_context(row: pd.Series) -> dict[str, float]:
    def pick(*names):
        for name in names:
            if name in row.index and pd.notna(row.get(name)):
                return row.get(name)
        return np.nan
    return {
        # Retired court characteristics are deliberately neutral here.
        # New authority features are evaluated in their own challenger and are
        # not silently substituted into the accepted production model.
        "court_speed": np.nan,
        "altitude_m": np.nan,
        "weather_temperature_c": pick("weather_temperature_c"),
        "weather_humidity_pct": pick("weather_humidity_pct"),
        "weather_wind_speed_kmh": pick("weather_wind_speed_kmh"),
        "weather_wind_gust_kmh": pick("weather_wind_gust_kmh"),
    }


def assemble_matchup_dataset(enriched_player_rows: pd.DataFrame, walkforward: pd.DataFrame, *, target_years: Iterable[int] = (2025, 2026)) -> tuple[pd.DataFrame, dict[str, int]]:
    years = tuple(int(y) for y in target_years)
    rows = enriched_player_rows.copy()
    rows["match_date"] = rows["match_date"].map(_normalize_calendar_date)
    target_rows = rows[rows["match_date"].dt.year.isin(years)].copy()
    wf = _prepare_walkforward(walkforward, years)
    wf_groups = {key: group for key, group in wf.groupby("_key", sort=False)}
    used_wf_indices: set[int] = set()
    output: list[dict] = []
    invalid = unmatched = ambiguous = missing_baseline = 0

    for match_id, group in target_rows.groupby("match_id", sort=False):
        if len(group) != 2 or set(group["player_role"].astype(str).str.lower()) != {"winner", "loser"}:
            invalid += 1; continue
        winner_row = group[group["player_role"].astype(str).str.lower() == "winner"].iloc[0]
        loser_row = group[group["player_role"].astype(str).str.lower() == "loser"].iloc[0]
        date = _normalize_calendar_date(winner_row["match_date"])
        tour = str(winner_row.get("tour") or "MEN").upper().replace("ATP", "MEN")
        key = (date, tour, canonical_name(winner_row["player_name"]), canonical_name(loser_row["player_name"]))
        candidates = wf_groups.get(key)
        if candidates is None or candidates.empty:
            unmatched += 1; continue
        if len(candidates) != 1:
            ambiguous += 1; continue
        wf_row = candidates.iloc[0]
        used_wf_indices.add(int(wf_row.name))
        try:
            p_w_serve = float(wf_row["winner_serve_p"]); p_l_serve = float(wf_row["loser_serve_p"]); p_elo_w = float(wf_row["elo_winner_p"])
            baseline_winner = calibrated_match_probability(p_w_serve, p_l_serve, p_elo_w, tour)
        except (KeyError, TypeError, ValueError):
            missing_baseline += 1; continue
        if not all(np.isfinite(v) for v in (p_w_serve, p_l_serve, p_elo_w, baseline_winner)):
            missing_baseline += 1; continue

        state_w = build_player_state(winner_row); state_l = build_player_state(loser_row)
        state_w.update({"player_name": winner_row["player_name"], "player_role": "winner"}); state_l.update({"player_name": loser_row["player_name"], "player_role": "loser"})
        oriented = orient_matchup_row(
            state_w, state_l, baseline_winner_probability=baseline_winner,
            base_features={"x_sr_winner": _logit(p_w_serve) - _logit(p_l_serve), "x_elo_winner": _logit(p_elo_w)},
            context=_shared_context(winner_row),
        )
        a_is_winner = bool(oriented["target_a_win"])
        oriented.update({
            "match_id": match_id, "match_date": date, "year": int(date.year), "tour": tour,
            "surface": winner_row.get("surface"), "level": wf_row.get("level"), "tourney_name": winner_row.get("tourney_name"), "best_of": winner_row.get("best_of"),
            "serve_probability_a": p_w_serve if a_is_winner else p_l_serve,
            "serve_probability_b": p_l_serve if a_is_winner else p_w_serve,
            "winner_name": str(winner_row.get("player_name") or ""), "loser_name": str(loser_row.get("player_name") or ""),
        })
        output.append(oriented)

    result = pd.DataFrame(output)
    qc = {
        "target_warehouse_matches": int(target_rows["match_id"].nunique()), "walkforward_rows": int(len(wf)), "matched_matches": int(len(result)),
        "warehouse_unmatched": int(unmatched), "warehouse_invalid": int(invalid), "walkforward_ambiguous": int(ambiguous),
        "missing_baseline_inputs": int(missing_baseline), "walkforward_unmatched": int(sum(1 for idx in wf.index if int(idx) not in used_wf_indices)),
    }
    return result, qc


def load_walkforward(base_dir: str | Path = ".") -> pd.DataFrame:
    base = Path(base_dir); frames = []
    for name, tour in (("v5_men_walkforward.csv", "MEN"), ("v5_wta_walkforward.csv", "WTA")):
        path = base / name
        if not path.exists(): continue
        frame = pd.read_csv(path, low_memory=False); frame["tour"] = tour; frames.append(frame)
    if not frames: raise FileNotFoundError("No V5 walk-forward files found")
    return pd.concat(frames, ignore_index=True, sort=False)
