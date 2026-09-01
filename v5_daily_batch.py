"""Automated V5 daily board and frozen prediction ledger."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re

import numpy as np
import pandas as pd

from v5_core import simulate_match
from v5_live_market import canonical_name, add_model_pricing, signal_row
from v5_model_calibration import calibrated_match_probability, calibration_record


BASE = Path(__file__).resolve().parent
MARKET_PATH = BASE / "v5_market_ready" / "market_board_input.csv"
OUTDIR = BASE / "v5_daily_ready"
LATEST_BOARD_PATH = OUTDIR / "latest_board.csv"
LATEST_SUMMARY_PATH = OUTDIR / "latest_summary.json"
FROZEN_LEDGER_PATH = OUTDIR / "frozen_predictions.csv"

SIGNAL_ORDER = {"BET": 0, "LEAN": 1, "REVIEW": 2, "PASS": 3, "N/A": 4, "NO PRICE": 5}


def _line_token(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    try:
        return f"{float(value):g}"
    except Exception:
        return str(value).strip().lower()


def freeze_key(row):
    fixture = str(row.get("fixture_id", "")).strip()
    group = str(row.get("market_group", "")).strip().lower()
    selection = canonical_name(row.get("selection"))
    line = _line_token(row.get("line"))
    return "|".join((fixture, group, selection, line))


def eligible_pre_match(feed, now=None):
    if feed.empty or "start_time_utc" not in feed.columns:
        return feed.iloc[0:0].copy()
    now = now or datetime.now(timezone.utc)
    now_ts = pd.Timestamp(now)
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize("UTC")
    else:
        now_ts = now_ts.tz_convert("UTC")
    starts = pd.to_datetime(feed["start_time_utc"], errors="coerce", utc=True)
    return feed.loc[starts.notna() & (starts > now_ts)].copy()


def merge_frozen(existing, fresh):
    if existing is None or existing.empty:
        return fresh.copy().reset_index(drop=True)
    if fresh is None or fresh.empty:
        return existing.copy().reset_index(drop=True)
    existing = existing.copy(); fresh = fresh.copy()
    if "freeze_key" not in existing.columns:
        existing["freeze_key"] = existing.apply(freeze_key, axis=1)
    if "freeze_key" not in fresh.columns:
        fresh["freeze_key"] = fresh.apply(freeze_key, axis=1)
    seen = set(existing["freeze_key"].astype(str))
    add = fresh.loc[~fresh["freeze_key"].astype(str).isin(seen)].copy()
    return pd.concat([existing, add], ignore_index=True, sort=False)


def rank_board(board):
    if board is None or board.empty:
        return pd.DataFrame() if board is None else board.copy()
    out = board.copy()
    out["_signal_rank"] = out.get("signal", pd.Series(index=out.index, dtype=object)).map(SIGNAL_ORDER).fillna(9)
    out["_ev_rank"] = pd.to_numeric(out.get("expected_value"), errors="coerce").fillna(-999.0)
    out = out.sort_values(["_signal_rank", "_ev_rank"], ascending=[True, False], kind="stable")
    return out.drop(columns=["_signal_rank", "_ev_rank"]).reset_index(drop=True)


def infer_surface(tournament):
    t = str(tournament or "").lower()
    grass = ("wimbledon", "queen", "halle", "eastbourne", "nottingham", "s-hertogenbosch", "hertogenbosch", "newport")
    clay = ("roland garros", "french open", "rome", "madrid", "monte carlo", "barcelona", "munich", "hamburg", "bastad", "gstaad", "kitzbuhel", "bucharest", "marrakech", "geneva", "estoril", "rio", "buenos aires", "santiago", "augsburg", "como", "plovdiv")
    hard = ("us open", "australian open", "cincinnati", "canada", "montreal", "toronto", "indian wells", "miami", "washington", "atlanta", "acapulco", "delray beach", "doha", "dubai", "beijing", "tokyo", "shanghai", "vienna", "paris masters", "basel", "manacor", "mallorca", "porto", "zhangjiagang")
    def has_term(term):
        return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", t) is not None
    if any(has_term(x) for x in grass): return "Grass", "Auto — tournament map"
    if any(has_term(x) for x in clay): return "Clay", "Auto — tournament map"
    if any(has_term(x) for x in hard): return "Hard", "Auto — tournament map"
    return "Hard", "Auto default — review"


def infer_best_of(tournament, tour):
    """Men's Grand Slam main draws are Bo5; qualifying and all WTA are Bo3."""
    t = str(tournament or "").lower()
    category = str(tour or "").lower()
    is_men = category in {"men", "atp"} or "men" in category
    is_slam = any(name in t for name in ("australian open", "french open", "roland garros", "wimbledon", "us open"))
    is_qualifying = any(term in t for term in ("qualifying", "qualification", "qualifier"))
    return 5 if is_men and is_slam and not is_qualifying else 3


