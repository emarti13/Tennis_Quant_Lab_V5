from __future__ import annotations

from collections import defaultdict
import math

import numpy as np
import pandas as pd

from v5_venue_metadata import stable_event_id


def _estimate(values: pd.Series, weights: np.ndarray | None = None) -> tuple[float, float, int]:
    vals = pd.to_numeric(values, errors="coerce")
    mask = vals.notna().to_numpy()
    if not mask.any():
        return np.nan, np.nan, 0
    arr = vals.to_numpy(dtype=float)[mask]
    if weights is None:
        w = np.ones(len(arr), dtype=float)
    else:
        w = np.asarray(weights, dtype=float)[mask]
    w = np.where(np.isfinite(w) & (w > 0), w, 0.0)
    if w.sum() <= 0:
        w = np.ones(len(arr), dtype=float)
    mean = float(np.average(arr, weights=w))
    if len(arr) == 1:
        uncertainty = 0.50
    else:
        variance = float(np.average((arr - mean) ** 2, weights=w))
        eff_n = float((w.sum() ** 2) / max((w ** 2).sum(), 1e-12))
        uncertainty = max(math.sqrt(max(variance, 0.0) / max(eff_n, 1.0)), 0.08)
    return mean, uncertainty, int(len(arr))


def blend_estimates(mean_a: float, uncertainty_a: float, mean_b: float, uncertainty_b: float) -> tuple[float, float]:
    a_ok = pd.notna(mean_a) and pd.notna(uncertainty_a) and float(uncertainty_a) > 0
    b_ok = pd.notna(mean_b) and pd.notna(uncertainty_b) and float(uncertainty_b) > 0
    if not a_ok and not b_ok:
        return np.nan, np.nan
    if not a_ok:
        return float(mean_b), float(uncertainty_b)
    if not b_ok:
        return float(mean_a), float(uncertainty_a)
    pa = 1.0 / (float(uncertainty_a) ** 2)
    pb = 1.0 / (float(uncertainty_b) ** 2)
    mean = (pa * float(mean_a) + pb * float(mean_b)) / (pa + pb)
    uncertainty = math.sqrt(1.0 / (pa + pb))
    return float(mean), float(uncertainty)


def _new_moments() -> dict[str, float]:
    return {"count": 0, "sum": 0.0, "sumsq": 0.0}


def _add_moment(stats: dict[str, float], value: float) -> None:
    if value is None or not math.isfinite(float(value)):
        return
    x = float(value)
    stats["count"] += 1
    stats["sum"] += x
    stats["sumsq"] += x * x


def _moments_estimate(stats: dict[str, float] | None) -> tuple[float, float, int]:
    if not stats or int(stats.get("count", 0)) <= 0:
        return np.nan, np.nan, 0
    n = int(stats["count"])
    mean = float(stats["sum"] / n)
    if n == 1:
        return mean, 0.50, 1
    variance = max(float(stats["sumsq"] / n - mean * mean), 0.0)
    uncertainty = max(math.sqrt(variance / n), 0.08)
    return mean, uncertainty, n


def _historical_moments_estimate(year_stats: dict[int, dict[str, float]] | None, target_year: int) -> tuple[float, float, int]:
    if not year_stats:
        return np.nan, np.nan, 0
    total_w = weighted_sum = weighted_sumsq = sum_w2 = 0.0
    n_total = 0
    for year, stats in year_stats.items():
        if int(year) >= int(target_year) or int(stats.get("count", 0)) <= 0:
            continue
        n = int(stats["count"])
        years_old = int(target_year) - int(year)
        w = float(0.70 ** max(years_old - 1, 0))
        total_w += w * n
        weighted_sum += w * float(stats["sum"])
        weighted_sumsq += w * float(stats["sumsq"])
        sum_w2 += (w * w) * n
        n_total += n
    if n_total <= 0 or total_w <= 0:
        return np.nan, np.nan, 0
    mean = weighted_sum / total_w
    if n_total == 1:
        return float(mean), 0.50, 1
    variance = max(weighted_sumsq / total_w - mean * mean, 0.0)
    eff_n = (total_w * total_w) / max(sum_w2, 1e-12)
    uncertainty = max(math.sqrt(variance / max(eff_n, 1.0)), 0.08)
    return float(mean), float(uncertainty), int(n_total)


