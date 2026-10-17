"""Measure the stage rule (v5_fixture_stage) against TennisMyLife.

Usage:  python scripts/check_fixture_stage.py [--out docs/experiments/data/fixture_stage.json]

TennisMyLife publishes main draws only for Challengers and the WTA, so a stored Challenger or
WTA fixture with a TennisMyLife result is main draw and one without (in a month TennisMyLife
covers) is, almost always, qualifying. Reports, per family, how many main-draw fixtures the
rule labels main (kept for official recommendations) and how many qualifying ones it lets
through, plus the same for fixtures Kalshi describes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from v5_fixture_stage import edition_levels, fixture_stages  # noqa: E402
from v5_market_results import load_fixture_winners  # noqa: E402

UNTIL = "2026-10-01"   # leave the latest weeks out: TennisMyLife lags


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/experiments/data/fixture_stage.json")
    args = ap.parse_args()
    fx = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False)
                    for p in sorted((BASE / "market_history" / "fixtures").glob("*.csv"))]).drop_duplicates("fixture_id")
    fx = fx[(fx["resolution"] == "ok") & (fx["cutoff_utc"] < UNTIL)].reset_index(drop=True)
    kpath = sorted((BASE / "market_history" / "kalshi" / "markets").glob("*.csv"))
    kalshi = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in kpath]) if kpath else None
    fmap = BASE / "market_history" / "kalshi" / "fixture_map.csv"
    if kalshi is not None and fmap.exists():
        m = pd.read_csv(fmap, dtype=str, keep_default_na=False).set_index("ticker")["fixture_id"]
        kalshi["fixture_id"] = kalshi["ticker"].map(m).fillna(kalshi["fixture_id"])
    schedule = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False)
                          for p in sorted((BASE / "context_registry" / "master_schedule" / "reconciliation").glob("*/master_schedule.csv"))])
    stages = fixture_stages(fx, kalshi, edition_levels(schedule))
    truth = load_fixture_winners(fx, BASE, sources=("tennismylife",))
    d = fx.merge(stages, on="fixture_id")
    d["family"] = d["edition_key"].str.split("|").str[0]
    d["truth"] = d["fixture_id"].isin(truth["fixture_id"]).map({True: "main", False: "qualifying"})
    report = {"until": UNTIL, "by_family": {}}
    for fam, g in d[d["family"].isin(["CHALLENGER", "WTA"])].groupby("family"):
        t = pd.crosstab(g["stage"], g["truth"])
        main_total = int((g["truth"] == "main").sum())
        kept = int(t.loc["main", "main"]) if "main" in t.index and "main" in t.columns else 0
        leaked = int(t.loc["main", "qualifying"]) if "main" in t.index and "qualifying" in t.columns else 0
        report["by_family"][fam] = {
            "fixtures": int(len(g)), "main_draw_truth": main_total, "main_labelled_main": kept,
            "main_draw_kept_share": round(kept / main_total, 4) if main_total else None,
            "qualifying_labelled_main": leaked,
            "qualifying_share_of_labelled_main": round(leaked / max(kept + leaked, 1), 4),
            "table": {s: {k: int(v) for k, v in row.items()} for s, row in t.to_dict("index").items()},
            "by_source": g.groupby("stage_source").size().to_dict(),
        }
    k = d[d["stage_source"] == "kalshi"]
    report["kalshi_labelled"] = {f: {s: {k2: int(v) for k2, v in row.items()} for s, row in pd.crosstab(g["stage"], g["truth"]).to_dict("index").items()}
                                 for f, g in k.groupby("family")}
    out = BASE / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