def _tour_to_v5(category, tournament):
    text = f"{category or ''} {tournament or ''}".lower()
    return "WTA" if "wta" in text or "women" in text else "MEN"


def _player_lookup(ratings):
    return {canonical_name(x): x for x in ratings["player"].dropna().unique()}


def _resolve_player(name, lookup):
    target = canonical_name(name)
    if not target: return None
    exact = lookup.get(target)
    if exact is not None: return exact
    target_tokens = target.split(); target_set = set(target_tokens); subset = []
    for key, actual in lookup.items():
        key_set = set(key.split())
        if target_set.issubset(key_set) or key_set.issubset(target_set): subset.append(actual)
    if len(set(subset)) == 1: return subset[0]
    if len(target_tokens) >= 2:
        first, surname = target_tokens[0], target_tokens[-1]; ends = []
        for key, actual in lookup.items():
            toks = key.split()
            if len(toks) >= 2 and toks[0] == first and toks[-1] == surname: ends.append(actual)
        if len(set(ends)) == 1: return ends[0]
    return None


def _base_probs_from_ratings(df, p1, p2, surface, baseline):
    from v5_core import logistic, logit
    a = df[(df.player == p1) & (df.surface == surface)]
    b = df[(df.player == p2) & (df.surface == surface)]
    if a.empty or b.empty: raise ValueError("Player/surface not found in V5 ratings.")
    a = a.iloc[-1]; b = b.iloc[-1]
    wa = min(1.0, (float(a.surface_points) + float(b.surface_points)) / 700.0)
    eta_a = logit(baseline[surface]) + float(a.serve_global) - float(b.return_global) + 0.55 * wa * (float(a.serve_surface) - float(b.return_surface))
    eta_b = logit(baseline[surface]) + float(b.serve_global) - float(a.return_global) + 0.55 * wa * (float(b.serve_surface) - float(a.return_surface))
    return logistic(eta_a), logistic(eta_b), a, b


def _confidence_for_market(row, p1, p2, p1_conf, p2_conf):
    if str(row.get("market_group", "")) == "total_games": return min(p1_conf, p2_conf)
    sel = canonical_name(row.get("selection"))
    if sel == canonical_name(p1): return p1_conf
    if sel == canonical_name(p2): return p2_conf
    return min(p1_conf, p2_conf)


def _requested_market_lines(fixture_rows, market_group):
    if "market_group" not in fixture_rows.columns or "line" not in fixture_rows.columns: return []
    values = pd.to_numeric(fixture_rows.loc[fixture_rows["market_group"] == market_group, "line"], errors="coerce").dropna()
    return sorted({float(x) for x in values})