def _cohort_key(row: pd.Series) -> tuple[str, str, str]:
    return (
        str(row.get("tour") or ""),
        str(row.get("surface") or ""),
        str(row.get("indoor")),
    )


def _altitude_band(value) -> str:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return "unknown"
    altitude = float(parsed)
    if altitude >= 1500:
        return "extreme"
    if altitude >= 750:
        return "high"
    if altitude >= 300:
        return "moderate"
    return "low"


def _structural_key(row: pd.Series):
    profile = str(row.get("schedule_speed_profile_family") or "").strip()
    setting = str(row.get("schedule_setting") or "").strip().lower()
    surface = str(row.get("surface") or row.get("schedule_surface") or "").strip().lower()
    tour = str(row.get("tour") or "").strip().upper()
    if not profile or not surface or not tour:
        return None
    return (tour, surface, setting or str(row.get("indoor")), profile, _altitude_band(row.get("schedule_altitude_m")))


def build_court_speed_features(matches: pd.DataFrame) -> pd.DataFrame:
    """Create leak-safe historical-prior/current-event/current-day court-speed states.

    This implementation is streaming rather than repeatedly filtering the full historical
    table. Rows sharing the exact same timestamp are priced before any of them update state,
    preventing same-time leakage. Date-only history therefore never leaks same-day matches.
    """
    if matches is None or matches.empty:
        return matches.copy() if matches is not None else pd.DataFrame()

    df = matches.copy()
    df["_orig_order"] = np.arange(len(df))
    df["match_start"] = pd.to_datetime(df["match_start"], errors="coerce", utc=True)
    df = df.sort_values(["match_start", "_orig_order"], kind="stable", na_position="last").reset_index(drop=True)

    event_year_stats: dict[str, dict[int, dict[str, float]]] = defaultdict(lambda: defaultdict(_new_moments))
    cohort_year_stats: dict[tuple[str, str, str], dict[int, dict[str, float]]] = defaultdict(lambda: defaultdict(_new_moments))
    structural_year_stats: dict[tuple, dict[int, dict[str, float]]] = defaultdict(lambda: defaultdict(_new_moments))
    current_event_stats: dict[tuple[str, int], dict[str, float]] = defaultdict(_new_moments)
    current_day_stats: dict[tuple[str, object], dict[str, float]] = defaultdict(_new_moments)
    rows: list[dict] = []

    valid = df[df["match_start"].notna()]
    for timestamp, batch in valid.groupby("match_start", sort=True):
        year = int(timestamp.year)
        day = timestamp.normalize()
        # Score every row in this exact-time batch from state that existed before the batch.
        for _, target in batch.iterrows():
            event_id = target.get("canonical_event_id")
            event_key = str(event_id) if pd.notna(event_id) and str(event_id) else ""
            cohort = _cohort_key(target)
            structural = _structural_key(target)

            structural_mean, structural_u, structural_n = _historical_moments_estimate(structural_year_stats.get(structural), year) if structural else (np.nan, np.nan, 0)
            hist_mean, hist_u, hist_n = _historical_moments_estimate(event_year_stats.get(event_key), year) if event_key else (np.nan, np.nan, 0)
            prior_level = "same_event" if hist_n > 0 else "none"
            if hist_n == 0 and structural_n > 0:
                hist_mean, hist_u, hist_n = structural_mean, structural_u, structural_n
                prior_level = "schedule_structural"
            if hist_n == 0:
                hist_mean, hist_u, hist_n = _historical_moments_estimate(cohort_year_stats.get(cohort), year)
                if hist_n > 0:
                    prior_level = "tour_surface_indoor"

            cur_mean, cur_u, cur_n = _moments_estimate(current_event_stats.get((event_key, year))) if event_key else (np.nan, np.nan, 0)
            day_mean, day_u, day_n = _moments_estimate(current_day_stats.get((event_key, day))) if event_key else (np.nan, np.nan, 0)
            blended, blended_u = blend_estimates(hist_mean, hist_u, cur_mean, cur_u)
            rows.append({
                "_orig_order": target["_orig_order"],
                "court_speed_structural_prior": structural_mean,
                "court_speed_structural_sample_size": structural_n,
                "court_speed_structural_uncertainty": structural_u,
                "court_speed_historical_prior": hist_mean,
                "court_speed_historical_sample_size": hist_n,
                "court_speed_historical_uncertainty": hist_u,
                "court_speed_current_event": cur_mean,
                "court_speed_current_event_sample_size": cur_n,
                "court_speed_current_event_uncertainty": cur_u,
                "court_speed_current_day": day_mean,
                "court_speed_current_day_sample_size": day_n,
                "court_speed_blended": blended,
                "court_speed_blended_uncertainty": blended_u,
                "court_speed_delta_vs_historical": float(cur_mean - hist_mean) if pd.notna(cur_mean) and pd.notna(hist_mean) else np.nan,
                "court_speed_prior_level": prior_level,
            })

        # Only after every target at this exact timestamp is priced may the observations enter history.
        for _, completed in batch.iterrows():
            value = pd.to_numeric(pd.Series([completed.get("speed_residual")]), errors="coerce").iloc[0]
            if pd.isna(value) or not math.isfinite(float(value)):
                continue
            event_id = completed.get("canonical_event_id")
            event_key = str(event_id) if pd.notna(event_id) and str(event_id) else ""
            cohort = _cohort_key(completed)
            structural = _structural_key(completed)
            if event_key:
                _add_moment(event_year_stats[event_key][year], float(value))
                _add_moment(current_event_stats[(event_key, year)], float(value))
                _add_moment(current_day_stats[(event_key, day)], float(value))
            if structural:
                _add_moment(structural_year_stats[structural][year], float(value))
            _add_moment(cohort_year_stats[cohort][year], float(value))

    # Invalid-date rows remain explicit missing context.
    for _, target in df[df["match_start"].isna()].iterrows():
        rows.append({
            "_orig_order": target["_orig_order"],
            "court_speed_structural_prior": np.nan,
            "court_speed_structural_sample_size": 0,
            "court_speed_structural_uncertainty": np.nan,
            "court_speed_historical_prior": np.nan,
            "court_speed_historical_sample_size": 0,
            "court_speed_historical_uncertainty": np.nan,
            "court_speed_current_event": np.nan,
            "court_speed_current_event_sample_size": 0,
            "court_speed_current_event_uncertainty": np.nan,
            "court_speed_current_day": np.nan,
            "court_speed_current_day_sample_size": 0,
            "court_speed_blended": np.nan,
            "court_speed_blended_uncertainty": np.nan,
            "court_speed_delta_vs_historical": np.nan,
            "court_speed_prior_level": "none",
        })

    features = pd.DataFrame(rows).set_index("_orig_order")
    original = matches.copy()
    original["_orig_order"] = np.arange(len(original))
    for col in features.columns:
        original[col] = original["_orig_order"].map(features[col])
    return original.drop(columns=["_orig_order"]).reset_index(drop=True)


