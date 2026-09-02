from __future__ import annotations

import math
import numpy as np
import pandas as pd

from v5_tournament_registry import normalize_event_name


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


def _historical_prior(prior: pd.DataFrame, target: pd.Series) -> tuple[float, float, int, str]:
    target_year = int(target["match_start"].year)
    hist = prior[prior["match_start"].dt.year < target_year]
    if hist.empty:
        return np.nan, np.nan, 0, "none"

    event_id = target.get("canonical_event_id")
    same_event = hist[hist["canonical_event_id"] == event_id] if pd.notna(event_id) else hist.iloc[0:0]
    if not same_event.empty:
        years_old = target_year - same_event["match_start"].dt.year.to_numpy()
        weights = np.power(0.70, np.maximum(years_old - 1, 0))
        m, u, n = _estimate(same_event["speed_residual"], weights)
        if n > 0:
            return m, u, n, "same_event"

    cohort = hist[
        (hist["tour"].astype(str) == str(target.get("tour")))
        & (hist["surface"].astype(str) == str(target.get("surface")))
        & (hist["indoor"].astype(str) == str(target.get("indoor")))
    ]
    if not cohort.empty:
        years_old = target_year - cohort["match_start"].dt.year.to_numpy()
        weights = np.power(0.70, np.maximum(years_old - 1, 0))
        m, u, n = _estimate(cohort["speed_residual"], weights)
        if n > 0:
            return m, u, n, "tour_surface_indoor"
    return np.nan, np.nan, 0, "none"


def build_court_speed_features(matches: pd.DataFrame) -> pd.DataFrame:
    """Create leak-safe historical-prior/current-event/current-day court-speed states."""
    if matches is None or matches.empty:
        return matches.copy() if matches is not None else pd.DataFrame()

    df = matches.copy()
    df["_orig_order"] = np.arange(len(df))
    df["match_start"] = pd.to_datetime(df["match_start"], errors="coerce", utc=True)
    df = df.sort_values(["match_start", "_orig_order"], kind="stable").reset_index(drop=True)
    rows = []

    for _, target in df.iterrows():
        start = target["match_start"]
        if pd.isna(start):
            prior = df.iloc[0:0]
        else:
            # With date-only historical data, equal timestamps deliberately do not see one
            # another. That is conservative and prevents unknown same-day order leakage.
            prior = df[df["match_start"] < start]

        hist_mean, hist_u, hist_n, prior_level = _historical_prior(prior, target)
        year = int(start.year) if pd.notna(start) else -1
        event_id = target.get("canonical_event_id")
        current = prior[
            (prior["canonical_event_id"] == event_id)
            & (prior["match_start"].dt.year == year)
        ] if pd.notna(event_id) else prior.iloc[0:0]
        cur_mean, cur_u, cur_n = _estimate(current["speed_residual"])

        day = current[current["match_start"].dt.normalize() == start.normalize()] if pd.notna(start) else current.iloc[0:0]
        day_mean, day_u, day_n = _estimate(day["speed_residual"])

        blended, blended_u = blend_estimates(hist_mean, hist_u, cur_mean, cur_u)
        rows.append({
            "_orig_order": target["_orig_order"],
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
            "court_speed_delta_vs_historical": (
                float(cur_mean - hist_mean) if pd.notna(cur_mean) and pd.notna(hist_mean) else np.nan
            ),
            "court_speed_prior_level": prior_level,
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
    own = (
        first_in * first_won + (1.0 - first_in) * second_won
        if all(math.isfinite(v) for v in (first_in, first_won, second_won)) else float("nan")
    )
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
    # Faster conditions should suppress return success relative to the player's prior state.
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
    name = normalize_event_name(row.get("tourney_name") or "")
    if not name:
        return None
    tour = str(row.get("tour") or "MEN").upper()
    return f"{tour}:{name}"


def add_derived_court_speed_features(player_rows: pd.DataFrame) -> pd.DataFrame:
    """Derive opponent-adjusted event speed observations then attach pre-match speed state.

    Current-match statistics create a speed observation only for later matches. The target
    row receives historical/current-event estimates produced solely from earlier dates.
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
        speed_residual = _mean_finite(signals)
        event_id = _event_id(first)
        observations.append({
            "match_id": match_id,
            "canonical_event_id": event_id,
            "tour": first.get("tour"),
            "surface": first.get("surface"),
            "indoor": first.get("indoor", np.nan),
            "match_start": first.get("match_date"),
            "speed_residual": speed_residual,
        })

    if not observations:
        return df
    match_frame = pd.DataFrame(observations)
    speed = build_court_speed_features(match_frame)
    feature_cols = ["match_id"] + [c for c in speed.columns if c.startswith("court_speed_")]
    mapping = speed[feature_cols].drop_duplicates("match_id").set_index("match_id")
    for col in feature_cols[1:]:
        df[col] = df["match_id"].map(mapping[col])
    return df.reset_index(drop=True)
