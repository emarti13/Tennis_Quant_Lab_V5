
from __future__ import annotations

import csv
import glob
import json
import math
import re
from collections import defaultdict
from pathlib import Path

SNAPDIR = Path("oddspapi_daily")
META_FILE = Path("oddspapi_markets_tennis.json")
OUTDIR = Path("oddspapi_normalized")
OUTDIR.mkdir(exist_ok=True)

def latest_file(pattern):
    files=sorted(glob.glob(str(SNAPDIR/pattern)))
    if not files:
        raise FileNotFoundError(pattern)
    return Path(files[-1])

def dec_implied(x):
    try:
        x=float(x)
        return 1/x if x>1 else None
    except Exception:
        return None

def market_group(meta):
    mid=int(meta.get("marketId",-1))
    name=(meta.get("marketName") or "").lower()
    period=(meta.get("period") or "").lower()
    mtype=(meta.get("marketType") or "").lower()

    if mid == 121:
        return "moneyline"
    if "total games" in name and ("full" in period or period in ("match","fulltime","")):
        return "total_games"
    if "game handicap" in name and ("full" in period or period in ("match","fulltime","")):
        return "game_spread"

    # Documented OddsPapi tennis IDs; used only as a safe fallback if labels differ.
    if 1223 <= mid <= 1245 and mid % 2 == 1:
        return "total_games"
    if 12159 <= mid <= 12229 and mid % 2 == 1:
        return "game_spread"
    return None

def outcome_lookup(meta):
    return {str(o.get("outcomeId")): (o.get("outcomeName") or "") for o in meta.get("outcomes",[])}

def normalize_selection(group, outcome_name, outcome_id, p1, p2):
    s=(outcome_name or "").strip().lower()
    oid=int(outcome_id) if str(outcome_id).isdigit() else None

    if group == "moneyline":
        if oid == 121 or s in ("player 1","1","home"):
            return p1
        if oid == 122 or s in ("player 2","2","away"):
            return p2

    if group == "total_games":
        if "over" in s or (oid is not None and oid % 2 == 1):
            return "Over"
        if "under" in s or (oid is not None and oid % 2 == 0):
            return "Under"

    if group == "game_spread":
        if "player 1" in s or s in ("1","home") or (oid is not None and oid % 2 == 1):
            return p1
        if "player 2" in s or s in ("2","away") or (oid is not None and oid % 2 == 0):
            return p2

    return outcome_name or str(outcome_id)

def normalized_line(group, meta, selection, p1, p2):
    try:
        h=float(meta.get("handicap"))
    except Exception:
        return None
    if group == "total_games":
        return h
    if group == "game_spread":
        return h if selection == p1 else -h
    return None

