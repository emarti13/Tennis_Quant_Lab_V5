"""Research: can the last in-play prices name the winner? (user-approved 2026-10-17)

Usage:  python scripts/research_inplay_winners.py [--chunks 1-30]

For each fixture in the stored January-August backfill (oddspapi_history/chunks), take each
book's last active in-play moneyline quote per side (after the start). A book calls the
match when one side is at or below WIN_PRICE and the other at or above LOSE_PRICE; the
fixture's call is the books' common call (none if they disagree or none calls it). Compared
with TennisMyLife winners (v5_market_results), which settle main draws.
Moneyline is OddsPapi market 121, outcome 121 = participant 1, 122 = participant 2
(normalize_oddspapi_snapshot), so no market dictionary is needed.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from historical_odds_normalizer import flatten_history  # noqa: E402
from v5_market_history import close_cutoff  # noqa: E402
from v5_market_results import load_fixture_winners  # noqa: E402

WIN_PRICE, LOSE_PRICE = 1.10, 5.0


def call_winner(payload: dict, cutoff: pd.Timestamp) -> tuple[str, dict]:
    rows = [r for r in flatten_history(payload or {}) if r["market_id"] == "121" and r["outcome_id"] in ("121", "122")]
    last: dict[tuple, dict] = {}
    for r in rows:
        t = pd.Timestamp(r["created_at"])
        if t <= cutoff or r["active"] is False:
            continue
        k = (r["bookmaker"], r["outcome_id"])
        if k not in last or t > last[k]["t"]:
            last[k] = {"t": t, "p": r["price_decimal"]}
    calls = {}
    for book in {b for b, _ in last}:
        p1, p2 = last.get((book, "121"), {}).get("p"), last.get((book, "122"), {}).get("p")
        if p1 is None or p2 is None:
            calls[book] = "incomplete"
        elif p1 <= WIN_PRICE and p2 >= LOSE_PRICE:
            calls[book] = "p1"
        elif p2 <= WIN_PRICE and p1 >= LOSE_PRICE:
            calls[book] = "p2"
        else:
            calls[book] = "unclear"
    decided = {c for c in calls.values() if c in ("p1", "p2")}
    if not calls:
        return "no_inplay", calls
    if len(decided) == 1:
        return decided.pop(), calls
    return ("conflict" if len(decided) > 1 else "unclear"), calls


def strict_call(calls: dict) -> str:
    """At least two books name the same winner and no book is unclear or names the other."""
    decided = [c for c in calls.values() if c in ("p1", "p2")]
    if len(decided) >= 2 and len(set(decided)) == 1 and all(c in ("p1", "p2", "incomplete") for c in calls.values()):
        return decided[0]
    return "none"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", default="1-30")
    ap.add_argument("--out", default="docs/experiments/data/inplay_winners.json")
    args = ap.parse_args()
    lo, _, hi = args.chunks.partition("-")
    fx = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False)
                    for p in sorted((BASE / "market_history" / "fixtures").glob("*.csv"))]).drop_duplicates("fixture_id")
    fx = fx.set_index("fixture_id", drop=False)
    rows = []
    for i in range(int(lo), int(hi or lo) + 1):
        path = BASE / "oddspapi_history" / "chunks" / f"history_chunk_{i:04d}.jsonl.gz"
        if not path.exists():
            continue
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                fid = (rec.get("fixture") or {}).get("fixtureId")
                if fid not in fx.index:
                    continue
                f = fx.loc[fid].to_dict()
                call, books = call_winner(rec.get("historical_odds"), close_cutoff(f)[0])
                rows.append({"fixture_id": fid, "call": call, "strict": strict_call(books), "books": json.dumps(books)})
        print(path.name, len(rows), flush=True)
    d = pd.DataFrame(rows).merge(fx.reset_index(drop=True)[["fixture_id", "edition_key", "player1_id", "player2_id", "resolution"]], on="fixture_id")
    truth = load_fixture_winners(fx.reset_index(drop=True), BASE, sources=("tennismylife",))
    d = d.merge(truth, on="fixture_id", how="left")
    d["family"] = d["edition_key"].str.split("|").str[0]
    with_truth = d[d["winner_side"].notna()]
    called = with_truth[with_truth["call"].isin(["p1", "p2"])]
    report = {
        "fixtures": int(len(d)), "calls": d["call"].value_counts().to_dict(),
        "with_tennismylife_result": int(len(with_truth)),
        "called_among_those": int(len(called)), "coverage": round(len(called) / max(len(with_truth), 1), 4),
        "agree": int((called["call"] == called["winner_side"]).sum()),
        "disagree": int((called["call"] != called["winner_side"]).sum()),
        "agreement": round(float((called["call"] == called["winner_side"]).mean()), 5) if len(called) else None,
        "by_family": {f: {"with_result": int(len(g)), "called": int(g["call"].isin(["p1", "p2"]).sum()),
                          "agree": int((g["call"] == g["winner_side"]).sum())} for f, g in with_truth.groupby("family")},
        "without_result_called": int(d[d["winner_side"].isna()]["call"].isin(["p1", "p2"]).sum()),
        "without_result": int(d["winner_side"].isna().sum()),
        "strict": {"called": int(with_truth["strict"].isin(["p1", "p2"]).sum()),
                   "agree": int((with_truth["strict"] == with_truth["winner_side"]).sum()),
                   "disagree": int((with_truth["strict"].isin(["p1", "p2"]) & (with_truth["strict"] != with_truth["winner_side"])).sum()),
                   "without_result_called": int(d[d["winner_side"].isna()]["strict"].isin(["p1", "p2"]).sum())},
        "disagreement_rows": called[called["call"] != called["winner_side"]][["fixture_id", "edition_key", "call", "winner_side", "books"]].head(50).to_dict("records"),
    }
    d.drop(columns=["books"]).to_csv(BASE / "docs" / "experiments" / "data" / "inplay_winner_calls.csv", index=False)
    out = BASE / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "disagreement_rows"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
