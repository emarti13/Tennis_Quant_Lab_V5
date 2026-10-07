#!/usr/bin/env python3
import json, logging, math, sys
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist

import ccxt
import numpy as np
import pandas as pd

@dataclass
class Cfg:
    exchange: str = "coinbase"
    symbol: str = "BTC/USD"
    history_days: int = 1100
    fee: float = 0.001
    slippage: float = 0.0005
    allow_short: bool = False
    holdout_frac: float = 0.15
    wf_train_days: int = 365
    wf_test_days: int = 90
    min_n_train: int = 200
    min_n_fold: int = 40
    min_folds: int = 3
    min_fold_pos_frac: float = 0.6
    min_n_pooled: int = 150
    min_n_holdout: int = 40
    alpha: float = 0.05
    delay_slippage: float = 0.0005
    vol_pctl: float = 80.0
    stop_loss: float = 0.01

CFG = Cfg()
WINDOWS_FILE = Path("windows.json")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("coinbase-discover")

def wilson_lb(wins, n, z):
    if n == 0:
        return 0.0
    p = wins / n
    d = 1 + z*z/n
    centre = p + z*z/(2*n)
    adj = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return (centre-adj)/d

def sample_stats(r):
    n=len(r)
    if n == 0:
        return None
    wins=int((r>0).sum())
    W=r[r>0].mean() if wins else 0.0
    L=-r[r<=0].mean() if wins < n else 0.0
    return dict(n=n,wins=wins,p=wins/n,W=float(W),L=float(L),mean=float(r.mean()))

def breakeven_p(W,L):
    return L/(W+L) if (W+L)>0 else 1.0

def make_exchange():
    cls=getattr(ccxt, CFG.exchange)
    return cls({"enableRateLimit":True})

def fetch_hourly(ex, days):
    since=ex.milliseconds()-days*86_400_000
    rows=[]
    calls=0
    while since < ex.milliseconds():
        batch=ex.fetch_ohlcv(CFG.symbol,"1h",since=since,limit=300)
        calls += 1
        if not batch:
            break
        rows += batch
        nxt=batch[-1][0]+3_600_000
        if nxt <= since:
            raise RuntimeError(f"pagination stalled: since={since}, last={batch[-1][0]}")
        since=nxt
    df=pd.DataFrame(rows,columns=["ts","o","h","l","c","v"]).drop_duplicates("ts").sort_values("ts")
    df["dt"]=pd.to_datetime(df["ts"],unit="ms",utc=True)
    df["hour"]=df["dt"].dt.hour
    log.info("fetch calls=%d raw_rows=%d unique_rows=%d", calls, len(rows), len(df))
    return df.reset_index(drop=True)

def simulate_returns(df, direction):
    o,c,h,l=df["o"],df["c"],df["h"],df["l"]
    entry_cost=CFG.slippage+CFG.delay_slippage
    stop_slip=2*CFG.slippage
    if direction==1:
        entry=o*(1+entry_cost)
        exit_close=c*(1-CFG.slippage)
        stop_level=entry*(1-CFG.stop_loss)
        stop_px=stop_level*(1-stop_slip)
        stopped=l<=stop_level
    else:
        entry=o*(1-entry_cost)
        exit_close=c*(1+CFG.slippage)
        stop_level=entry*(1+CFG.stop_loss)
        stop_px=stop_level*(1+stop_slip)
        stopped=h>=stop_level
    exit_px=exit_close.where(~stopped,stop_px)
    ratio=exit_px/entry
    net=direction*(ratio-1)-CFG.fee*(1+ratio)
    lr=np.log(df["c"]).diff()
    roll=lr.rolling(24).std()
    thr=roll.rolling(720,min_periods=200).quantile(CFG.vol_pctl/100)
    allowed=roll.shift(1)<=thr.shift(1)
    return net.where(allowed)

