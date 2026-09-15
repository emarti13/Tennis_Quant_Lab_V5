from __future__ import annotations
import pandas as pd
from historical_fixture_matcher import canonical_name


def _grade(value: float) -> str:
    if value == 0:
        return "PUSH"
    return "WIN" if value > 0 else "LOSS"


def _primary_per_book(g: pd.DataFrame) -> pd.DataFrame:
    """Choose each book's most balanced offered line before forming consensus."""
    x=g.copy()
    if "bookmaker" not in x.columns:
        return x
    p=pd.to_numeric(x.get("no_vig_prob"),errors="coerce")
    x["_balance"]=(p-.5).abs().fillna(999.0)
    # Stable fallback when no-vig probability is unavailable: first observed line.
    return x.sort_values(["bookmaker","_balance"],kind="stable").groupby("bookmaker",sort=False).head(1)


def consensus_spread(rows: pd.DataFrame) -> pd.DataFrame:
    """One player-A primary line per book, then median closing handicap per fixture."""
    if rows.empty:
        return pd.DataFrame(columns=["fixture_id","tour","line","outcome"])
    out=[]
    for fid,g in rows.groupby("fixture_id",sort=False):
        target=canonical_name(g.iloc[0]["player_a"])
        a=g[g["selection"].map(canonical_name).eq(target)]
        if a.empty:
            continue
        primary=_primary_per_book(a)
        line=float(primary["line"].median()); r=a.iloc[0]
        pred=float(r["pred_margin_a"])+line
        actual=float(r["actual_margin_a"])+line
        graded=actual if pred >= 0 else -actual
        out.append({"fixture_id":fid,"tour":r["tour"],"line":line,"outcome":_grade(graded)})
    return pd.DataFrame(out)


def consensus_total(rows: pd.DataFrame) -> pd.DataFrame:
    """One primary total per book, then median closing total per fixture."""
    if rows.empty:
        return pd.DataFrame(columns=["fixture_id","tour","line","outcome"])
    out=[]
    for fid,g in rows.groupby("fixture_id",sort=False):
        # Total snapshots contain over and under rows. Collapse each book/market to
        # one representative row first, then choose that book's most balanced market.
        x=g.copy()
        if "market_id" in x.columns:
            x=x.sort_index().groupby(["bookmaker","market_id"],sort=False).head(1)
        primary=_primary_per_book(x)
        line=float(primary["line"].median()); r=g.iloc[0]
        pred=float(r["pred_total"])-line; actual=float(r["actual_total"])-line
        if actual == 0:
            outcome="PUSH"
        else:
            outcome="WIN" if ((pred > 0) == (actual > 0)) else "LOSS"
        out.append({"fixture_id":fid,"tour":r["tour"],"line":line,"outcome":outcome})
    return pd.DataFrame(out)
