from __future__ import annotations

from datetime import datetime, timezone
import re
import unicodedata
from io import StringIO
from pathlib import Path
import json

import pandas as pd
import requests

VOID_MARKERS = ("RET", "W/O", "WO", "WALKOVER", "DEF", "DEFAULT", "ABD", "ABANDONED")


def canonical_name(name):
    s = "" if name is None else str(name).strip()
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()
    if "," in s:
        parts = [x.strip() for x in s.split(",", 1)]
        if len(parts) == 2 and all(parts):
            s = f"{parts[1]} {parts[0]}"
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def parse_score_games(score):
    text = str(score or "").strip()
    if not text:
        return None
    winner_games = 0
    loser_games = 0
    found = False
    for token in text.split():
        m = re.fullmatch(r"(\d+)-(\d+)(?:\([^)]*\))?", token)
        if not m:
            continue
        winner_games += int(m.group(1))
        loser_games += int(m.group(2))
        found = True
    return (winner_games, loser_games) if found else None


def _profit(result, decimal_odds):
    if result in ("PUSH", "VOID"):
        return 0.0
    if result == "LOSS":
        return -1.0
    try:
        d = float(decimal_odds)
    except Exception:
        return None
    return d - 1.0 if result == "WIN" else None


def settle_market(prediction, result):
    score = str(result.get("score", "") or "")
    if any(marker in score.upper() for marker in VOID_MARKERS):
        return {"settled_result": "VOID", "profit_units": 0.0, "winner_games": None, "loser_games": None}

    parsed = parse_score_games(score)
    if parsed is None:
        return {"settled_result": "VOID", "profit_units": 0.0, "winner_games": None, "loser_games": None}
    wg, lg = parsed
    winner = canonical_name(result.get("winner_name"))
    loser = canonical_name(result.get("loser_name"))
    selection = canonical_name(prediction.get("selection"))
    group = str(prediction.get("market_group", "")).strip().lower()
    line = pd.to_numeric(pd.Series([prediction.get("line")]), errors="coerce").iloc[0]

    settled = None
    if group == "moneyline":
        settled = "WIN" if selection == winner else ("LOSS" if selection == loser else None)
    elif group == "game_spread":
        if not pd.isna(line):
            if selection == winner:
                margin = (wg - lg) + float(line)
                settled = "WIN" if margin > 0 else ("PUSH" if abs(margin) < 1e-12 else "LOSS")
            elif selection == loser:
                margin = (lg - wg) + float(line)
                settled = "WIN" if margin > 0 else ("PUSH" if abs(margin) < 1e-12 else "LOSS")
    elif group == "total_games":
        if not pd.isna(line):
            total = wg + lg
            if selection == "over":
                settled = "WIN" if total > float(line) else ("PUSH" if total == float(line) else "LOSS")
            elif selection == "under":
                settled = "WIN" if total < float(line) else ("PUSH" if total == float(line) else "LOSS")

    if settled is None:
        return {"settled_result": None, "profit_units": None, "winner_games": wg, "loser_games": lg}
    return {
        "settled_result": settled,
        "profit_units": _profit(settled, prediction.get("best_decimal_odds")),
        "winner_games": wg,
        "loser_games": lg,
    }


def _parse_tourney_date(value):
    s = str(value or "").split(".")[0]
    if re.fullmatch(r"\d{8}", s):
        return pd.to_datetime(s, format="%Y%m%d", errors="coerce", utc=True)
    return pd.to_datetime(value, errors="coerce", utc=True)


def _tournament_overlap(a, b):
    stop = {"atp", "wta", "men", "women", "singles", "challenger", "open"}
    ta = {x for x in canonical_name(a).split() if x not in stop and len(x) > 2}
    tb = {x for x in canonical_name(b).split() if x not in stop and len(x) > 2}
    if not ta or not tb:
        return True
    return bool(ta & tb)


