from __future__ import annotations

from hashlib import sha256
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse
import json
import re

import pandas as pd
import requests

from v5_context_schema import MATCH_COLUMNS, PLAYER_MATCH_COLUMNS, SCHEMA_VERSION
from v5_settlement import canonical_name, parse_score_games


SLAM_TOKENS = ("australian open", "roland garros", "french open", "wimbledon", "us open")
HISTORY_SUFFIXES = ("", "_atp_quali", "_challenger", "_wta")
RAW_STAT_SUFFIXES = {
    "ace": "aces",
    "df": "double_faults",
    "svpt": "service_points",
    "1stIn": "first_serves_in",
    "1stWon": "first_serve_points_won",
    "2ndWon": "second_serve_points_won",
    "bpSaved": "break_points_saved",
    "bpFaced": "break_points_faced",
}


def _manifest_basename(item: dict) -> str:
    name = str(item.get("name") or "").replace("\\", "/").split("/")[-1]
    if name:
        return name.lower()
    return Path(urlparse(str(item.get("url") or "")).path).name.lower()


def resolve_history_targets(files: list[dict], years: tuple[int, ...] | list[int]) -> dict[str, dict]:
    lookup = {_manifest_basename(item): item for item in files if isinstance(item, dict) and item.get("url")}
    resolved: dict[str, dict] = {}
    for year in years:
        for suffix in HISTORY_SUFFIXES:
            name = f"{int(year)}{suffix}.csv"
            if name.lower() in lookup:
                resolved[name] = lookup[name.lower()]
    return resolved


def load_tennismylife_history(years=(2025, 2026)) -> tuple[pd.DataFrame, dict]:
    from refresh_tennismylife_cloud import get_manifest

    files = get_manifest()
    targets = resolve_history_targets(files, years=tuple(int(y) for y in years))
    expected = {f"{int(y)}{suffix}.csv" for y in years for suffix in HISTORY_SUFFIXES}
    missing = sorted(expected - set(targets))
    frames = []
    loaded = []
    failed = []
    source_columns: dict[str, list[str]] = {}
    for local_name, meta in targets.items():
        try:
            response = requests.get(meta["url"], timeout=120)
            response.raise_for_status()
            df = pd.read_csv(StringIO(response.text), low_memory=False)
        except Exception as exc:
            failed.append({"file": local_name, "error": type(exc).__name__})
            continue
        required = {"winner_name", "loser_name", "tourney_date", "score"}
        if not required.issubset(df.columns):
            failed.append({"file": local_name, "error": "missing_required_columns"})
            continue
        if "tourney_name" not in df.columns:
            df["tourney_name"] = ""
        df["result_file"] = local_name
        frames.append(df)
        source_columns[local_name] = list(df.columns)
        loaded.append({"file": local_name, "rows": int(len(df))})

    out = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    if not out.empty:
        out = out[out["winner_name"].notna() & out["loser_name"].notna()].copy()
        keys = [c for c in ["tourney_id", "match_num", "winner_name", "loser_name", "score"] if c in out.columns]
        if keys:
            out = out.drop_duplicates(keys, keep="last")
    detail = {
        "requested_years": [int(y) for y in years],
        "loaded": loaded,
        "missing": missing,
        "failed": failed,
        "stat_column_coverage": {
            file_name: sorted([c for c in cols if c.startswith(("w_", "l_"))])
            for file_name, cols in source_columns.items()
        },
    }
    return out, detail


def _parse_date(value) -> pd.Timestamp:
    text = str(value or "").split(".")[0]
    if re.fullmatch(r"\d{8}", text):
        return pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    return pd.to_datetime(value, errors="coerce")


def _infer_tour(result_file: str) -> str:
    return "WTA" if "wta" in str(result_file or "").lower() else "MEN"


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


