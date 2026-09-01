from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd

from v5_daily_batch import MARKET_PATH, _load_ratings, _load_summary, build_daily_outputs
from v5_live_market import canonical_name

OUT = Path("v5_daily_ready/calibrated_live_board_diagnostic.json")


def _num(value):
    try:
        x = float(value)
        return x if pd.notna(x) else None
    except Exception:
        return None


def _mean(values):
    values = [x for x in values if x is not None]
    return None if not values else sum(values) / len(values)


def _is_main(value):
    return str(value).strip().lower() in {"true", "1", "yes"}


def _side(q):
    if q is None: return "unknown"
    if q < 0.5: return "underdog"
    if q > 0.5: return "favorite"
    return "pickem"


def _selection_probability(row, p1_probability_column):
    p = _num(row.get(p1_probability_column))
    if p is None: return None
    sel = canonical_name(row.get("selection"))
    p1 = canonical_name(row.get("resolved_player1") or row.get("player1"))
    p2 = canonical_name(row.get("resolved_player2") or row.get("player2"))
    if sel == p1: return p
    if sel == p2: return 1.0 - p
    return None


def main():
    feed = pd.read_csv(MARKET_PATH, low_memory=False)
    snapshots = pd.to_datetime(feed["snapshot_utc"], errors="coerce", utc=True)
    snapshot = snapshots.max()
    if pd.isna(snapshot):
        raise RuntimeError("No valid market snapshot timestamp")

    board, _, errors = build_daily_outputs(
        feed, _load_ratings(), _load_summary(), existing_ledger=pd.DataFrame(), now=snapshot, sims=1500
    )

    bets = board[board["signal"] == "BET"].copy()
    actionable = board[board["signal"].isin(["BET", "LEAN"])].copy()
    ml = board[(board["market_group"] == "moneyline") & board["model_probability"].notna()].copy()
    main_board = board[board["main_line"].map(_is_main)].copy() if "main_line" in board.columns else board.iloc[0:0].copy()
    main_bets = main_board[main_board["signal"] == "BET"].copy()
    main_actionable = main_board[main_board["signal"].isin(["BET", "LEAN"])].copy()

    ml_market = {}
    for _, r in ml.iterrows():
        q = _num(r.get("consensus_no_vig_prob"))
        if q is not None:
            ml_market[(str(r.get("fixture_id")), canonical_name(r.get("selection")))] = q

    def selected_side_counts(frame, group):
        counts = Counter()
        for _, r in frame[frame["market_group"] == group].iterrows():
            if group == "moneyline":
                q = _num(r.get("consensus_no_vig_prob"))
            else:
                q = ml_market.get((str(r.get("fixture_id")), canonical_name(r.get("selection"))))
            counts[_side(q)] += 1
        return dict(counts)

    dog_delta=[]; fav_delta=[]; compression=[]; raw_dog_delta=[]; calibrated_minus_raw=[]; conditioning_miss=[]
    for _, r in ml.iterrows():
        q=_num(r.get("consensus_no_vig_prob")); p=_num(r.get("model_probability"))
        raw=_selection_probability(r,"raw_sim_probability_p1")
        target=_num(r.get("strength_conditioning_target_p1")); achieved=_num(r.get("strength_conditioning_achieved_p1"))
        if target is not None and achieved is not None: conditioning_miss.append(abs(target-achieved))
        if q is None or p is None: continue
        compression.append(abs(q-0.5)-abs(p-0.5))
        if q < 0.5:
            dog_delta.append(p-q)
            if raw is not None: raw_dog_delta.append(raw-q)
        elif q > 0.5:
            fav_delta.append(p-q)
        if raw is not None: calibrated_minus_raw.append(p-raw)

    total_rows=board[(board["market_group"]=="total_games") & board["model_probability"].notna()].copy()
    total_bets=bets[bets["market_group"]=="total_games"]
    total_actionable=actionable[actionable["market_group"]=="total_games"]
    total_main_bets=main_bets[main_bets["market_group"]=="total_games"]
    total_main_actionable=main_actionable[main_actionable["market_group"]=="total_games"]

    main_delta=[]
    if not total_rows.empty:
        seen=set()
        for _, r in total_rows.iterrows():
            if not _is_main(r.get("main_line")): continue
            line=_num(r.get("line")); exp=_num(r.get("expected_total"))
            key=(str(r.get("fixture_id")),line)
            if line is None or exp is None or key in seen: continue
            seen.add(key); main_delta.append(exp-line)

    payload={
        "purpose":"diagnostic only; no side-balance target is used in model fitting or signal selection",
        "market_snapshot_utc":snapshot.isoformat(),
        "fixture_count":int(board["fixture_id"].nunique()) if not board.empty else 0,
        "board_rows":int(len(board)),
        "main_line_rows":int(len(main_board)),
        "errors":errors,
        "model_version":sorted(board["model_version"].dropna().unique().tolist()) if not board.empty else [],
        "best_of_counts":{str(k):int(v) for k,v in board.groupby("fixture_id")["best_of"].first().value_counts().items()} if not board.empty else {},
        "moneyline":{
            "priced_rows":int(len(ml)),
            "bet_side_counts":selected_side_counts(bets,"moneyline"),
            "actionable_side_counts":selected_side_counts(actionable,"moneyline"),
            "mean_model_minus_market_underdog_pp":None if _mean(dog_delta) is None else 100*_mean(dog_delta),
            "mean_model_minus_market_favorite_pp":None if _mean(fav_delta) is None else 100*_mean(fav_delta),
            "mean_raw_sim_minus_market_underdog_pp":None if _mean(raw_dog_delta) is None else 100*_mean(raw_dog_delta),
            "mean_calibrated_minus_raw_selected_probability_pp":None if _mean(calibrated_minus_raw) is None else 100*_mean(calibrated_minus_raw),
            "mean_compression_toward_50_pp":None if _mean(compression) is None else 100*_mean(compression),
            "mean_strength_conditioning_target_miss_pp":None if _mean(conditioning_miss) is None else 100*_mean(conditioning_miss),
        },
        "spreads":{
            "all_lines_bet_side_counts_via_moneyline":selected_side_counts(bets,"game_spread"),
            "all_lines_actionable_side_counts_via_moneyline":selected_side_counts(actionable,"game_spread"),
            "main_line_bet_side_counts_via_moneyline":selected_side_counts(main_bets,"game_spread"),
            "main_line_actionable_side_counts_via_moneyline":selected_side_counts(main_actionable,"game_spread"),
            "main_line_bet_fixtures":int(main_bets.loc[main_bets["market_group"]=="game_spread","fixture_id"].nunique()),
        },
        "totals":{
            "priced_rows":int(len(total_rows)),
            "all_lines_bet_side_counts":dict(Counter(total_bets["selection"].astype(str).str.lower())),
            "all_lines_actionable_side_counts":dict(Counter(total_actionable["selection"].astype(str).str.lower())),
            "main_line_bet_side_counts":dict(Counter(total_main_bets["selection"].astype(str).str.lower())),
            "main_line_actionable_side_counts":dict(Counter(total_main_actionable["selection"].astype(str).str.lower())),
            "main_line_bet_fixtures":int(total_main_bets["fixture_id"].nunique()),
            "mean_expected_total_minus_market_main_line_games":_mean(main_delta),
            "main_line_fixture_count":len(main_delta),
        },
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8")
    print(json.dumps(payload,indent=2,default=str))


if __name__ == "__main__":
    main()
