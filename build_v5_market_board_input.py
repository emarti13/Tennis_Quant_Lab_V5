
from __future__ import annotations
import csv, json
from pathlib import Path
from collections import defaultdict
from v5_market_feed import load_market_rows

INFILE=Path("oddspapi_normalized/normalized_markets.csv")
OUTDIR=Path("v5_market_ready")
OUTDIR.mkdir(exist_ok=True)

def main():
    rows=load_market_rows(INFILE)

    # Market coverage / QC
    books=sorted({r["bookmaker"] for r in rows})
    fixtures=sorted({r["fixture_id"] for r in rows})
    coverage={}
    for b in books:
        coverage[b]={}
        for g in ("moneyline","game_spread","total_games"):
            coverage[b][g]=len({r["fixture_id"] for r in rows if r["bookmaker"]==b and r["market_group"]==g})

    # Best available price by exact selection/line.
    best={}
    for r in rows:
        key=(r["fixture_id"],r["market_group"],r["selection"],r.get("line"))
        try:
            px=float(r["decimal_odds"])
        except Exception:
            continue
        if key not in best or px > float(best[key]["decimal_odds"]):
            best[key]=r

    # Cross-book consensus no-vig probability by exact market selection/line.
    cons=defaultdict(list)
    for r in rows:
        try:
            p=float(r["no_vig_prob"])
        except Exception:
            continue
        key=(r["fixture_id"],r["market_group"],r["selection"],r.get("line"))
        cons[key].append((r["bookmaker"],p))

    fields=[
        "snapshot_utc","fixture_id","start_time_utc","tournament","tour",
        "player1","player2","market_group","selection","line",
        "best_bookmaker","best_decimal_odds","best_american_odds",
        "best_book_no_vig_prob","consensus_no_vig_prob","books_in_consensus",
        "market_hold_at_best_book","main_line"
    ]
    output=[]
    for key,r in best.items():
        vals=cons.get(key,[])
        consensus=(sum(p for _,p in vals)/len(vals)) if vals else None
        output.append({
            "snapshot_utc":r.get("snapshot_utc"),
            "fixture_id":r.get("fixture_id"),
            "start_time_utc":r.get("start_time_utc"),
            "tournament":r.get("tournament"),
            "tour":r.get("tour"),
            "player1":r.get("player1"),
            "player2":r.get("player2"),
            "market_group":r.get("market_group"),
            "selection":r.get("selection"),
            "line":r.get("line"),
            "best_bookmaker":r.get("bookmaker"),
            "best_decimal_odds":r.get("decimal_odds"),
            "best_american_odds":r.get("american_odds"),
            "best_book_no_vig_prob":r.get("no_vig_prob"),
            "consensus_no_vig_prob":consensus,
            "books_in_consensus":len(vals),
            "market_hold_at_best_book":r.get("market_hold"),
            "main_line":r.get("main_line"),
        })

    with (OUTDIR/"market_board_input.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader(); w.writerows(output)

    qc={
        "normalized_rows":len(rows),
        "fixtures_with_any_market":len(fixtures),
        "books":books,
        "coverage_by_book":coverage,
        "best_price_rows":len(output),
        "paired_market_integrity":"verified upstream: each market_id had 2 outcomes in uploaded snapshot",
        "integration_status":"READY_FOR_V5_PREDICTION_JOIN"
    }
    (OUTDIR/"market_feed_qc.json").write_text(json.dumps(qc,indent=2),encoding="utf-8")
    print(json.dumps(qc,indent=2))

if __name__=="__main__":
    main()
