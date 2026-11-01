"""Market price store: open, close and checkpoint prices per fixture, book and selection.

Rebuild plan Step 3; spec docs/superpowers/specs/2026-10-16-market-data-layer-design.md
(§2.1, §2.2, §5). Prices only, never model output: the store keeps every relevant fixture
OddsPapi has history for, whether or not any model priced it.

From one /historical-odds payload (every price change per book, market, outcome) this
module derives, for each selection:

- open: first active quote before the start;
- close: last active quote strictly before the start. "Start" is the true start when
  OddsPapi has reported it, else the scheduled start (`cutoff_source` says which);
- checkpoints: the quote standing at T-24 h, T-12 h, T-6 h and T-1 h;
- `close_valid_until`: when that close stopped standing. OddsPapi records changes only, so
  a close set hours early still stood at the start unless the book withdrew it (an
  inactive record). `close_gap_min` is the time from that withdrawal to the start.

Spec §5.4 (user, 2026-10-16): for edge and CLV measurement a close whose book stopped
quoting more than 60 minutes before the start counts as missing (`close_stale`). The
close is still stored.

Stored per start month, append-only: market_history/fixtures/YYYY-MM.csv (one row per
fixture: start, cutoff, our edition and player ids) and market_history/price_points/YYYY-MM.csv
(the moneyline, plus the main game handicap and the main total games line per book, the
line closest to even). Raw payloads go to a monthly GitHub release (decision D3), not git.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from historical_odds_normalizer import flatten_history
from normalize_oddspapi_snapshot import market_group, normalize_selection, normalized_line, outcome_lookup

STORE_DIR = Path("market_history")
POINTS_DIR = STORE_DIR / "price_points"
FIXTURES_DIR = STORE_DIR / "fixtures"
PULL_LOG = STORE_DIR / "pull_log.csv"
CHECKPOINT_HOURS = (24, 12, 6, 1)
STALE_CLOSE_MINUTES = 60
GROUPS = ("moneyline", "game_spread", "total_games")
# Spec §5.1: Pinnacle is information; Bet365 and BetRivers are execution books.
DEFAULT_BOOKS = ("pinnacle", "bet365", "betrivers")

FIXTURE_COLUMNS = [
    "fixture_id", "start_time_utc", "true_start_time_utc", "cutoff_utc", "cutoff_source",
    "tournament_id", "tournament_name", "edition_key", "participant1_id", "participant2_id",
    "player1_id", "player2_id", "resolution", "source", "pulled_utc",
]
POINT_COLUMNS = [
    "fixture_id", "bookmaker", "market_group", "market_id", "outcome_id", "player_key", "side", "line",
    "open_price", "open_utc",
    "close_price", "close_utc", "close_valid_until", "close_gap_min", "close_stale",
    *[c for h in CHECKPOINT_HOURS for c in (f"t{h}h_price", f"t{h}h_utc")],
    "quotes", "pre_start_quotes",
]
KEY = ["fixture_id", "bookmaker", "market_id", "outcome_id", "player_key"]
LOG_COLUMNS = ["fixture_id", "start_time_utc", "books", "mode", "status", "http_status",
               "quotes", "point_rows", "pulled_utc", "detail"]
DONE_STATUSES = {"ok", "not_found"}


def _ts(value) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() in ("", "nan", "NaT"):
        return None
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _iso(t) -> str:
    return pd.Timestamp(t).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ") if t is not None else ""


def close_cutoff(fixture: dict) -> tuple[pd.Timestamp, str]:
    """True start if known, else scheduled start. Raises without either (fail closed)."""
    true_start = _ts(fixture.get("true_start_time_utc"))
    if true_start is not None:
        return true_start, "true_start"
    scheduled = _ts(fixture.get("start_time_utc"))
    if scheduled is None:
        raise ValueError(f"fixture {fixture.get('fixture_id')} has no start time")
    return scheduled, "scheduled_start"


def _standing(quotes: list[dict], at: pd.Timestamp) -> dict | None:
    """The quote standing at `at`: the latest record at or before it, if that record is active."""
    last = None
    for q in quotes:
        if q["created_at"] > at:
            break
        last = q
    return last if last is not None and last["active"] is not False else None


def selection_points(quotes: list[dict], cutoff: pd.Timestamp) -> dict:
    """Open, close, checkpoints and close staleness for one selection's quotes (sorted by time)."""
    pre = [q for q in quotes if q["created_at"] < cutoff]
    active_pre = [q for q in pre if q["active"] is not False]
    out = {"quotes": len(quotes), "pre_start_quotes": len(pre)}
    first, last = (active_pre[0], active_pre[-1]) if active_pre else (None, None)
    out["open_price"], out["open_utc"] = (first["price_decimal"], _iso(first["created_at"])) if first else (None, "")
    out["close_price"], out["close_utc"] = (last["price_decimal"], _iso(last["created_at"])) if last else (None, "")
    if last is not None:
        withdrawn = next((q for q in pre if q["created_at"] > last["created_at"] and q["active"] is False), None)
        until = withdrawn["created_at"] if withdrawn else cutoff
        gap = (cutoff - until).total_seconds() / 60
        out.update(close_valid_until=_iso(until), close_gap_min=round(gap, 1), close_stale=gap > STALE_CLOSE_MINUTES)
    else:
        out.update(close_valid_until="", close_gap_min=None, close_stale=True)
    for h in CHECKPOINT_HOURS:
        q = _standing(pre, cutoff - timedelta(hours=h))
        out[f"t{h}h_price"], out[f"t{h}h_utc"] = (q["price_decimal"], _iso(q["created_at"])) if q else (None, "")
    return out


