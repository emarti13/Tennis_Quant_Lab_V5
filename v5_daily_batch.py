"""Daily board and frozen prediction ledger (rebuild plan Step 4g).

Every fixture is priced by the one pricing function (v5_pricing.price_fixture): resolution
through the master schedule and player registry, the leak-free baseline Elo with the
18-match minimum, and the stage label. A fixture that cannot be priced is kept on the board
with its reason (fail closed). The app's override run (v5_interactive_production) calls the
same function. Only the moneyline is modelled; edges, EV and signals come from repricing
against the latest prices.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

import numpy as np
import pandas as pd

from v5_live_market import canonical_name
from v5_pricing import MODEL_VERSION, RATING_STATES_PATH, PricingContext, board_rows, rating_state_rows


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
    existing = existing.copy()
    fresh = fresh.copy()
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
    out["_ev_rank"] = pd.to_numeric(out.get("expected_value", pd.Series(index=out.index, dtype=float)), errors="coerce").fillna(-999.0)
    out = out.sort_values(["_signal_rank", "_ev_rank"], ascending=[True, False], kind="stable")
    return out.drop(columns=["_signal_rank", "_ev_rank"]).reset_index(drop=True)


def infer_best_of(tournament, tour):
    """Men's Grand Slam main draws are Bo5; qualifying and all WTA are Bo3."""
    t = str(tournament or "").lower()
    category = str(tour or "").lower()
    is_men = category in {"men", "atp"} or "men" in category
    is_slam = any(name in t for name in ("australian open", "french open", "roland garros", "wimbledon", "us open"))
    is_qualifying = any(term in t for term in ("qualifying", "qualification", "qualifier"))
    return 5 if is_men and is_slam and not is_qualifying else 3


def build_daily_outputs(feed, ctx: PricingContext, existing_ledger=None, now=None):
    """(board, ledger, errors, rating_states): every pre-match fixture in the feed, priced by
    ctx, and the rating vectors each price used (saved so the app can re-price the board)."""
    now = now or datetime.now(timezone.utc)
    frozen_at = pd.Timestamp(now).isoformat()
    eligible = eligible_pre_match(feed, now=now)
    frames, errors, prices = [], [], []
    for fixture_id, group in eligible.groupby("fixture_id", sort=False):
        try:
            price = ctx.price(fixture_id)
            prices.append(price)
            frames.append(board_rows(group, price, frozen_at=frozen_at))
        except Exception as exc:          # a bug, not a no-price: recorded, never hidden
            first = group.iloc[0]
            errors.append({"fixture_id": str(fixture_id), "player1": first.get("player1"),
                           "player2": first.get("player2"), "tournament": first.get("tournament"),
                           "stage": "price_fixture", "error": f"{type(exc).__name__}: {exc}"})
    board = rank_board(pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame())
    if not board.empty:
        board["freeze_key"] = board.apply(freeze_key, axis=1)
    fresh = pd.DataFrame() if board.empty else board[pd.to_numeric(board["model_probability"], errors="coerce").notna()].copy()
    return board, merge_frozen(existing_ledger, fresh), errors, rating_state_rows(prices)


def main():
    if not MARKET_PATH.exists():
        raise FileNotFoundError(MARKET_PATH)
    feed = pd.read_csv(MARKET_PATH, low_memory=False)
    now = datetime.now(timezone.utc)
    ctx = PricingContext.from_repo(BASE, now=now)
    existing = pd.read_csv(FROZEN_LEDGER_PATH, low_memory=False) if FROZEN_LEDGER_PATH.exists() else pd.DataFrame()
    board, ledger, errors, states = build_daily_outputs(feed, ctx, existing_ledger=existing, now=now)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    board.to_csv(LATEST_BOARD_PATH, index=False)
    states.to_csv(BASE / RATING_STATES_PATH, index=False)
    ledger.to_csv(FROZEN_LEDGER_PATH, index=False)
    fixtures = board.drop_duplicates("fixture_id") if not board.empty else board
    snapshot = str(feed["snapshot_utc"].dropna().iloc[0]) if "snapshot_utc" in feed.columns and feed["snapshot_utc"].notna().any() else None
    payload = {
        "status": "SUCCESS" if not errors else "PARTIAL",
        "built_at_utc": now.isoformat(),
        "market_snapshot_utc": snapshot,
        "market_rows_input": int(len(feed)),
        "eligible_pre_match_fixtures": int(eligible_pre_match(feed, now=now)["fixture_id"].nunique()) if not feed.empty else 0,
        "priced_fixtures": int((fixtures.get("price_status") == "priced").sum()) if not board.empty else 0,
        "no_price_reasons": {str(k): int(v) for k, v in fixtures[fixtures["price_status"] != "priced"]["price_reason"].value_counts().items()} if not board.empty else {},
        "priced_rows": int(pd.to_numeric(board.get("model_probability"), errors="coerce").notna().sum()) if not board.empty else 0,
        "board_rows": int(len(board)),
        "frozen_ledger_rows": int(len(ledger)),
        "new_frozen_rows": int(len(ledger) - len(existing)),
        "errors": errors,
        "model_version": MODEL_VERSION,
        "probability_source": "v5_pricing.price_fixture: leak-free baseline Elo keyed by player_id; markets joined after the probability is frozen",
        "market_prices_used_in_model": False,
    }
    LATEST_SUMMARY_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str))
    return payload


if __name__ == "__main__":
    main()
