from __future__ import annotations

from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected one exact match, found {text.count(old)}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    out, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected one regex match, found {count}")
    return out


def retire_context_builder() -> None:
    path = Path("build_v5_context_matchups.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, "from v5_court_speed import add_derived_court_speed_features\n", "", "court-speed import")
    text = replace_once(text, "    enriched = add_derived_court_speed_features(enriched)\n", "", "court-speed enrichment")
    text = replace_once(
        text,
        '        "court_speed": pick("court_speed_blended", "court_speed"),\n        "altitude_m": pick("altitude_m", "venue_altitude_m"),',
        '        # Retired court characteristics are deliberately neutral here.\n        # New authority features are evaluated in their own challenger and are\n        # not silently substituted into the accepted production model.\n        "court_speed": np.nan,\n        "altitude_m": np.nan,',
        "shared legacy court context",
    )
    path.write_text(text, encoding="utf-8")


def retire_daily_surface_resolver() -> None:
    path = Path("v5_daily_batch.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from v5_court_conditions_source import resolve_court_conditions\n",
        "from v5_tournament_authority import resolve_authority\n",
        "daily legacy court import",
    )
    resolver = '''def resolve_fixture_surface(tournament, *, start_time_utc=None, context_history=None, tour="", oddspapi_tournament_id=None):
    """Resolve surface only from the approved tournament authority.

    OddsPapi identity is optional evidence. There is no CourtSpeed, historical
    schedule, hardcoded tournament map, or default-surface fallback.
    """
    start = pd.to_datetime(start_time_utc, errors="coerce", utc=True)
    year = int(start.year) if pd.notna(start) else int(pd.Timestamp.now(tz="UTC").year)
    try:
        row = resolve_authority(
            tournament,
            year,
            tour=tour,
            match_date=start_time_utc,
            oddspapi_tournament_id=oddspapi_tournament_id,
        )
    except Exception:
        row = None
    surface = str((row or {}).get("Surface") or "").title().strip()
    if surface in {"Hard", "Clay", "Grass"}:
        return surface, "Tournament authority"
    raise ValueError(f"TOURNAMENT_AUTHORITY_SURFACE_MISSING:{tournament}:{year}")


'''
    text = regex_once(text, r"def infer_surface\(tournament\):.*?(?=def infer_best_of)", resolver, "daily legacy surface resolver block")
    old_call = '''    surface, surface_source = resolve_fixture_surface(
        tournament,
        start_time_utc=first.get("start_time_utc"),
        context_history=context_history,
    )'''
    new_call = '''    surface, surface_source = resolve_fixture_surface(
        tournament,
        start_time_utc=first.get("start_time_utc"),
        context_history=context_history,
        tour=tour,
        oddspapi_tournament_id=first.get("tournament_id") or first.get("oddspapi_tournament_id"),
    )'''
    text = replace_once(text, old_call, new_call, "daily authority resolver call")
    path.write_text(text, encoding="utf-8")


def retire_live_context_source() -> None:
    path = Path("v5_full_context_live.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from v5_court_conditions_source import resolve_court_conditions\n",
        "from v5_tournament_authority import resolve_authority\n",
        "live legacy court import",
    )
    target_rows = '''def _target_rows(fixture: dict) -> pd.DataFrame:
    match_id = f"live_{fixture.get('fixture_id') or 'unknown'}"
    start_utc = pd.to_datetime(fixture.get("start_time_utc"), errors="coerce", utc=True)
    match_date = start_utc.tz_convert("UTC").tz_localize(None) if pd.notna(start_utc) else pd.NaT
    authority = resolve_authority(
        fixture.get("tournament") or "",
        _fixture_year(fixture),
        tour=fixture.get("tour") or "",
        surface=fixture.get("surface"),
        match_date=fixture.get("start_time_utc"),
        oddspapi_tournament_id=fixture.get("tournament_id") or fixture.get("oddspapi_tournament_id"),
    )
    authority = authority or {}
    source_surface = str(authority.get("Surface") or "").title().strip()
    surface = source_surface if source_surface in {"Hard", "Clay", "Grass"} else np.nan
    source_environment = str(authority.get("Setting") or "").title().strip()
    environment = source_environment if source_environment in {"Indoor", "Outdoor"} else np.nan
    indoor = True if environment == "Indoor" else (False if environment == "Outdoor" else np.nan)

    common = {
        "match_id": match_id,
        "tour": "WTA" if str(fixture.get("tour") or "").upper() == "WTA" or "women" in str(fixture.get("tournament") or "").lower() else "MEN",
        "match_date": match_date,
        "scheduled_start_utc": None if pd.isna(start_utc) else start_utc.isoformat(),
        "tourney_id": fixture.get("tournament_id"),
        "tourney_name": fixture.get("tournament") or "",
        "match_num": np.nan,
        "round": fixture.get("round"),
        "surface": surface,
        "best_of": fixture.get("best_of", 3),
        "indoor": indoor,
        "indoor_outdoor": environment,
        "environment": environment,
        "authority_altitude_m": authority.get("Altitude (m)", np.nan),
        "authority_cpi": authority.get("Actual_CPI_Rating", np.nan),
        "authority_tennis_abstract_rating": authority.get("Tennis_Abstract_Rating", np.nan),
        "authority_ball_model": authority.get("Official_Ball_Model"),
        "authority_match_method": authority.get("authority_match_method"),
        "court_speed_override": np.nan,
        "external_cpi": np.nan,
        "external_ace_rate_pct": np.nan,
        "external_rally_length": np.nan,
        "external_relative_air_density": np.nan,
        "external_altitude_m": np.nan,
        "external_ball_type": np.nan,
        "external_overall_speed_rating": np.nan,
        "court_conditions_source": "TournamentAuthority" if authority else "missing",
        "court_conditions_source_quality": "authority" if authority else "missing",
        "court_conditions_target_year": _fixture_year(fixture),
        "court_conditions_refreshed_at": None,
        "cpi_source_year": None,
        "ace_rate_pct_source_year": None,
        "rally_length_source_year": None,
        "relative_air_density_source_year": None,
        "ball_type_source_year": None,
        "surface_source": "TournamentAuthority" if pd.notna(surface) else "missing",
        "environment_source": "TournamentAuthority" if pd.notna(environment) else "missing",
        "cpi_source": "missing",
        "ace_rate_source": "missing",
        "rally_source": "missing",
        "rad_source": "missing",
        "altitude_source": "missing",
        "ball_source": "missing",
        "overall_speed_source": "missing",
        "result_file": "LIVE_TARGET",
        "source_quality": "live_pre_match_target",
        "match_games": np.nan,
        "match_sets": np.nan,
        "match_duration_minutes": np.nan,
    }
    blank_stats = {
        "stat_aces": np.nan,
        "stat_double_faults": np.nan,
        "stat_service_points": np.nan,
        "stat_first_serves_in": np.nan,
        "stat_first_serve_points_won": np.nan,
        "stat_second_serve_points_won": np.nan,
        "stat_break_points_saved": np.nan,
        "stat_break_points_faced": np.nan,
        "stat_return_points_total": np.nan,
        "stat_return_points_won": np.nan,
        "stat_break_points_opportunities": np.nan,
        "stat_break_points_converted": np.nan,
    }
    p1, p2 = str(fixture.get("player1") or ""), str(fixture.get("player2") or "")
    return pd.DataFrame([
        {**common, **blank_stats, "player_name": p1, "opponent_name": p2, "player_role": "target", "player_rank": fixture.get("player1_rank"), "opponent_rank": fixture.get("player2_rank")},
        {**common, **blank_stats, "player_name": p2, "opponent_name": p1, "player_role": "target", "player_rank": fixture.get("player2_rank"), "opponent_rank": fixture.get("player1_rank")},
    ])


'''
    text = regex_once(text, r"def _target_rows\(fixture: dict\) -> pd\.DataFrame:.*?(?=def build_live_enriched_history)", target_rows, "live target rows")
    text = replace_once(
        text,
        '        "court_speed": pick("court_speed_override", "court_speed_blended", "court_speed"),\n        "altitude_m": pick("external_altitude_m", "venue_altitude_m", "altitude_m"),',
        '        # New authority court characteristics remain shadow features until\n        # their individual challenger gates pass. Production gets no retired fallback.\n        "court_speed": np.nan,\n        "altitude_m": np.nan,',
        "live accepted-model court context",
    )
    path.write_text(text, encoding="utf-8")


def retire_workflows() -> None:
    Path(".github/workflows/courtspeed_conditions_refresh.yml").write_text(
        '''name: CourtSpeed Conditions Refresh (Retired)\n\non:\n  workflow_dispatch:\n\npermissions:\n  contents: read\n\njobs:\n  retired:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo "Retired - context_registry/tournament_authority.csv is the sole tournament/court authority."\n''',
        encoding="utf-8",
    )
    Path(".github/workflows/courtspeed_conditions_tests.yml").write_text(
        '''name: CourtSpeed Conditions Tests (Retired)\n\non:\n  workflow_dispatch:\n\npermissions:\n  contents: read\n\njobs:\n  retired:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo "Retired legacy CourtSpeed tests; authority contracts run in v5_tournament_challenger.yml."\n''',
        encoding="utf-8",
    )


def main() -> None:
    retire_context_builder()
    retire_daily_surface_resolver()
    retire_live_context_source()
    retire_workflows()
    print("Legacy CourtSpeed/court-condition production paths retired.")


if __name__ == "__main__":
    main()