def _label(meta: dict | None, outcome_id) -> tuple[str | None, str, float | None]:
    if not meta:
        return None, "", None
    group = market_group(meta)
    if group not in GROUPS:
        return None, "", None
    side = normalize_selection(group, outcome_lookup(meta).get(str(outcome_id), ""), outcome_id, "p1", "p2")
    return group, side, normalized_line(group, meta, side, "p1", "p2")


def fixture_record(fixture: dict, *, identity: dict | None = None, source: str = "oddspapi_historical",
                   pulled_utc: str | None = None) -> dict:
    """The fixture row stored next to its price points."""
    cutoff, cutoff_source = close_cutoff(fixture)
    identity = identity or {}
    return {
        "fixture_id": fixture.get("fixture_id"), "start_time_utc": fixture.get("start_time_utc"),
        "true_start_time_utc": fixture.get("true_start_time_utc") or "", "cutoff_utc": _iso(cutoff),
        "cutoff_source": cutoff_source, "tournament_id": fixture.get("tournament_id"),
        "tournament_name": fixture.get("tournament_name"),
        "participant1_id": fixture.get("participant1_id"), "participant2_id": fixture.get("participant2_id"),
        "edition_key": identity.get("edition_key", ""), "player1_id": identity.get("player1_id", ""),
        "player2_id": identity.get("player2_id", ""), "resolution": identity.get("resolution", ""),
        "source": source, "pulled_utc": pulled_utc or _iso(pd.Timestamp.now(tz="UTC")),
    }


