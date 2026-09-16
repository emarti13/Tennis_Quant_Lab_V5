from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

from v5_results_reset import filter_since_reset, load_reset_timestamp

MARKETS = {"moneyline": "Moneyline", "game_spread": "Spread", "total_games": "Totals"}
TOURS = ("ATP", "WTA", "Challenger", "All")
SIGNALS = ("BET", "LEAN", "REVIEW", "PASS", "Overall")


def load_tracking_ledger(base_dir: str | Path = ".") -> pd.DataFrame:
    base = Path(base_dir)
    path = base / "v5_daily_ready" / "frozen_predictions.csv"
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, low_memory=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    reset = load_reset_timestamp(base / "v5_daily_ready" / "results_reset.json")
    return filter_since_reset(df, reset, timestamp_columns=("frozen_at_utc", "snapshot_utc", "start_time_utc"))


def tour_bucket(row) -> str:
    raw = " ".join(str(row.get(c) or "") for c in ("tour", "tour_v5", "tournament")).lower()
    if "challenger" in raw:
        return "Challenger"
    if "wta" in raw or "women" in raw:
        return "WTA"
    return "ATP"


def _cell(frame: pd.DataFrame) -> dict:
    if frame is None or frame.empty:
        return {"Win Rate": np.nan, "W-L": "0-0", "N": 0, "Units": 0.0, "ROI": np.nan}
    result = frame["settled_result"].fillna("").astype(str).str.upper()
    decided = result.isin(["WIN", "LOSS"])
    wins = int((result == "WIN").sum()); losses = int((result == "LOSS").sum())
    n = wins + losses
    units = pd.to_numeric(frame.loc[decided, "profit_units"], errors="coerce").fillna(0.0).sum() if "profit_units" in frame.columns else 0.0
    return {"Win Rate": wins / n if n else np.nan, "W-L": f"{wins}-{losses}", "N": n, "Units": float(units), "ROI": float(units / n) if n else np.nan}


def tracking_matrix(df: pd.DataFrame, market_group: str) -> pd.DataFrame:
    columns = pd.MultiIndex.from_product([SIGNALS, ("Win Rate", "W-L", "N", "Units", "ROI")])
    out = pd.DataFrame(index=TOURS, columns=columns, dtype=object)
    if df is None or df.empty:
        source = pd.DataFrame()
    else:
        status = df.get("result_status", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper()
        result = df.get("settled_result", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.upper()
        group = df.get("market_group", pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.lower()
        source = df.loc[status.eq("SETTLED") & result.isin(["WIN", "LOSS", "PUSH"]) & group.eq(market_group)].copy()
        if not source.empty:
            source["_tour_bucket"] = source.apply(tour_bucket, axis=1)
            source["_signal"] = source.get("signal", pd.Series(index=source.index, dtype=object)).fillna("").astype(str).str.upper()
    for tour in TOURS:
        tour_rows = source if tour == "All" else source[source.get("_tour_bucket", pd.Series(index=source.index, dtype=object)).eq(tour)]
        for signal in SIGNALS:
            rows = tour_rows if signal == "Overall" else tour_rows[tour_rows.get("_signal", pd.Series(index=tour_rows.index, dtype=object)).eq(signal)]
            values = _cell(rows)
            for stat, value in values.items(): out.loc[tour, (signal, stat)] = value
    out.index.name = "Tour"
    return out


def tracking_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {label: tracking_matrix(df, key) for key, label in MARKETS.items()}


def render_tracking_tables(st_module, df: pd.DataFrame, *, heading="Market tracking by tour and signal") -> None:
    st_module.markdown(f"### {heading}")
    st_module.caption("Live post-reset settlement tracking. Each cell reports Win Rate, W-L, N, Units and ROI. Pushes are zero-unit outcomes and are excluded from the win-rate denominator.")
    for label, table in tracking_tables(df).items():
        st_module.markdown(f"#### {label}")
        st_module.dataframe(table.style.format({col: ("{:.1%}" if col[1] in {"Win Rate", "ROI"} else "{:+.2f}" if col[1] == "Units" else "{}") for col in table.columns}), use_container_width=True)