def _num(row: pd.Series, name: str) -> float:
    value = pd.to_numeric(pd.Series([row.get(name)]), errors="coerce").iloc[0]
    return float(value) if pd.notna(value) and math.isfinite(float(value)) else float("nan")


def _ratio(n: float, d: float) -> float:
    return float(n / d) if math.isfinite(n) and math.isfinite(d) and d > 0 else float("nan")


def _mean_finite(values) -> float:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return float(np.mean(vals)) if vals else float("nan")


def _expected_service_win(row: pd.Series, opponent: pd.Series) -> float:
    first_in = _num(row, "rolling_first_serve_in_pct")
    first_won = _num(row, "rolling_first_serve_points_won_pct")
    second_won = _num(row, "rolling_second_serve_points_won_pct")
    own = first_in * first_won + (1.0 - first_in) * second_won if all(math.isfinite(v) for v in (first_in, first_won, second_won)) else float("nan")
    opp_return = _num(opponent, "rolling_return_points_won_pct")
    versus_return = 1.0 - opp_return if math.isfinite(opp_return) else float("nan")
    return _mean_finite([own, versus_return])


def _player_speed_signal(row: pd.Series, opponent: pd.Series) -> float:
    svpt = _num(row, "stat_service_points")
    first_won = _num(row, "stat_first_serve_points_won")
    second_won = _num(row, "stat_second_serve_points_won")
    actual_serve_win = _ratio(first_won + second_won, svpt) if all(math.isfinite(v) for v in (first_won, second_won, svpt)) else float("nan")
    expected_serve_win = _expected_service_win(row, opponent)
    serve_residual = actual_serve_win - expected_serve_win if all(math.isfinite(v) for v in (actual_serve_win, expected_serve_win)) else float("nan")

    actual_ace = _ratio(_num(row, "stat_aces"), svpt)
    expected_ace = _num(row, "rolling_ace_rate")
    ace_residual = actual_ace - expected_ace if all(math.isfinite(v) for v in (actual_ace, expected_ace)) else float("nan")

    ret_total = _num(row, "stat_return_points_total")
    actual_return = _ratio(_num(row, "stat_return_points_won"), ret_total)
    expected_return = _num(row, "rolling_return_points_won_pct")
    return_suppression = expected_return - actual_return if all(math.isfinite(v) for v in (expected_return, actual_return)) else float("nan")

    components = []
    for value, weight in ((serve_residual, 0.55), (ace_residual, 0.25), (return_suppression, 0.20)):
        if math.isfinite(value):
            components.append((value, weight))
    if not components:
        return float("nan")
    weight_sum = sum(weight for _, weight in components)
    return float(sum(value * weight for value, weight in components) / weight_sum)


