"""Cross-check the two results sources and report coverage (v5_market_results).

Usage:  python scripts/check_results_sources.py [--out docs/experiments/data/results_sources.json]

Where TennisMyLife and Kalshi both settle a stored fixture they must name the same winner;
any disagreement points to a matching error on one side and is listed. Also reports winner
coverage by family and by day of the edition (qualifying days come first) for each source
and combined, and the Kalshi markets not tied to any fixture.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from v5_market_results import kalshi_winners, load_fixture_winners, load_kalshi_markets  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/experiments/data/results_sources.json")
    args = ap.parse_args()
    fx = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False)
                    for p in sorted((BASE / "market_history" / "fixtures").glob("*.csv"))]).drop_duplicates("fixture_id")
    fx = fx[fx["resolution"] == "ok"].reset_index(drop=True)
    tml = load_fixture_winners(fx, BASE, sources=("tennismylife",))
    markets = load_kalshi_markets(BASE)
    kal = kalshi_winners(markets)
    kal = kal[kal["fixture_id"].isin(fx["fixture_id"])]
    both = tml.merge(kal, on="fixture_id", suffixes=("_tml", "_kalshi"))
    disagree = both[both["winner_side_tml"] != both["winner_side_kalshi"]]
    combined = load_fixture_winners(fx, BASE)

    # A larger overlap that needs no prices: every fixture a Kalshi market is tied to,
    # identified straight from the fixture registry.
    from v5_fixture_resolution import FixtureResolver
    resolver = FixtureResolver.from_repo(BASE)
    ids = sorted(set(markets.loc[markets["fixture_id"] != "", "fixture_id"]))
    reg = pd.DataFrame([{"fixture_id": i, **resolver.identify(i)} for i in ids])
    reg_tml = load_fixture_winners(reg, BASE, sources=("tennismylife",))
    reg_kal = kalshi_winners(markets)
    reg_both = reg_tml.merge(reg_kal, on="fixture_id", suffixes=("_tml", "_kalshi"))
    reg_disagree = reg_both[reg_both["winner_side_tml"] != reg_both["winner_side_kalshi"]]

    fx["family"] = fx["edition_key"].str.split("|").str[0]
    fx["day"] = (pd.to_datetime(fx["start_time_utc"], utc=True).dt.tz_localize(None).dt.normalize()
                 - pd.to_datetime(fx["edition_key"].str.split("|").str[1])).dt.days.clip(-3, 7)
    fx["month"] = fx["cutoff_utc"].str[:7]
    kalshi_months = fx[fx["fixture_id"].isin(markets["fixture_id"])]["month"].unique()
    window = fx[fx["month"].isin(kalshi_months)]
    cov = lambda frame, ids: round(float(frame["fixture_id"].isin(ids).mean()), 3) if len(frame) else None
    report = {
        "fixtures_resolved": int(len(fx)),
        "tennismylife_winners": int(len(tml)), "kalshi_winners": int(len(kal)), "combined": int(len(combined)),
        "overlap": int(len(both)), "disagreements": int(len(disagree)),
        "disagreement_rows": disagree.merge(fx[["fixture_id", "edition_key", "player1_id", "player2_id", "start_time_utc"]],
                                            on="fixture_id").to_dict("records"),
        "registry_overlap": {"kalshi_fixtures": int(len(ids)), "resolved": int((reg["resolution"] == "ok").sum()) if len(reg) else 0,
                             "both_sources": int(len(reg_both)), "disagreements": int(len(reg_disagree)),
                             "disagreement_rows": reg_disagree.merge(reg, on="fixture_id").to_dict("records")},
        "kalshi_markets": int(len(markets)), "kalshi_markets_unmatched": int((markets["fixture_id"] == "").sum()),
        "kalshi_settlements": markets["result"].value_counts().to_dict(),
        "coverage_in_kalshi_months": {
            "months": sorted(kalshi_months),
            "by_family": {f: {"fixtures": int(len(g)), "tennismylife": cov(g, tml["fixture_id"]),
                              "kalshi": cov(g, kal["fixture_id"]), "combined": cov(g, combined["fixture_id"])}
                          for f, g in window.groupby("family")},
            "by_day": {int(d): {"fixtures": int(len(g)), "combined": cov(g, combined["fixture_id"])}
                       for d, g in window.groupby("day")},
        },
        "coverage_all_months_combined": {f: cov(g, combined["fixture_id"]) for f, g in fx.groupby("family")},
    }
    out = BASE / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("disagreement_rows", "coverage_in_kalshi_months")},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
