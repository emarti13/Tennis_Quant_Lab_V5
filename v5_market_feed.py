
from __future__ import annotations
import csv
from collections import defaultdict
from pathlib import Path

NORMALIZED_DEFAULT = Path("oddspapi_normalized/normalized_markets.csv")

def load_market_rows(path=NORMALIZED_DEFAULT):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            for k in ("line","decimal_odds","raw_implied_prob","no_vig_prob","market_hold","limit"):
                if r.get(k) not in (None,"","nan","NaN"):
                    try:
                        r[k] = float(r[k])
                    except Exception:
                        pass
            rows.append(r)
    return rows

def matchup_key(a,b):
    return tuple(sorted((str(a).strip().lower(), str(b).strip().lower())))

def build_fixture_index(rows):
    out = defaultdict(list)
    for r in rows:
        out[matchup_key(r.get("player1"), r.get("player2"))].append(r)
    return out

def get_match_markets(player1, player2, rows=None):
    rows = rows if rows is not None else load_market_rows()
    return build_fixture_index(rows).get(matchup_key(player1, player2), [])

def best_price(rows, market_group, selection, line=None):
    cand=[]
    for r in rows:
        if r.get("market_group") != market_group:
            continue
        if str(r.get("selection","")).strip().lower() != str(selection).strip().lower():
            continue
        if line is not None:
            try:
                if abs(float(r.get("line")) - float(line)) > 1e-9:
                    continue
            except Exception:
                continue
        try:
            price=float(r["decimal_odds"])
        except Exception:
            continue
        cand.append((price,r))
    return max(cand,key=lambda x:x[0])[1] if cand else None

def decimal_to_american(d):
    d=float(d)
    if d >= 2:
        return round((d-1)*100)
    return round(-100/(d-1))

def expected_value(model_prob, decimal_odds):
    p=float(model_prob)
    d=float(decimal_odds)
    return p*d - 1.0

def probability_edge(model_prob, no_vig_prob):
    if no_vig_prob in (None,""):
        return None
    return float(model_prob)-float(no_vig_prob)
