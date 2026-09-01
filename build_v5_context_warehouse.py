from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import re

import pandas as pd

from v5_context_schema import MATCH_COLUMNS, PLAYER_MATCH_COLUMNS, SCHEMA_VERSION
from v5_settlement import canonical_name, load_tennismylife_results, parse_score_games


SLAM_TOKENS = ("australian open", "roland garros", "french open", "wimbledon", "us open")


def _parse_date(value) -> pd.Timestamp:
    text = str(value or "").split(".")[0]
    if re.fullmatch(r"\d{8}", text):
        return pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    return pd.to_datetime(value, errors="coerce")


def _infer_tour(result_file: str) -> str:
    name = str(result_file or "").lower()
    return "WTA" if "wta" in name else "MEN"


def _infer_best_of(row: pd.Series, tour: str) -> int:
    value = pd.to_numeric(pd.Series([row.get("best_of")]), errors="coerce").iloc[0]
    if pd.notna(value) and int(value) in (3, 5):
        return int(value)
    event = str(row.get("tourney_name") or "").lower()
    round_name = str(row.get("round") or "").upper()
    is_qual = round_name.startswith("Q") or "qual" in event
    if tour == "MEN" and not is_qual and any(token in event for token in SLAM_TOKENS):
        return 5
    return 3


def _stable_match_id(row: pd.Series, tour: str, match_date: pd.Timestamp) -> str:
    p1 = canonical_name(row.get("winner_name"))
    p2 = canonical_name(row.get("loser_name"))
    pair = "|".join(sorted((p1, p2)))
    date_key = "" if pd.isna(match_date) else match_date.strftime("%Y-%m-%d")
    event = canonical_name(row.get("tourney_name"))
    provider_key = str(row.get("tourney_id") or "") + "|" + str(row.get("match_num") or "")
    raw = f"{tour}|{date_key}|{event}|{provider_key}|{pair}"
    return "m_" + sha256(raw.encode("utf-8")).hexdigest()[:24]


def normalize_results(results: pd.DataFrame) -> pd.DataFrame:
    if results is None or results.empty:
        return pd.DataFrame(columns=MATCH_COLUMNS)
    records = []
    for _, row in results.iterrows():
        winner = row.get("winner_name")
        loser = row.get("loser_name")
        if not canonical_name(winner) or not canonical_name(loser):
            continue
        tour = _infer_tour(row.get("result_file"))
        match_date = _parse_date(row.get("tourney_date"))
        parsed = parse_score_games(row.get("score"))
        wg, lg = parsed if parsed is not None else (None, None)
        records.append({
            "match_id": _stable_match_id(row, tour, match_date),
            "tour": tour,
            "match_date": match_date,
            "tourney_id": row.get("tourney_id"),
            "tourney_name": row.get("tourney_name") or row.get("tournament") or "",
            "match_num": row.get("match_num"),
            "round": row.get("round"),
            "surface": row.get("surface"),
            "best_of": _infer_best_of(row, tour),
            "winner_name": str(winner),
            "loser_name": str(loser),
            "score": row.get("score"),
            "winner_games": wg,
            "loser_games": lg,
            "total_games": None if wg is None else wg + lg,
            "result_file": row.get("result_file"),
            "source_quality": "exact_result_row",
            "winner_rank": row.get("winner_rank"),
            "loser_rank": row.get("loser_rank"),
        })
    out = pd.DataFrame(records)
    if out.empty:
        return pd.DataFrame(columns=MATCH_COLUMNS)
    out["match_date"] = pd.to_datetime(out["match_date"], errors="coerce")
    out = out.sort_values(["match_date", "tour", "tourney_name", "match_id"], kind="stable").reset_index(drop=True)
    out = out.drop_duplicates("match_id", keep="last").reset_index(drop=True)
    return out


def build_player_match_rows(matches: pd.DataFrame) -> pd.DataFrame:
    if matches is None or matches.empty:
        return pd.DataFrame(columns=PLAYER_MATCH_COLUMNS)
    rows = []
    context_cols = [
        "match_id", "tour", "match_date", "tourney_id", "tourney_name", "match_num",
        "round", "surface", "best_of", "result_file", "source_quality",
    ]
    for _, match in matches.iterrows():
        base = {c: match.get(c) for c in context_cols}
        rows.append({
            **base,
            "player_name": match.get("winner_name"),
            "opponent_name": match.get("loser_name"),
            "player_role": "winner",
            "player_rank": match.get("winner_rank"),
            "opponent_rank": match.get("loser_rank"),
        })
        rows.append({
            **base,
            "player_name": match.get("loser_name"),
            "opponent_name": match.get("winner_name"),
            "player_role": "loser",
            "player_rank": match.get("loser_rank"),
            "opponent_rank": match.get("winner_rank"),
        })
    out = pd.DataFrame(rows)
    out["match_date"] = pd.to_datetime(out["match_date"], errors="coerce")
    return out.sort_values(["match_date", "match_id", "player_role"], kind="stable").reset_index(drop=True)


def build_context_warehouse(base_dir: str = ".") -> dict[str, object]:
    base = Path(base_dir)
    out_dir = base / "context_warehouse"
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = load_tennismylife_results()
    if raw.empty:
        raise RuntimeError("No TennisMyLife result rows available; refusing to create an empty warehouse")
    matches = normalize_results(raw)
    player_rows = build_player_match_rows(matches)

    matches.to_parquet(out_dir / "matches.parquet", index=False)
    player_rows.to_parquet(out_dir / "player_match_rows.parquet", index=False)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": "TennisMyLife via existing refresh manifest",
        "raw_rows": int(len(raw)),
        "match_rows": int(len(matches)),
        "player_match_rows": int(len(player_rows)),
        "tour_counts": {str(k): int(v) for k, v in matches["tour"].value_counts().to_dict().items()},
        "date_min": str(matches["match_date"].min()),
        "date_max": str(matches["match_date"].max()),
    }
    schema = {
        "schema_version": SCHEMA_VERSION,
        "grain": {
            "matches": "one row per canonical singles match",
            "player_match_rows": "two rows per match, one per player",
        },
        "match_columns": list(matches.columns),
        "player_match_columns": list(player_rows.columns),
        "feature_namespace": "feature_* is reserved for pre-first-serve information only",
    }
    (out_dir / "source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out_dir / "schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return manifest


def main() -> int:
    build_context_warehouse(".")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
