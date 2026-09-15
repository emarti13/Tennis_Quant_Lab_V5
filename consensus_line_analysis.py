from __future__ import annotations
import pandas as pd


def _grade(value: float) -> str:
    if value == 0:
        return "PUSH"
    return "WIN" if value > 0 else "LOSS"


def consensus_spread(rows: pd.DataFrame) -> pd.DataFrame:
    """Collapse spread quotes to one median player-A closing handicap per fixture."""
    if rows.empty:
        return pd.DataFrame(columns=["fixture_id","tour","line","outcome"])
    out=[]
    for fid,g in rows.groupby("fixture_id",sort=False):
        a=g[g["selection"].astype(str).eq(g["player_a"].astype(str))]
        if a.empty:
            continue
        line=float(a["line"].median()); r=a.iloc[0]
        pred=float(r["pred_margin_a"])+line
        actual=float(r["actual_margin_a"])+line
        # If A is not predicted to cover, select B at the opposite consensus handicap.
        graded=actual if pred >= 0 else -actual
        out.append({"fixture_id":fid,"tour":r["tour"],"line":line,"outcome":_grade(graded)})
    return pd.DataFrame(out)


def consensus_total(rows: pd.DataFrame) -> pd.DataFrame:
    """Collapse total quotes to one median closing total per fixture."""
    if rows.empty:
        return pd.DataFrame(columns=["fixture_id","tour","line","outcome"])
    out=[]
    for fid,g in rows.groupby("fixture_id",sort=False):
        line=float(g["line"].median()); r=g.iloc[0]
        pred=float(r["pred_total"])-line; actual=float(r["actual_total"])-line
        if actual == 0:
            outcome="PUSH"
        else:
            outcome="WIN" if ((pred > 0) == (actual > 0)) else "LOSS"
        out.append({"fixture_id":fid,"tour":r["tour"],"line":line,"outcome":outcome})
    return pd.DataFrame(out)