def _event_id(row: pd.Series) -> str | None:
    name = str(row.get("tourney_name") or "")
    event_id = stable_event_id(row.get("tour") or "MEN", row.get("tourney_id"), name)
    return event_id if not event_id.endswith(":unknown") else None


def add_derived_court_speed_features(player_rows: pd.DataFrame) -> pd.DataFrame:
    """Derive opponent-adjusted event speed observations then attach pre-match speed state.

    Current-match statistics create a speed observation only for later matches. The target
    row receives historical/current-event estimates produced solely from earlier timestamps.
    Stable source tournament codes take precedence over event names, preserving continuity
    through sponsor/name changes.
    """
    if player_rows is None or player_rows.empty:
        return player_rows.copy() if player_rows is not None else pd.DataFrame()

    df = player_rows.copy()
    df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce")
    observations = []
    for match_id, group in df.groupby("match_id", sort=False):
        if len(group) != 2:
            continue
        first, second = group.iloc[0], group.iloc[1]
        signals = [_player_speed_signal(first, second), _player_speed_signal(second, first)]
        observations.append({
            "match_id": match_id,
            "canonical_event_id": _event_id(first),
            "tour": first.get("tour"),
            "surface": first.get("surface"),
            "indoor": first.get("indoor", np.nan),
            "schedule_surface": first.get("schedule_surface"),
            "schedule_setting": first.get("schedule_setting"),
            "schedule_altitude_m": first.get("schedule_altitude_m"),
            "schedule_speed_profile_family": first.get("schedule_speed_profile_family"),
            "match_start": first.get("match_date"),
            "speed_residual": _mean_finite(signals),
        })

    if not observations:
        return df
    speed = build_court_speed_features(pd.DataFrame(observations))
    feature_cols = ["match_id"] + [c for c in speed.columns if c.startswith("court_speed_")]
    mapping = speed[feature_cols].drop_duplicates("match_id").set_index("match_id")
    for col in feature_cols[1:]:
        df[col] = df["match_id"].map(mapping[col])
    return df.reset_index(drop=True)
