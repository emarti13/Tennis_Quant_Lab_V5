"""One-off: save the shapes of Kalshi's public market data for tennis match markets."""
import json, time
from pathlib import Path
import requests

K = "https://api.elections.kalshi.com/trade-api/v2"
out = {}
def get(path, **p):
    r = requests.get(f"{K}{path}", params=p, timeout=30)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:300])

for series in ("KXATPMATCH", "KXWTAMATCH", "KXATPCHALLENGERMATCH", "KXWTACHALLENGERMATCH"):
    s, m = get("/markets", series_ticker=series, status="settled", limit=200)
    markets = (m or {}).get("markets", []) if isinstance(m, dict) else []
    out[series] = {"status": s, "settled_seen": len(markets), "cursor": bool(isinstance(m, dict) and m.get("cursor"))}
    if not markets:
        continue
    mk = max(markets, key=lambda x: float(x.get("volume_fp") or 0))
    out[series]["market"] = mk
    s, ev = get(f"/events/{mk['event_ticker']}")
    out[series]["event"] = ev
    close = int(time.mktime(time.strptime(mk["close_time"][:19], "%Y-%m-%dT%H:%M:%S")))
    opn = int(time.mktime(time.strptime(mk["open_time"][:19], "%Y-%m-%dT%H:%M:%S")))
    s, c = get(f"/series/{series}/markets/{mk['ticker']}/candlesticks", start_ts=opn, end_ts=close, period_interval=1)
    cs = (c or {}).get("candlesticks", []) if isinstance(c, dict) else []
    out[series]["candles_1m"] = {"status": s, "n": len(cs), "first": cs[:2], "last": cs[-1:], "error": None if s == 200 else c}
    s, t = get("/markets/trades", ticker=mk["ticker"], limit=1000)
    tr = (t or {}).get("trades", []) if isinstance(t, dict) else []
    out[series]["trades"] = {"status": s, "n_first_page": len(tr), "cursor": bool(isinstance(t, dict) and t.get("cursor")),
                             "newest": tr[:2], "oldest_on_page": tr[-1:]}
    time.sleep(0.5)
Path("research").mkdir(exist_ok=True)
Path("research/kalshi_shapes.json").write_text(json.dumps(out, indent=1, default=str))
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk in ("status", "settled_seen")} for k, v in out.items()}))