def main():
    meta=json.loads(META_FILE.read_text(encoding="utf-8"))
    meta_by_id={str(m["marketId"]):m for m in meta}

    fixtures_file=latest_file("*_fixtures.json")
    fixtures=json.loads(fixtures_file.read_text(encoding="utf-8"))
    allowed={f["fixtureId"]:f for f in fixtures if int(f.get("statusId",0))==0}

    manifest_file=latest_file("*_manifest.json")
    manifest=json.loads(manifest_file.read_text(encoding="utf-8"))
    captured=manifest.get("captured_at_utc")

    odds_files=sorted(SNAPDIR.glob("*_batch*.json"))
    rows=[]

    for fp in odds_files:
        arr=json.loads(fp.read_text(encoding="utf-8"))
        for fx in arr:
            fid=fx.get("fixtureId")
            if fid not in allowed or int(fx.get("statusId",-1)) != 0:
                continue
            base=allowed[fid]
            p1=base.get("participant1Name")
            p2=base.get("participant2Name")
            for book,bdata in (fx.get("bookmakerOdds") or {}).items():
                if not bdata.get("bookmakerIsActive",True) or bdata.get("suspended",False):
                    continue
                for mid,m in (bdata.get("markets") or {}).items():
                    meta_m=meta_by_id.get(str(mid))
                    if not meta_m:
                        continue
                    group=market_group(meta_m)
                    if not group:
                        continue
                    if not m.get("marketActive",True):
                        continue
                    ol=outcome_lookup(meta_m)

                    for oid,o in (m.get("outcomes") or {}).items():
                        for _,price in (o.get("players") or {}).items():
                            if not price.get("active",False):
                                continue
                            selection=normalize_selection(group,ol.get(str(oid),""),oid,p1,p2)
                            line=normalized_line(group,meta_m,selection,p1,p2)
                            dec=price.get("price")
                            implied=dec_implied(dec)
                            rows.append({
                                "snapshot_utc":captured,
                                "fixture_id":fid,
                                "start_time_utc":base.get("startTime"),
                                "tournament_id":base.get("tournamentId"),
                                "tournament":base.get("tournamentName"),
                                "tour":base.get("categoryName"),
                                "player1":p1,
                                "player2":p2,
                                "bookmaker":book,
                                "market_group":group,
                                "market_id":int(mid),
                                "market_name":meta_m.get("marketName"),
                                "period":meta_m.get("period"),
                                "selection":selection,
                                "line":line,
                                "decimal_odds":dec,
                                "american_odds":price.get("priceAmerican"),
                                "raw_implied_prob":implied,
                                "main_line":price.get("mainLine"),
                                "changed_at":price.get("changedAt"),
                                "limit":price.get("limit"),
                            })

    # De-vig within each exact two-sided market.
    buckets=defaultdict(list)
    for i,r in enumerate(rows):
        key=(r["fixture_id"],r["bookmaker"],r["market_id"])
        buckets[key].append(i)

    for ids in buckets.values():
        probs=[rows[i]["raw_implied_prob"] for i in ids if rows[i]["raw_implied_prob"]]
        total=sum(probs)
        for i in ids:
            p=rows[i]["raw_implied_prob"]
            rows[i]["no_vig_prob"]=(p/total if p and total>0 and len(probs)>=2 else None)
            rows[i]["market_hold"]=(total-1 if total>0 and len(probs)>=2 else None)

    fields=list(rows[0].keys()) if rows else []
    csv_path=OUTDIR/"normalized_markets.csv"
    with csv_path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    (OUTDIR/"normalized_markets.json").write_text(
        json.dumps(rows,indent=2,default=str),encoding="utf-8"
    )

    # One row per offered selection with best currently available decimal price.
    best={}
    for r in rows:
        key=(r["fixture_id"],r["market_group"],r["selection"],r["line"])
        cur=best.get(key)
        if cur is None or float(r["decimal_odds"]) > float(cur["decimal_odds"]):
            best[key]=r

    best_rows=list(best.values())
    best_path=OUTDIR/"best_prices.csv"
    with best_path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        w.writerows(best_rows)

    summary={
        "snapshot_utc":captured,
        "fixtures_in_slate":len(allowed),
        "normalized_rows":len(rows),
        "best_price_rows":len(best_rows),
        "books":sorted({r["bookmaker"] for r in rows}),
        "moneyline_fixtures_by_book":{},
        "total_games_fixtures_by_book":{},
        "game_spread_fixtures_by_book":{},
    }
    for book in summary["books"]:
        for group,key in (
            ("moneyline","moneyline_fixtures_by_book"),
            ("total_games","total_games_fixtures_by_book"),
            ("game_spread","game_spread_fixtures_by_book"),
        ):
            summary[key][book]=len({r["fixture_id"] for r in rows if r["bookmaker"]==book and r["market_group"]==group})

    (OUTDIR/"normalization_summary.json").write_text(
        json.dumps(summary,indent=2),encoding="utf-8"
    )
    print(json.dumps(summary,indent=2))

if __name__=="__main__":
    main()