def build_fixture_board(fixture_rows, ratings_by_tour, summary, sims=5000, frozen_at=None):
    if fixture_rows is None or fixture_rows.empty: return pd.DataFrame()
    first = fixture_rows.iloc[0]
    tournament = first.get("tournament")
    tour = _tour_to_v5(first.get("tour"), tournament)
    ratings = ratings_by_tour[tour]
    surface, surface_source = infer_surface(tournament)
    best_of = infer_best_of(tournament, tour)

    lookup = _player_lookup(ratings)
    p1 = _resolve_player(first.get("player1"), lookup)
    p2 = _resolve_player(first.get("player2"), lookup)
    if p1 is None or p2 is None:
        missing=[]
        if p1 is None: missing.append(str(first.get("player1")))
        if p2 is None: missing.append(str(first.get("player2")))
        raise ValueError("Unmatched V5 player(s): " + ", ".join(missing))
    if p1 == p2: raise ValueError("Players resolved to the same V5 identity.")

    baseline = summary.get(tour, {}).get("baseline", {"Hard": 0.62, "Clay": 0.60, "Grass": 0.65})
    p1_serve, p2_serve, a, b = _base_probs_from_ratings(ratings, p1, p2, surface, baseline)
    elo_a = 0.35 * float(a.elo) + 0.65 * float(a.surface_elo)
    elo_b = 0.35 * float(b.elo) + 0.65 * float(b.surface_elo)
    p_elo = 1 / (1 + 10 ** ((elo_b - elo_a) / 400))
    calibrated_p = calibrated_match_probability(p1_serve, p2_serve, p_elo, tour)
    calibration = calibration_record(tour)

    # Form and day-volatility remain diagnostic state features until a separate
    # chronological holdout test proves they improve probability/score calibration.
    result = simulate_match(
        p1_serve, p2_serve,
        best_of=best_of,
        n=int(sims), seed=42,
        formA=0.0, formB=0.0, volA=0.0, volB=0.0,
        state_variation=False,
        spread_lines=_requested_market_lines(fixture_rows, "game_spread"),
        total_lines=_requested_market_lines(fixture_rows, "total_games"),
        target_pA_win=calibrated_p,
    )

    model_gap = abs(calibrated_p - p_elo)
    disagreement = "HIGH" if model_gap >= 0.12 else ("MODERATE" if model_gap >= 0.07 else "LOW")
    p1_conf = float(a.get("state_confidence", 0.0)); p2_conf = float(b.get("state_confidence", 0.0))

    priced = add_model_pricing(fixture_rows, result, p1, p2)
    frozen_at = frozen_at or datetime.now(timezone.utc).isoformat()
    signals=[]; confs=[]
    for _, r in priced.iterrows():
        conf = _confidence_for_market(r, p1, p2, p1_conf, p2_conf); confs.append(conf)
        sig = signal_row(r, disagreement_level=disagreement, state_confidence=conf)
        if surface_source == "Auto default — review" and sig in ("BET", "LEAN"): sig = "REVIEW"
        signals.append(sig)

    priced["signal"] = signals
    priced["state_confidence"] = confs
    priced["model_version"] = "V5.1_OUTCOME_CALIBRATED"
    priced["tour_v5"] = tour
    priced["surface"] = surface
    priced["surface_source"] = surface_source
    priced["best_of"] = best_of
    priced["resolved_player1"] = p1
    priced["resolved_player2"] = p2
    priced["simulations"] = int(sims)
    priced["serve_probability_p1"] = p1_serve
    priced["serve_probability_p2"] = p2_serve
    priced["elo_probability_p1"] = p_elo
    priced["raw_sim_probability_p1"] = float(result["raw_pA_win"])
    priced["calibrated_probability_p1"] = calibrated_p
    priced["calibration_version"] = calibration["version"]
    priced["calibration_fit_year"] = calibration["fit_year"]
    priced["calibration_validation_year"] = calibration["validation_year"]
    priced["state_variation_used"] = False
    priced["model_disagreement"] = disagreement
    priced["model_gap"] = model_gap
    priced["expected_margin"] = float(result["expected_margin"])
    priced["expected_total"] = float(result["expected_total"])
    priced["raw_expected_margin"] = float(result["raw_expected_margin"])
    priced["raw_expected_total"] = float(result["raw_expected_total"])
    priced["frozen_at_utc"] = frozen_at
    priced["result_status"] = "OPEN"
    priced["settled_result"] = ""
    priced["profit_units"] = np.nan
    priced["freeze_key"] = priced.apply(freeze_key, axis=1)
    return priced


