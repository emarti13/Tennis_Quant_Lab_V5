from __future__ import annotations
import pandas as pd


def _metrics(df: pd.DataFrame) -> dict:
    decisive=df[~df["outcome"].eq("PUSH")]
    wins=int(decisive["outcome"].eq("WIN").sum())
    losses=int(decisive["outcome"].eq("LOSS").sum())
    return {"decisions":int(len(decisive)),"wins":wins,"losses":losses,"pushes":int(df["outcome"].eq("PUSH").sum()),"accuracy":float(wins/len(decisive)) if len(decisive) else None}


def summarize_pair(baseline: pd.DataFrame, enhanced: pd.DataFrame) -> dict:
    out={}
    tours=sorted(set(baseline.get("tour",pd.Series(dtype=str)).astype(str)) | set(enhanced.get("tour",pd.Series(dtype=str)).astype(str)))
    for tour in tours:
        b=baseline[baseline["tour"].astype(str).eq(tour)].copy()
        e=enhanced[enhanced["tour"].astype(str).eq(tour)].copy()
        common=set(b["fixture_id"].astype(str)) & set(e["fixture_id"].astype(str))
        b=b[b["fixture_id"].astype(str).isin(common)]
        e=e[e["fixture_id"].astype(str).isin(common)]
        bm=_metrics(b); em=_metrics(e)
        delta=None if bm["accuracy"] is None or em["accuracy"] is None else 100.0*(em["accuracy"]-bm["accuracy"])
        out[tour]={"matched_fixtures":len(common),"baseline":bm,"enhanced":em,"delta_accuracy_pp":delta}
    return out