def find_windows(df):
    dirs=(1,-1) if CFG.allow_short else (1,)
    n_tests=24*len(dirs)
    z=NormalDist().inv_cdf(1-CFG.alpha/n_tests)
    nets={d:simulate_returns(df,d) for d in dirs}
    hours=df["hour"].values
    wf_end=int(len(df)*(1-CFG.holdout_frac))
    tr_len,te_len=CFG.wf_train_days*24,CFG.wf_test_days*24
    folds={}
    start=0
    fold_ranges=[]
    while start+tr_len+te_len<=wf_end:
        a,b,c=start,start+tr_len,start+tr_len+te_len
        fold_ranges.append((a,b,c))
        for d in dirs:
            net=nets[d]
            for hour in range(24):
                mh=hours==hour
                st=sample_stats(net.iloc[a:b][mh[a:b]].dropna())
                if not st or st["n"]<CFG.min_n_train:
                    continue
                if not (st["mean"]>0 and st["p"]>breakeven_p(st["W"],st["L"])):
                    continue
                te=net.iloc[b:c][mh[b:c]].dropna()
                if len(te)>=CFG.min_n_fold:
                    folds.setdefault((hour,d),[]).append(te)
        start += te_len
    log.info("walk-forward region rows=%d holdout rows=%d folds=%d", wf_end, len(df)-wf_end, len(fold_ranges))

    candidates=[]
    for (hour,d),parts in sorted(folds.items()):
        if len(parts)<CFG.min_folds:
            continue
        st=sample_stats(pd.concat(parts))
        if st["n"]<CFG.min_n_pooled or st["mean"]<=0:
            continue
        be=breakeven_p(st["W"],st["L"])
        lb=wilson_lb(st["wins"],st["n"],z)
        pos=float(np.mean([p.mean()>0 for p in parts]))
        ok=lb>be and pos>=CFG.min_fold_pos_frac
        log.info("h=%02d dir=%+d folds=%d OOS n=%d p=%.3f lb=%.3f be=%.3f mean=%.4f%% folds+=%.0f%% %s",
                 hour,d,len(parts),st["n"],st["p"],lb,be,st["mean"]*100,pos*100,"CANDIDATE" if ok else "-")
        if ok:
            candidates.append(dict(hour=hour,direction=d,p_lb=float(lb),W=st["W"],L=st["L"],
                                   breakeven=float(be),oos_p=st["p"],oos_mean=st["mean"],
                                   oos_n=st["n"],folds=len(parts),fold_pos_frac=pos))
    found=[]
    for w in candidates:
        m=hours==w["hour"]
        st=sample_stats(nets[w["direction"]].iloc[wf_end:][m[wf_end:]].dropna())
        ok=bool(st and st["n"]>=CFG.min_n_holdout and st["mean"]>0 and st["p"]>w["breakeven"])
        log.info("HOLDOUT veto h=%02d n=%s p=%s mean=%s -> %s",
                 w["hour"],st and st["n"],st and round(st["p"],3),
                 st and round(st["mean"],6),"PASS" if ok else "VETO")
        if ok:
            w.update(holdout_n=st["n"],holdout_p=st["p"],holdout_mean=st["mean"])
            found.append(w)
    return found

def main():
    ex=make_exchange()
    ex.load_markets()
    if CFG.symbol not in ex.markets:
        raise SystemExit(f"{CFG.symbol} not found on Coinbase")

    smoke=fetch_hourly(ex,2)
    gaps=smoke["ts"].diff().dropna()
    bad=gaps[gaps!=3_600_000]
    print("SMOKE",json.dumps({
        "candles":len(smoke),
        "first":str(smoke.dt.iloc[0]),
        "last":str(smoke.dt.iloc[-1]),
        "duplicates":int(smoke.ts.duplicated().sum()),
        "non_hourly_gaps":int(len(bad))
    }))
    if len(smoke)<24 or smoke.ts.duplicated().sum() or len(bad):
        raise SystemExit("Coinbase smoke test failed")

    df=fetch_hourly(ex,CFG.history_days).iloc[:-1].reset_index(drop=True)
    need=int((CFG.wf_train_days+CFG.wf_test_days*CFG.min_folds)*24/(1-CFG.holdout_frac))
    if len(df)<need:
        raise SystemExit(f"Need at least {need} hourly candles; got {len(df)}")

    gaps=df["ts"].diff().dropna()
    bad=gaps[gaps!=3_600_000]
    diag={
        "candles":len(df),
        "first":str(df.dt.iloc[0]),
        "last":str(df.dt.iloc[-1]),
        "duplicates":int(df.ts.duplicated().sum()),
        "non_hourly_gaps":int(len(bad)),
        "min_required":need,
        "fee_per_side":CFG.fee,
        "slippage_per_side":CFG.slippage,
        "delay_slippage":CFG.delay_slippage
    }
    Path("coinbase_data_diagnostics.json").write_text(json.dumps(diag,indent=2))
    print("FULL_DATA",json.dumps(diag))
    if df.ts.duplicated().sum():
        raise SystemExit("Duplicate timestamps in full history")
    if len(bad):
        print("WARNING: full history contains non-hourly gaps; first gap ms:",bad.head(20).tolist())

    found=find_windows(df)
    WINDOWS_FILE.write_text(json.dumps(found,indent=2))
    print("DISCOVERED_WINDOWS",len(found))
    print(json.dumps(found,indent=2))

if __name__=="__main__":
    main()
