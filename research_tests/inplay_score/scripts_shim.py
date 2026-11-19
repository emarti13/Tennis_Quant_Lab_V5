"""read_log and COLS from scripts/log_kalshi_live.py (branch feat/vm-runner), copied so this research
branch can read the server's live logs without that branch's code."""
from __future__ import annotations

import pandas as pd

STATS = ("points_won", "service_points_won", "service_points_lost", "first_serve_successful",
         "second_serve_successful", "first_serve_points_won", "second_serve_points_won", "aces",
         "double_faults", "breakpoints_won", "total_breakpoints", "tiebreaks_won")
COLS = (["polled_utc", "series", "event_ticker", "milestone_id", "status", "match_status", "widget_status",
         "server", "advantage", "sets_1", "sets_2", "games_1", "games_2", "points_1", "points_2",
         "round_scores_1", "round_scores_2", "competitor_1", "competitor_2"]
        + [f"{k}_{i}" for i in (1, 2) for k in STATS]
        + ["ticker_1", "bid_1", "ask_1", "ticker_2", "bid_2", "ask_2"])


def read_log(path) -> pd.DataFrame:
    """Read a live-score log, including the one day (2026-11-01) whose file mixes the 23-column
    layout (before that day's update) with the 49-column one appended without a header."""
    import csv
    import gzip
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", newline="") as f:
        rows = list(csv.reader(f))
    head, out, extra = rows[0], [], []
    for r in rows[1:]:
        (out if len(r) == len(head) else extra).append(r)
    frames = [pd.DataFrame(out, columns=head)]
    if extra and len(extra[0]) == len(COLS):
        frames.append(pd.DataFrame([r for r in extra if len(r) == len(COLS)], columns=COLS))
    df = pd.concat(frames, ignore_index=True).replace("", None)
    for c in df.columns:
        num = pd.to_numeric(df[c], errors="coerce")
        if num.notna().sum() == df[c].notna().sum():            # every value is a number
            df[c] = num
    return df