def match_result_row(prediction, results):
    if results is None or results.empty:
        return None
    p1 = canonical_name(prediction.get("resolved_player1") or prediction.get("player1"))
    p2 = canonical_name(prediction.get("resolved_player2") or prediction.get("player2"))
    start = pd.to_datetime(prediction.get("start_time_utc"), errors="coerce", utc=True)
    matches = []
    for _, r in results.iterrows():
        w = canonical_name(r.get("winner_name"))
        l = canonical_name(r.get("loser_name"))
        if {w, l} != {p1, p2}:
            continue
        rd = _parse_tourney_date(r.get("tourney_date"))
        if pd.notna(start) and pd.notna(rd) and abs((rd.normalize() - start.normalize()).days) > 2:
            continue
        if not _tournament_overlap(prediction.get("tournament"), r.get("tourney_name") or r.get("tournament")):
            continue
        matches.append(r)
    if len(matches) != 1:
        return None
    return matches[0]


def settle_ledger(ledger, results, settled_at=None):
    if ledger is None or ledger.empty:
        return ledger.copy(), {"settled": 0, "open": 0, "ambiguous_or_missing": 0}
    out = ledger.copy()
    settled_at = settled_at or datetime.now(timezone.utc).isoformat()
    added = [
        "settled_at_utc", "result_source", "result_tourney_date", "result_tournament",
        "result_winner", "result_loser", "result_score", "winner_games", "loser_games",
        "settlement_note",
    ]
    for c in added:
        if c not in out.columns:
            out[c] = None
    settled_count = 0
    missing = 0
    for idx, pred in out.iterrows():
        if str(pred.get("result_status", "OPEN")).upper() != "OPEN":
            continue
        r = match_result_row(pred, results)
        if r is None:
            missing += 1
            continue
        s = settle_market(pred, r)
        if not s.get("settled_result"):
            missing += 1
            continue
        out.at[idx, "result_status"] = "SETTLED"
        out.at[idx, "settled_result"] = s["settled_result"]
        out.at[idx, "profit_units"] = s["profit_units"]
        out.at[idx, "settled_at_utc"] = settled_at
        out.at[idx, "result_source"] = "TennisMyLife"
        out.at[idx, "result_tourney_date"] = r.get("tourney_date")
        out.at[idx, "result_tournament"] = r.get("tourney_name") or r.get("tournament")
        out.at[idx, "result_winner"] = r.get("winner_name")
        out.at[idx, "result_loser"] = r.get("loser_name")
        out.at[idx, "result_score"] = r.get("score")
        out.at[idx, "winner_games"] = s.get("winner_games")
        out.at[idx, "loser_games"] = s.get("loser_games")
        out.at[idx, "settlement_note"] = "automatic settlement"
        settled_count += 1
    open_count = int((out["result_status"].astype(str).str.upper() == "OPEN").sum())
    return out, {"settled": settled_count, "open": open_count, "ambiguous_or_missing": missing}


def load_tennismylife_results():
    from refresh_tennismylife_cloud import get_manifest, manifest_lookup, resolve_targets
    lookup = manifest_lookup(get_manifest())
    resolved, _ = resolve_targets(lookup)
    frames = []
    for local_name, meta in resolved.items():
        try:
            response = requests.get(meta["url"], timeout=120)
            response.raise_for_status()
            df = pd.read_csv(StringIO(response.text), low_memory=False)
        except Exception:
            continue
        required = {"winner_name", "loser_name", "tourney_date", "score"}
        if not required.issubset(df.columns):
            continue
        if "tourney_name" not in df.columns:
            df["tourney_name"] = ""
        df["result_file"] = local_name
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    out = out[out["winner_name"].notna() & out["loser_name"].notna()].copy()
    keys = [c for c in ["tourney_id", "match_num", "winner_name", "loser_name", "score"] if c in out.columns]
    if keys:
        out = out.drop_duplicates(keys, keep="last")
    return out


def main(ledger_path="v5_daily_ready/frozen_predictions.csv", summary_path="v5_daily_ready/settlement_summary.json"):
    ledger_path = Path(ledger_path)
    summary_path = Path(summary_path)
    if not ledger_path.exists():
        raise FileNotFoundError(ledger_path)
    ledger = pd.read_csv(ledger_path, low_memory=False)
    results = load_tennismylife_results()
    settled_at = datetime.now(timezone.utc).isoformat()
    updated, stats = settle_ledger(ledger, results, settled_at=settled_at)
    updated.to_csv(ledger_path, index=False)
    summary = {
        "status": "SUCCESS",
        "settled_at_utc": settled_at,
        "result_rows_loaded": int(len(results)),
        "ledger_rows": int(len(updated)),
        **stats,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