def build_daily_outputs(feed, ratings_by_tour, summary, existing_ledger=None, now=None, sims=5000):
    eligible = eligible_pre_match(feed, now=now)
    frames=[]; errors=[]
    frozen_at = (now or datetime.now(timezone.utc)).isoformat()
    for fixture_id, g in eligible.groupby("fixture_id", sort=False):
        try:
            frames.append(build_fixture_board(g, ratings_by_tour, summary, sims=sims, frozen_at=frozen_at))
        except Exception as exc:
            first=g.iloc[0]
            errors.append({"fixture_id":str(fixture_id),"player1":first.get("player1"),"player2":first.get("player2"),"tournament":first.get("tournament"),"error":str(exc)})
    board = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    board = rank_board(board)
    fresh = pd.DataFrame() if board.empty else board[pd.to_numeric(board["model_probability"], errors="coerce").notna()].copy()
    ledger = merge_frozen(existing_ledger, fresh)
    return board, ledger, errors


def _load_summary(path=BASE / "v5_build_summary.json"):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_ratings():
    return {"MEN": pd.read_csv(BASE / "v5_men_ratings.csv", low_memory=False), "WTA": pd.read_csv(BASE / "v5_wta_ratings.csv", low_memory=False)}


def main(sims=5000):
    if not MARKET_PATH.exists(): raise FileNotFoundError(MARKET_PATH)
    feed=pd.read_csv(MARKET_PATH,low_memory=False); summary=_load_summary(); ratings=_load_ratings()
    existing=pd.read_csv(FROZEN_LEDGER_PATH,low_memory=False) if FROZEN_LEDGER_PATH.exists() else pd.DataFrame()
    old_count=len(existing); now=datetime.now(timezone.utc)
    board,ledger,errors=build_daily_outputs(feed,ratings,summary,existing_ledger=existing,now=now,sims=sims)
    OUTDIR.mkdir(parents=True,exist_ok=True); board.to_csv(LATEST_BOARD_PATH,index=False); ledger.to_csv(FROZEN_LEDGER_PATH,index=False)
    snapshot=None
    if "snapshot_utc" in feed.columns and not feed["snapshot_utc"].dropna().empty: snapshot=str(feed["snapshot_utc"].dropna().iloc[0])
    signal_counts=board["signal"].value_counts(dropna=False).to_dict() if not board.empty and "signal" in board.columns else {}
    payload={
        "status":"SUCCESS" if not errors else "PARTIAL",
        "built_at_utc":now.isoformat(),"market_snapshot_utc":snapshot,"simulations_per_fixture":int(sims),
        "market_rows_input":int(len(feed)),
        "eligible_pre_match_fixtures":int(eligible_pre_match(feed,now=now)["fixture_id"].nunique()) if not feed.empty else 0,
        "priced_rows":int(pd.to_numeric(board.get("model_probability"),errors="coerce").notna().sum()) if not board.empty else 0,
        "board_rows":int(len(board)),"frozen_ledger_rows":int(len(ledger)),"new_frozen_rows":int(len(ledger)-old_count),
        "signal_counts":{str(k):int(v) for k,v in signal_counts.items()},"errors":errors,
        "model_version":"V5.1_OUTCOME_CALIBRATED",
        "probability_source":"2025 outcome-calibrated serve/return + surface Elo; no sportsbook inputs",
        "state_variation_used":False,
    }
    LATEST_SUMMARY_PATH.write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8")
    print(json.dumps(payload,indent=2,default=str)); return payload


if __name__ == "__main__":
    main()
