#!/usr/bin/env python3
"""
Research diagnostic: check fatigue_v1 ordering rules against real OddsPapi start/end times.

    python diagnose_fatigue_ordering_vs_clock.py            # repo layout (.v5_history_cache + v5_results_ready)
    python diagnose_fatigue_ordering_vs_clock.py <bundle>/02_upstream_daily_sources

Exit code 1 if any pair is counted "before" while the clock says it happened after (leak risk).
"""
import os
import sys

import pandas as pd

import v5_fatigue_features as F
import v5_fatigue_validation as V


def main(path="."):
    bundle = os.path.isdir(os.path.join(path, "historical_rating_aggregates"))
    m = F.load_matches(path) if bundle else F.load_repo_matches(path)
    fixtures = pd.read_csv(os.path.join(path, "oddspapi_registry", "fixtures.csv"), low_memory=False)
    r = V.clock_check(m, fixtures)
    print(f"clock-timed matches: {r['timed_matches']}; same-player pairs checked: {r['pairs']}")
    print(f"rule says BEFORE but clock says AFTER (leak risk): {r['leak_risk']}")
    for s in r["leak_examples"][:10]:
        print("   ", s)
    print(f"clock says before but rule leaves it out (safe information loss): {r['missed']} {dict(r['missed_kinds'])}")
    return 1 if r["leak_risk"] else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