def _score_set_count(score) -> int | None:
    tokens = re.findall(r"\b\d+-\d+(?:\([^)]*\))?", str(score or ""))
    return len(tokens) if tokens else None


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
        record = {
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
            "total_sets": _score_set_count(row.get("score")),
            "match_duration_minutes": row.get("minutes") if "minutes" in row.index else row.get("duration_minutes"),
            "result_file": row.get("result_file"),
            "source_quality": "exact_result_row",
            "winner_rank": row.get("winner_rank"),
            "loser_rank": row.get("loser_rank"),
        }
        for prefix in ("w", "l"):
            for source_suffix, canonical_suffix in RAW_STAT_SUFFIXES.items():
                record[f"raw_{prefix}_{canonical_suffix}"] = row.get(f"{prefix}_{source_suffix}")
        records.append(record)
    out = pd.DataFrame(records)
    if out.empty:
        return pd.DataFrame(columns=MATCH_COLUMNS)
    out["match_date"] = pd.to_datetime(out["match_date"], errors="coerce")
    numeric_columns = [
        "match_num", "best_of", "winner_games", "loser_games", "total_games", "total_sets",
        "match_duration_minutes", "winner_rank", "loser_rank",
    ] + [c for c in out.columns if c.startswith(("raw_w_", "raw_l_"))]
    for col in numeric_columns:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.sort_values(["match_date", "tour", "tourney_name", "match_id"], kind="stable").reset_index(drop=True)
    return out.drop_duplicates("match_id", keep="last").reset_index(drop=True)


def _player_raw_stats(match: pd.Series, prefix: str) -> dict:
    return {
        f"stat_{canonical_suffix}": match.get(f"raw_{prefix}_{canonical_suffix}")
        for canonical_suffix in RAW_STAT_SUFFIXES.values()
    }


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
        raw_history = {
            "match_games": match.get("total_games"),
            "match_sets": match.get("total_sets"),
            "match_duration_minutes": match.get("match_duration_minutes"),
        }
        rows.append({
            **base, **raw_history, **_player_raw_stats(match, "w"),
            "player_name": match.get("winner_name"),
            "opponent_name": match.get("loser_name"),
            "player_role": "winner",
            "player_rank": match.get("winner_rank"),
            "opponent_rank": match.get("loser_rank"),
        })
        rows.append({
            **base, **raw_history, **_player_raw_stats(match, "l"),
            "player_name": match.get("loser_name"),
            "opponent_name": match.get("winner_name"),
            "player_role": "loser",
            "player_rank": match.get("loser_rank"),
            "opponent_rank": match.get("winner_rank"),
        })
    out = pd.DataFrame(rows)
    out["match_date"] = pd.to_datetime(out["match_date"], errors="coerce")
    for col in [c for c in out.columns if c.startswith("stat_")] + [
        "match_games", "match_sets", "match_duration_minutes", "player_rank", "opponent_rank"
    ]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.sort_values(["match_date", "match_id", "player_role"], kind="stable").reset_index(drop=True)


def build_context_warehouse(base_dir: str = ".", years=(2025, 2026)) -> dict[str, object]:
    base = Path(base_dir)
    out_dir = base / "context_warehouse"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw, source_detail = load_tennismylife_history(years=years)
    if raw.empty:
        raise RuntimeError("No TennisMyLife historical result rows available; refusing to create an empty warehouse")
    matches = normalize_results(raw)
    player_rows = build_player_match_rows(matches)
    matches.to_parquet(out_dir / "matches.parquet", index=False)
    player_rows.to_parquet(out_dir / "player_match_rows.parquet", index=False)
    stat_cols = [c for c in player_rows.columns if c.startswith("stat_")]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": "TennisMyLife manifest historical season files",
        "source_detail": source_detail,
        "raw_rows": int(len(raw)),
        "match_rows": int(len(matches)),
        "player_match_rows": int(len(player_rows)),
        "tour_counts": {str(k): int(v) for k, v in matches["tour"].value_counts().to_dict().items()},
        "year_counts": {str(int(k)): int(v) for k, v in matches["match_date"].dt.year.value_counts().sort_index().to_dict().items() if pd.notna(k)},
        "stat_non_null_counts": {c: int(player_rows[c].notna().sum()) for c in stat_cols},
        "date_min": str(matches["match_date"].min()),
        "date_max": str(matches["match_date"].max()),
    }
    schema = {
        "schema_version": SCHEMA_VERSION,
        "grain": {"matches": "one row per canonical singles match", "player_match_rows": "two rows per match, one per player"},
        "match_columns": list(matches.columns),
        "player_match_columns": list(player_rows.columns),
        "feature_namespace": "feature_* is reserved for pre-first-serve information only; raw target-match outcomes/stats may exist outside that namespace solely to become lagged history for later rows",
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
