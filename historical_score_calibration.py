from __future__ import annotations

import math
import re
from io import StringIO

import pandas as pd
import requests

from refresh_tennismylife_cloud import get_manifest, manifest_lookup
from v5_settlement import VOID_MARKERS, canonical_name, parse_score_games


def canonical_date(value) -> str:
    text = str(value or "").split(".")[0]
    if re.fullmatch(r"\d{8}", text):
        parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    else:
        parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else parsed.date().isoformat()


def result_key(date, winner, loser):
    return canonical_date(date), canonical_name(winner), canonical_name(loser)


def score_games(score):
    text = str(score or "")
    if any(marker in text.upper() for marker in VOID_MARKERS):
        return None
    return parse_score_games(text)


def build_result_index(results: pd.DataFrame) -> dict:
    out = {}
    if results is None or results.empty:
        return out
    for _, row in results.iterrows():
        parsed = score_games(row.get("score"))
        if parsed is None:
            continue
        winner_games, loser_games = parsed
        key = result_key(row.get("tourney_date"), row.get("winner_name"), row.get("loser_name"))
        item = {
            "actual_total": int(winner_games + loser_games),
            "actual_margin": int(winner_games - loser_games),
            "winner_games": int(winner_games),
            "loser_games": int(loser_games),
            "tournament": row.get("tourney_name") or row.get("tournament") or "",
            "score": row.get("score"),
        }
        if key in out and out[key] != item:
            # Refuse an ambiguous same-date/name duplicate rather than silently choose.
            out[key] = None
        else:
            out[key] = item
    return {key: value for key, value in out.items() if value is not None}


def load_historical_results(years=(2025, 2026)):
    lookup = manifest_lookup(get_manifest())
    requested = []
    for year in years:
        requested.extend([
            f"{year}.csv",
            f"{year}_challenger.csv",
            f"{year}_atp_quali.csv",
            f"{year}_wta.csv",
        ])
    frames = []
    loaded = []
    missing = []
    for name in requested:
        meta = lookup.get(name.lower())
        if not meta:
            missing.append(name)
            continue
        response = requests.get(meta["url"], timeout=120)
        response.raise_for_status()
        df = pd.read_csv(StringIO(response.text), low_memory=False)
        required = {"tourney_date", "winner_name", "loser_name", "score"}
        if not required.issubset(df.columns):
            missing.append(name + ":missing_score_columns")
            continue
        df["_source_file"] = name
        frames.append(df)
        loaded.append({"file": name, "rows": int(len(df))})
    combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    return combined, loaded, missing


def matched_walkforward_scores(walkforward: pd.DataFrame, result_lookup: dict) -> pd.DataFrame:
    rows = []
    if walkforward is None or walkforward.empty:
        return pd.DataFrame()
    for _, row in walkforward.iterrows():
        result = result_lookup.get(result_key(row.get("date"), row.get("winner"), row.get("loser")))
        if not result:
            continue
        try:
            p_w = float(row.get("winner_serve_p"))
            p_l = float(row.get("loser_serve_p"))
            p_elo = float(row.get("elo_winner_p"))
        except Exception:
            continue
        if not all(math.isfinite(x) and 0 < x < 1 for x in (p_w, p_l, p_elo)):
            continue
        rows.append({
            "date": pd.Timestamp(row.get("date")),
            "surface": str(row.get("surface") or "Hard"),
            "level": row.get("level"),
            "winner": row.get("winner"),
            "loser": row.get("loser"),
            "winner_serve_p": p_w,
            "loser_serve_p": p_l,
            "elo_winner_p": p_elo,
            **result,
        })
    return pd.DataFrame(rows)
