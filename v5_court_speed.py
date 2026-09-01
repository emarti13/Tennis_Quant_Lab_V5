from __future__ import annotations

import math
import numpy as np
import pandas as pd


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
    # Uncertainty is standard-error-like, with a floor so one observation is not treated as certain.
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
        return m, u, n, "same_event"

    # Hierarchical fallback. Venue/cohort keys can be added without changing consumers;
    # today the strongest available generic fallback is tour/surface/indoor.
    cohort = hist[
        (hist["tour"].astype(str) == str(target.get("tour")))
        & (hist["surface"].astype(str) == str(target.get("surface")))
        & (hist["indoor"].astype(str) == str(target.get("indoor")))
    ]
    if not cohort.empty:
        years_old = target_year - cohort["match_start"].dt.year.to_numpy()
        weights = np.power(0.70, np.maximum(years_old - 1, 0))
        m, u, n = _estimate(cohort["speed_residual"], weights)
        return m, u, n, "tour_surface_indoor"
    return np.nan, np.nan, 0, "none"


def build_court_speed_features(matches: pd.DataFrame) -> pd.DataFrame:
    """Create leak-safe historical-prior/current-event/current-day court-speed states.

    `speed_residual` is deliberately an input contract: later feature engineering computes
    opponent-adjusted hold/ace/break/etc residual composites. This estimator only performs
    temporal prior/update logic and never sees later matches.
    """
    if matches is None or matches.empty:
        return matches.copy() if matches is not None else pd.DataFrame()

    df = matches.copy()
    df["_orig_order"] = np.arange(len(df))
    df["match_start"] = pd.to_datetime(df["match_start"], errors="coerce", utc=True)
    df = df.sort_values(["match_start", "_orig_order"], kind="stable").reset_index(drop=True)
    rows = []

    for i, target in df.iterrows():
        start = target["match_start"]
        if pd.isna(start):
            prior = df.iloc[0:0]
        else:
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
        # Same-day observations are already included in the event estimate. Keep their
        # state exposed separately; do not double-count them in the default blend.
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
