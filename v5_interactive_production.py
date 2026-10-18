"""The app's override run (rebuild plan Step 4g): the daily board with the user's edits.

The same pricing function as the daily batch (v5_pricing.price_fixture), with the user's
edits applied as edition overrides (spec 2026-10-12 §2.6: surface, setting, best-of; only
the fields changed). With no edits the run reproduces the daily batch exactly (parity
test). Saving the edits writes context_registry/master_schedule/overrides.csv, the user's
decision file for court attributes (context_registry/DECISIONS.md).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from v5_daily_batch import eligible_pre_match, freeze_key, rank_board
from v5_fixture_resolution import OVERRIDE_COLUMNS, OVERRIDABLE
from v5_live_market import canonical_name
from v5_pricing import PricingContext, board_rows

OVERRIDES_PATH = Path("context_registry") / "master_schedule" / "overrides.csv"
# Editor column -> edition field. Tour is not editable: it follows the edition.
EDIT_FIELDS = {"Surface": "surface", "Best Of": "best_of", "Environment": "setting"}
_SIGNAL_PRIORITY = {"BET": 0, "LEAN": 1, "REVIEW": 2, "PASS": 3, "N/A": 4, "NO PRICE": 5}


def edits_to_overrides(edited: pd.DataFrame, ctx: PricingContext, *, note: str = "app override run") -> tuple[list[dict], list[dict]]:
    """(override rows, errors). One row per fixture edit that differs from what the fixture
    resolves to now; a fixture that does not resolve cannot be overridden (its error says why)."""
    rows, errors = [], []
    today = datetime.now(timezone.utc).date().isoformat()
    for r in edited.to_dict("records"):
        fid = str(r.get("Fixture ID") or "")
        try:
            resolved = ctx.resolver.resolve(fid)
        except Exception as exc:
            errors.append({"fixture_id": fid, "stage": "resolve", "error": str(exc)})
            continue
        current = {"surface": resolved.surface, "best_of": resolved.best_of, "setting": resolved.setting}
        for column, field in EDIT_FIELDS.items():
            value = r.get(column)
            if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == "":
                continue
            value = str(int(float(value))) if field == "best_of" else str(value).strip().title()
            if str(current[field]) != value:
                rows.append({"edition_key": resolved.edition_key, "field": field, "value": value, "set_on": today, "note": note})
    return rows, errors


def price_board(market_feed: pd.DataFrame, ctx: PricingContext, *, now=None) -> pd.DataFrame:
    now = now or datetime.now(timezone.utc)
    frozen_at = pd.Timestamp(now).isoformat()
    frames = [board_rows(g, ctx.price(fid), frozen_at=frozen_at)
              for fid, g in eligible_pre_match(market_feed, now=now).groupby("fixture_id", sort=False)]
    board = rank_board(pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame())
    if not board.empty:
        board["freeze_key"] = board.apply(freeze_key, axis=1)
    return board


def run_interactive_production(market_feed: pd.DataFrame, edited: pd.DataFrame, ctx: PricingContext, *, now=None):
    """(today view, errors, override rows) for the fixtures in the editor."""
    valid = edited[edited["Player 1"].notna() & edited["Player 2"].notna()].copy()
    feed = market_feed[market_feed["fixture_id"].astype(str).isin(set(valid["Fixture ID"].astype(str)))]
    overrides, errors = edits_to_overrides(valid, ctx)
    board = price_board(feed, ctx.with_overrides(overrides) if overrides else ctx, now=now)
    return production_board_to_today(board), errors, overrides


def save_overrides(rows: list[dict], base_dir=".") -> int:
    """Write the edits to the overrides decision file: one row per edition and field, the
    newest edit replacing an older one. Returns the number of rows written."""
    rows = [r for r in rows if r.get("field") in OVERRIDABLE]
    if not rows:
        return 0
    path = Path(base_dir) / OVERRIDES_PATH
    old = pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else pd.DataFrame(columns=OVERRIDE_COLUMNS)
    new = pd.DataFrame(rows, columns=OVERRIDE_COLUMNS).astype(str)
    out = pd.concat([old, new], ignore_index=True).drop_duplicates(["edition_key", "field"], keep="last")
    path.parent.mkdir(parents=True, exist_ok=True)
    out[OVERRIDE_COLUMNS].to_csv(path, index=False)
    back = pd.read_csv(path, dtype=str, keep_default_na=False)       # read back: fail loudly if it did not stick
    for r in new.itertuples():
        hit = back[(back["edition_key"] == r.edition_key) & (back["field"] == r.field)]
        if hit.empty or hit.iloc[-1]["value"] != r.value:
            raise IOError(f"override {r.edition_key}/{r.field} did not persist")
    return len(new)


def _best_market(frame: pd.DataFrame):
    if frame is None or frame.empty:
        return None
    work = frame.copy()
    work["_sig"] = work.get("signal", pd.Series("", index=work.index)).astype(str).str.upper().map(_SIGNAL_PRIORITY).fillna(9)
    work["_ev"] = pd.to_numeric(work.get("expected_value", pd.Series(index=work.index, dtype=float)), errors="coerce").fillna(float("-inf"))
    return work.sort_values(["_sig", "_ev"], ascending=[True, False], kind="stable").iloc[0]


def _fair(p):
    return None if p is None else (round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p))


FIXTURE_FIELDS = ("price_status", "price_reason", "full_context_probability_p1", "tour_v5", "surface", "surface_source",
                  "setting", "best_of", "stage", "official_eligible", "rated_matches", "model_version")


def production_board_to_today(board: pd.DataFrame, fixtures: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per fixture for the Daily Board: the model price, why there is none, and the
    best moneyline per side (after repricing). A repriced board carries the frozen model
    columns on its moneyline rows only (and none for a fixture with no price), so the
    fixture's own fields come from any row that has them, else from `fixtures` (the daily
    forecast, one row per fixture)."""
    if board is None or board.empty:
        return pd.DataFrame()
    by_fixture = {} if fixtures is None or fixtures.empty else fixtures.drop_duplicates("fixture_id").set_index(
        fixtures.drop_duplicates("fixture_id")["fixture_id"].astype(str)).to_dict("index")
    rows = []
    for fixture_id, group in board.groupby("fixture_id", sort=False, dropna=False):
        first = group.iloc[0].copy()
        known = group[group["price_status"].notna()] if "price_status" in group.columns else group.iloc[0:0]
        source = known.iloc[0].to_dict() if len(known) else by_fixture.get(str(fixture_id), {})
        for k in FIXTURE_FIELDS:
            if k in source:
                first[k] = source[k]
        p1, p2 = str(first.get("player1")), str(first.get("player2"))
        p1p = pd.to_numeric(pd.Series([first.get("full_context_probability_p1")]), errors="coerce").iloc[0]
        p1p = None if pd.isna(p1p) else float(p1p)
        row = {
            "Status": "OK" if first.get("price_status") == "priced" else str(first.get("price_reason") or "NO PRICE"),
            "Fixture ID": fixture_id, "Tournament": first.get("tournament"), "Start": first.get("start_time_utc"),
            "Tour": first.get("tour_v5"), "Surface": first.get("surface"), "Surface Source": first.get("surface_source"),
            "Best Of": first.get("best_of"), "Environment": first.get("setting") or None, "Stage": first.get("stage"),
            "Official Eligible": bool(first.get("official_eligible")) if pd.notna(first.get("official_eligible")) else False,
            "Player 1": p1, "Player 2": p2, "P1 V5 %": p1p, "P2 V5 %": None if p1p is None else 1 - p1p,
            "P1 Fair": _fair(p1p), "P2 Fair": _fair(None if p1p is None else 1 - p1p),
            "Rated Matches": first.get("rated_matches"), "Model": first.get("model_version"),
            "Note": "" if first.get("price_status") == "priced" else str(first.get("price_reason") or ""),
        }
        ml = group[group["market_group"].astype(str).str.lower().eq("moneyline")]
        for prefix, player in (("P1", p1), ("P2", p2)):
            best = _best_market(ml[ml["selection"].map(canonical_name).eq(canonical_name(player))])
            if best is not None:
                row[f"{prefix} ML"] = best.get("best_american_odds")
                row[f"{prefix} ML EV"] = best.get("expected_value")
                row[f"{prefix} ML Signal"] = best.get("signal")
        rows.append(row)
    return pd.DataFrame(rows)
