from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


p = Path("build_v5_context_matchups.py")
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    "from v5_settlement import canonical_name\nfrom v5_travel_features import build_travel_features\n",
    "from v5_settlement import canonical_name\nfrom v5_schedule_context import enrich_events_with_schedule\nfrom v5_travel_features import build_travel_features\n",
    "context import",
)
s = replace_once(
    s,
    "    enriched = add_trajectory_features(enriched)\n    if tournament_registry is not None and not tournament_registry.empty:\n",
    "    enriched = add_trajectory_features(enriched)\n    enriched = enrich_events_with_schedule(enriched)\n    if tournament_registry is not None and not tournament_registry.empty:\n",
    "context enrichment",
)
p.write_text(s, encoding="utf-8")

p = Path("v5_court_speed.py")
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    '''def _cohort_key(row: pd.Series) -> tuple[str, str, str]:
    return (
        str(row.get("tour") or ""),
        str(row.get("surface") or ""),
        str(row.get("indoor")),
    )
''',
    '''def _cohort_key(row: pd.Series) -> tuple[str, str, str]:
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
''',
    "cohort helpers",
)
s = replace_once(
    s,
    "    cohort_year_stats: dict[tuple[str, str, str], dict[int, dict[str, float]]] = defaultdict(lambda: defaultdict(_new_moments))\n",
    "    cohort_year_stats: dict[tuple[str, str, str], dict[int, dict[str, float]]] = defaultdict(lambda: defaultdict(_new_moments))\n    structural_year_stats: dict[tuple, dict[int, dict[str, float]]] = defaultdict(lambda: defaultdict(_new_moments))\n",
    "structural state",
)
s = replace_once(
    s,
    '''            cohort = _cohort_key(target)

            hist_mean, hist_u, hist_n = _historical_moments_estimate(event_year_stats.get(event_key), year) if event_key else (np.nan, np.nan, 0)
            prior_level = "same_event" if hist_n > 0 else "none"
            if hist_n == 0:
                hist_mean, hist_u, hist_n = _historical_moments_estimate(cohort_year_stats.get(cohort), year)
                if hist_n > 0:
                    prior_level = "tour_surface_indoor"
''',
    '''            cohort = _cohort_key(target)
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
''',
    "prior hierarchy",
)
s = replace_once(
    s,
    '''                "court_speed_historical_prior": hist_mean,
                "court_speed_historical_sample_size": hist_n,
                "court_speed_historical_uncertainty": hist_u,
''',
    '''                "court_speed_structural_prior": structural_mean,
                "court_speed_structural_sample_size": structural_n,
                "court_speed_structural_uncertainty": structural_u,
                "court_speed_historical_prior": hist_mean,
                "court_speed_historical_sample_size": hist_n,
                "court_speed_historical_uncertainty": hist_u,
''',
    "structural outputs",
)
s = replace_once(
    s,
    '''            cohort = _cohort_key(completed)
            if event_key:
                _add_moment(event_year_stats[event_key][year], float(value))
                _add_moment(current_event_stats[(event_key, year)], float(value))
                _add_moment(current_day_stats[(event_key, day)], float(value))
            _add_moment(cohort_year_stats[cohort][year], float(value))
''',
    '''            cohort = _cohort_key(completed)
            structural = _structural_key(completed)
            if event_key:
                _add_moment(event_year_stats[event_key][year], float(value))
                _add_moment(current_event_stats[(event_key, year)], float(value))
                _add_moment(current_day_stats[(event_key, day)], float(value))
            if structural:
                _add_moment(structural_year_stats[structural][year], float(value))
            _add_moment(cohort_year_stats[cohort][year], float(value))
''',
    "structural update",
)
s = replace_once(
    s,
    '''            "court_speed_historical_prior": np.nan,
            "court_speed_historical_sample_size": 0,
            "court_speed_historical_uncertainty": np.nan,
''',
    '''            "court_speed_structural_prior": np.nan,
            "court_speed_structural_sample_size": 0,
            "court_speed_structural_uncertainty": np.nan,
            "court_speed_historical_prior": np.nan,
            "court_speed_historical_sample_size": 0,
            "court_speed_historical_uncertainty": np.nan,
''',
    "invalid rows",
)
s = replace_once(
    s,
    '''            "indoor": first.get("indoor", np.nan),
            "match_start": first.get("match_date"),
            "speed_residual": _mean_finite(signals),
''',
    '''            "indoor": first.get("indoor", np.nan),
            "schedule_surface": first.get("schedule_surface"),
            "schedule_setting": first.get("schedule_setting"),
            "schedule_altitude_m": first.get("schedule_altitude_m"),
            "schedule_speed_profile_family": first.get("schedule_speed_profile_family"),
            "match_start": first.get("match_date"),
            "speed_residual": _mean_finite(signals),
''',
    "observation schedule context",
)
p.write_text(s, encoding="utf-8")
