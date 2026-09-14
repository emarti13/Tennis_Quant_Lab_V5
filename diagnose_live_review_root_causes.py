from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from v5_live_market import canonical_name

BASE = Path(__file__).resolve().parent
BOARD = BASE / "v5_daily_ready" / "latest_board.csv"
FORECASTS = BASE / "v5_daily_ready" / "daily_forecasts.csv"
CONTEXT = BASE / "context_warehouse" / "player_match_rows.parquet"
WTA_RATINGS = BASE / "v5_wta_ratings.csv"
MEN_RATINGS = BASE / "v5_men_ratings.csv"
OUT = BASE / "docs" / "experiments" / "2026-09-14-live-review-root-cause.json"


def pricing_signal(row) -> str:
    ev = pd.to_numeric(pd.Series([row.get("expected_value")]), errors="coerce").iloc[0]
    edge = pd.to_numeric(pd.Series([row.get("edge_vs_consensus")]), errors="coerce").iloc[0]
    if pd.isna(ev) or pd.isna(edge):
        return "N/A"
    if float(ev) >= 0.05 and float(edge) >= 0.025:
        return "BET"
    if float(ev) >= 0.02 and float(edge) >= 0.01:
        return "LEAN"
    return "PASS"


def review_reason(row) -> str:
    if str(row.get("signal", "")).upper() != "REVIEW":
        return "NOT_REVIEW"
    base = pricing_signal(row)
    if base not in {"BET", "LEAN"}:
        return "OTHER_OR_LEGACY"
    enabled = row.get("production_market_enabled")
    if pd.notna(enabled) and str(enabled).strip().lower() in {"false", "0", "no"}:
        return "SCORE_MARKET_NOT_PROMOTED"
    conf = pd.to_numeric(pd.Series([row.get("state_confidence")]), errors="coerce").iloc[0]
    if pd.notna(conf) and float(conf) < 0.45:
        return "STATE_CONFIDENCE_LT_45"
    if str(row.get("surface_source", "")) == "Auto default — review":
        return "SURFACE_AUTO_DEFAULT_REVIEW"
    return "UNEXPLAINED_REVIEW"


def historical_surface_lookup(context: pd.DataFrame, tournament: str) -> dict:
    if context.empty:
        return {"rows": 0, "surfaces": {}, "names": []}
    name_col = next((c for c in ("tourney_name", "tournament", "event_name") if c in context.columns), None)
    if not name_col or "surface" not in context.columns:
        return {"rows": 0, "surfaces": {}, "names": []}
    t = canonical_name(tournament)
    tokens = [x for x in t.split() if x not in {"atp", "wta", "men", "women", "singles", "challenger"}]
    if not tokens:
        return {"rows": 0, "surfaces": {}, "names": []}
    names = context[name_col].fillna("").astype(str)
    canon = names.map(canonical_name)
    mask = pd.Series(True, index=context.index)
    for token in tokens[:3]:
        mask &= canon.str.contains(token, regex=False)
    sub = context.loc[mask, [name_col, "surface"]].copy()
    return {
        "rows": int(len(sub)),
        "surfaces": {str(k): int(v) for k, v in sub["surface"].fillna("MISSING").value_counts().to_dict().items()},
        "names": [str(x) for x in sub[name_col].dropna().astype(str).drop_duplicates().head(10).tolist()],
    }


def rating_detail(path: Path, player: str, surface: str) -> dict:
    if not path.exists():
        return {"found": False}
    df = pd.read_csv(path, low_memory=False)
    if "player" not in df.columns:
        return {"found": False}
    target = canonical_name(player)
    mask = df["player"].map(canonical_name).eq(target)
    if "surface" in df.columns:
        mask &= df["surface"].astype(str).str.title().eq(str(surface).title())
    if not mask.any():
        return {"found": False}
    r = df.loc[mask].iloc[-1]
    fields = [
        "player", "surface", "form_matches", "surface_form_matches", "global_points", "surface_points",
        "state_confidence", "state_confidence_label", "form_logit", "day_vol_logit", "vol_percentile",
    ]
    out = {"found": True}
    for field in fields:
        if field in r.index:
            value = r.get(field)
            out[field] = None if pd.isna(value) else (float(value) if isinstance(value, (int, float)) else str(value))
    return out


def main() -> int:
    board = pd.read_csv(BOARD, low_memory=False) if BOARD.exists() else pd.DataFrame()
    forecasts = pd.read_csv(FORECASTS, low_memory=False) if FORECASTS.exists() else pd.DataFrame()
    context = pd.read_parquet(CONTEXT) if CONTEXT.exists() else pd.DataFrame()

    if board.empty:
        payload = {"status": "missing_board"}
    else:
        board = board.copy()
        board["diagnostic_pricing_signal"] = [pricing_signal(r) for _, r in board.iterrows()]
        board["review_reason"] = [review_reason(r) for _, r in board.iterrows()]
        reviews = board[board["signal"].astype(str).str.upper().eq("REVIEW")].copy()
        actionable_before_review = board[board["diagnostic_pricing_signal"].isin(["BET", "LEAN"])].copy()
        tournaments = []
        for tournament, group in board.groupby("tournament", dropna=False):
            reasons = group["review_reason"].value_counts().to_dict()
            surf_source = group.get("surface_source", pd.Series(dtype=object)).fillna("").astype(str).value_counts().to_dict()
            tournaments.append({
                "tournament": str(tournament),
                "rows": int(len(group)),
                "signals": {str(k): int(v) for k, v in group["signal"].fillna("MISSING").value_counts().to_dict().items()},
                "review_reasons": {str(k): int(v) for k, v in reasons.items() if k != "NOT_REVIEW"},
                "surface_sources": {str(k): int(v) for k, v in surf_source.items()},
                "historical_surface_evidence": historical_surface_lookup(context, str(tournament)),
            })

        low_conf_fixtures = []
        for fixture_id, group in board.groupby("fixture_id", sort=False):
            conf = pd.to_numeric(group.get("state_confidence"), errors="coerce").min()
            if pd.isna(conf) or conf >= 0.45:
                continue
            first = group.iloc[0]
            tour = str(first.get("tour_v5") or first.get("tour") or "").upper()
            ratings = WTA_RATINGS if tour == "WTA" else MEN_RATINGS
            surface = str(first.get("surface") or "Hard")
            p1 = str(first.get("resolved_player1") or first.get("player1") or "")
            p2 = str(first.get("resolved_player2") or first.get("player2") or "")
            low_conf_fixtures.append({
                "fixture_id": str(fixture_id),
                "tournament": str(first.get("tournament")),
                "state_confidence_min": float(conf),
                "player1": rating_detail(ratings, p1, surface),
                "player2": rating_detail(ratings, p2, surface),
            })

        payload = {
            "status": "ok",
            "board_rows": int(len(board)),
            "review_rows": int(len(reviews)),
            "pricing_actionable_rows_before_review_gates": int(len(actionable_before_review)),
            "review_reason_counts": {str(k): int(v) for k, v in reviews["review_reason"].value_counts().to_dict().items()},
            "surface_auto_default_review_rows": int(board.get("surface_source", pd.Series(dtype=object)).astype(str).eq("Auto default — review").sum()),
            "low_confidence_rows": int(pd.to_numeric(board.get("state_confidence"), errors="coerce").lt(0.45).sum()),
            "production_market_disabled_rows": int(board.get("production_market_enabled", pd.Series(dtype=object)).astype(str).str.lower().eq("false").sum()),
            "tournaments": tournaments,
            "low_confidence_fixtures": low_conf_fixtures,
            "forecast_rows": int(len(forecasts)),
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
