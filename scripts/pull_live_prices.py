"""Live pre-match prices for the day's upcoming fixtures (v5_live_prices; spec §2.3, §5.3).

Usage:  python scripts/pull_live_prices.py [--max-minutes 5] [--hours-ahead 24]

Runs inside the existing live workflow (oddspapi_normalized_daily_v2.yml), after it has
refreshed the fixture registry. One free /historical-odds call per relevant fixture that
starts in the next 24 hours (soonest first; one call per 5 s; at most 3 books), storing the
price standing now for Pinnacle, Bet365 and BetRivers. It does not use the request quota, so
it also runs on days the quota-limited live pull is skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))
os.chdir(BASE)
from pull_market_history import COOLDOWN, META, REGISTRY, Api  # noqa: E402
from pull_oddspapi_quota_aware import relevant_fixture  # noqa: E402
from v5_live_prices import LIVE_DIR, append_live, live_quotes  # noqa: E402
from v5_market_history import DEFAULT_BOOKS, _as_fixture  # noqa: E402

MIN_LEAD_MINUTES = 10


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=float, default=5)
    ap.add_argument("--hours-ahead", type=float, default=24)
    args = ap.parse_args()
    key = os.environ.get("ODDSPAPI_KEY")
    if not key:
        raise SystemExit("ODDSPAPI_KEY is not set")
    if not META.exists():
        raise SystemExit(f"{META.name} is missing: the workflow restores it from the Actions cache")
    meta = json.loads(META.read_text(encoding="utf-8"))
    api, started, now = Api(key), time.time(), datetime.now(timezone.utc)
    reg = pd.read_csv(REGISTRY, dtype=str, keep_default_na=False)
    start = pd.to_datetime(reg["start_time_utc"], utc=True, errors="coerce")
    soon = reg[(start > now + timedelta(minutes=MIN_LEAD_MINUTES)) & (start <= now + timedelta(hours=args.hours_ahead))
               & (reg["true_start_time_utc"] == "")]
    soon = soon[pd.Series([relevant_fixture(_as_fixture(r)) for r in soon.to_dict("records")], index=soon.index, dtype=bool)]
    soon = soon.assign(_s=start[soon.index]).sort_values("_s")
    books = ",".join(DEFAULT_BOOKS)
    counts, frames = {}, []
    for fx in soon.to_dict("records"):
        if time.time() - started > args.max_minutes * 60:
            break
        status, body = api.get("historical-odds", fixtureId=fx["fixture_id"], bookmakers=books)
        fetched = datetime.now(timezone.utc)
        if status == 200:
            q = live_quotes(body, fx, meta, fetched)
            frames.append(q)
            counts["ok"] = counts.get("ok", 0) + 1
        else:
            counts[str(status)] = counts.get(str(status), 0) + 1
        time.sleep(COOLDOWN)
    rows = append_live(pd.concat(frames, ignore_index=True), BASE) if frames else 0
    result = {"run_utc": now.isoformat(timespec="seconds"), "upcoming": int(len(soon)), "calls": counts,
              "rows": rows, "minutes": round((time.time() - started) / 60, 1)}
    (BASE / LIVE_DIR).mkdir(parents=True, exist_ok=True)
    (BASE / LIVE_DIR / "run_status.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