def price_points(payload: dict, fixture: dict, market_meta: list[dict], *, cutoff: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per (book, market, outcome, player) in the stored market groups. `cutoff`
    defaults to the fixture's start; the live pull passes the fetch time instead, so a live
    price is the same "close" computed at that moment (v5_live_prices)."""
    cutoff = cutoff if cutoff is not None else close_cutoff(fixture)[0]
    meta_by_id = {str(m.get("marketId")): m for m in market_meta}
    quotes: dict[tuple, list[dict]] = {}
    for r in flatten_history(payload or {}):
        r["created_at"] = pd.Timestamp(r["created_at"])
        quotes.setdefault((r["bookmaker"], r["market_id"], r["outcome_id"], r["player_id"]), []).append(r)
    rows = []
    for (book, market_id, outcome_id, player_key), qs in quotes.items():
        group, side, line = _label(meta_by_id.get(str(market_id)), outcome_id)
        if group is None:
            continue
        qs.sort(key=lambda q: q["created_at"])
        rows.append({
            "fixture_id": fixture.get("fixture_id"), "bookmaker": book, "market_group": group,
            "market_id": str(market_id), "outcome_id": str(outcome_id), "player_key": str(player_key),
            "side": side, "line": line, **selection_points(qs, cutoff),
        })
    return main_lines(pd.DataFrame(rows, columns=POINT_COLUMNS))


def main_lines(points: pd.DataFrame) -> pd.DataFrame:
    """Keep the moneyline, and per book only the handicap/total line closest to even."""
    if points.empty:
        return points
    keep = [points[points["market_group"] == "moneyline"]]
    for (book, group), g in points[points["market_group"] != "moneyline"].groupby(["bookmaker", "market_group"]):
        price = pd.to_numeric(g["close_price"], errors="coerce").fillna(pd.to_numeric(g["open_price"], errors="coerce"))
        both = g.assign(_p=1 / price).groupby("market_id")["_p"].agg(["count", "sum", "min", "max"])
        both = both[both["count"] == 2]
        if both.empty:
            continue
        best = (both["max"] / both["sum"] - 0.5).abs().idxmin()
        keep.append(g[g["market_id"] == best])
    return pd.concat(keep, ignore_index=True)[POINT_COLUMNS]


def _append(frame: pd.DataFrame, path: Path, columns: list[str], key: list[str]) -> int:
    existing = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=key) if path.exists() else pd.DataFrame(columns=key)
    seen = set(map(tuple, existing[key].astype(str).values))
    new = frame[[tuple(map(str, k)) not in seen for k in frame[key].values]]
    if new.empty:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    new[columns].to_csv(path, mode="a", header=not path.exists(), index=False)
    return len(new)


def append_store(points: pd.DataFrame, fixtures: list[dict] | pd.DataFrame, base: Path | str = ".") -> int:
    """Append-only, per start month: a stored fixture row or price row is never replaced."""
    base = Path(base)
    fx = pd.DataFrame(fixtures, columns=FIXTURE_COLUMNS)
    if fx.empty:
        return 0
    month = fx.set_index("fixture_id")["start_time_utc"].map(lambda s: f"{_ts(s):%Y-%m}")
    for m, chunk in fx.groupby(fx["fixture_id"].map(month)):
        _append(chunk, base / FIXTURES_DIR / f"{m}.csv", FIXTURE_COLUMNS, ["fixture_id", "source"])
    added = 0
    if not points.empty:
        for m, chunk in points.groupby(points["fixture_id"].map(month)):
            added += _append(chunk, base / POINTS_DIR / f"{m}.csv", POINT_COLUMNS, KEY)
    return added


def load_pull_log(base: Path | str = ".") -> pd.DataFrame:
    path = Path(base) / PULL_LOG
    return pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else pd.DataFrame(columns=LOG_COLUMNS)


def append_pull_log(entries: list[dict], base: Path | str = ".") -> None:
    if not entries:
        return
    path = Path(base) / PULL_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(entries, columns=LOG_COLUMNS).to_csv(path, mode="a", header=not path.exists(), index=False)


def pending_fixtures(registry: pd.DataFrame, log: pd.DataFrame, *, now, since, books: str,
                     relevant, settle_hours: float = 6, max_attempts: int = 3,
                     skip_stored: bool = False, only_stored: bool = False,
                     true_start_wait_hours: float = 72) -> pd.DataFrame:
    """Relevant fixtures that started at least `settle_hours` ago, after `since`, oldest first,
    with no finished pull for this book set. A fixture whose true start OddsPapi has not
    reported yet waits up to `true_start_wait_hours` (its close would otherwise be cut at the
    scheduled start). `skip_stored`: leave out fixtures the January-August backfill already
    holds (their points come from the stored files); `only_stored`: just those (to add a book
    the stored backfill did not ask for)."""
    now = _ts(now)
    f = registry.copy()
    known = f["true_start_time_utc"].astype(str).str.len() > 0
    f["_start"] = pd.to_datetime(f["true_start_time_utc"].where(known, f["start_time_utc"]), utc=True, errors="coerce")
    wait = pd.Timedelta(hours=settle_hours) + (~known).astype(int) * pd.Timedelta(hours=true_start_wait_hours)
    f = f[f["_start"].notna() & (f["_start"] >= _ts(since)) & (f["_start"] <= now - wait)]
    f = f[pd.Series([relevant(_as_fixture(r)) for r in f.to_dict("records")], index=f.index, dtype=bool)]
    if (skip_stored or only_stored) and "historical_status" in f:
        stored = f["historical_status"].astype(str) == "CACHED"
        f = f[stored] if only_stored else f[~stored]
    if not log.empty:
        mine = log[log["books"] == books]
        done = set(mine.loc[mine["status"].isin(DONE_STATUSES), "fixture_id"])
        tries = mine[~mine["status"].isin(DONE_STATUSES)].groupby("fixture_id").size()
        exhausted = set(tries[tries >= max_attempts].index)
        f = f[~f["fixture_id"].isin(done | exhausted)]
    return f.sort_values(["_start", "fixture_id"]).drop(columns="_start")


def _as_fixture(row: dict) -> dict:
    """Registry row -> the OddsPapi field names `relevant_fixture` reads."""
    return {"categoryName": row.get("category_name", ""), "categorySlug": row.get("category_slug", ""),
            "tournamentName": row.get("tournament_name", ""), "tournamentSlug": row.get("tournament_slug", ""),
            "participant1Name": row.get("participant1_name", ""), "participant2Name": row.get("participant2_name", "")}
