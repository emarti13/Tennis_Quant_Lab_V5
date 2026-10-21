"""Stage 1 of run_totals.py: one row per joined match (winner/loser orientation kept only for
outcomes; every model input is re-oriented to the pre-match favourite later).

Reads (pandas only, untrusted): kaggle_data/join/joined.pkl, matches_serve.pkl, raw
.v5_history_cache/*.csv (SvGms, bp), tests/ml/cp_feats.pkl (leak-free serve/return skills and
court pace from court_pace_src.run; recomputed if missing), tests/features/features.pkl
(leak-free schedule/workload per player).
"""
from __future__ import annotations

import math
import os
import re
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, "..", ".."))
REPO = "/home/user/Tennis_Quant_Lab_V5"
SEALED = pd.Timestamp("2026-10-13")


def devig(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = (a > 1) & (b > 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = (1 / a) / (1 / a + 1 / b)
    return np.where(ok, p, np.nan)


# ------------------------------------------------------------------ first server
def parse_sets(score):
    """[(games_w, games_l, tiebreak?)] from '6-4 7-6(5)'; None if not a clean completed score."""
    if not isinstance(score, str) or re.search(r"RET|W/O|DEF|ABD|ABN|Def|unfinished|\?", score, re.I):
        return None
    out = []
    for tok in score.split():
        m = re.fullmatch(r"(\d+)-(\d+)(\(\d+\))?", tok)
        if not m:
            m2 = re.fullmatch(r"\[(\d+)-(\d+)\]", tok)       # match tiebreak instead of a third set
            if m2:
                return None
            return None
        a, b = int(m.group(1)), int(m.group(2))
        tb = (a, b) in ((7, 6), (6, 7))
        out.append((a, b, tb))
    return out or None


def infer_first_server(sets, w_sv, l_sv):
    """'w', 'l', 'both' (undeterminable) or None (inconsistent). SvGms excludes tiebreaks
    (checked on the data: w_SvGms + l_SvGms = games - tiebreaks)."""
    if sets is None or not (w_sv >= 0 and l_sv >= 0):
        return None
    res = []
    for w_first in (True, False):
        wf, ws, ls = w_first, 0, 0
        for a, b, tb in sets:
            n = a + b
            reg = n - (1 if tb else 0)
            first_n, second_n = (reg + 1) // 2, reg // 2
            if wf:
                ws += first_n; ls += second_n
            else:
                ls += first_n; ws += second_n
            if n % 2 == 1:
                wf = not wf
        res.append((ws, ls) == (w_sv, l_sv))
    if res[0] and res[1]:
        return "both"
    if res[0]:
        return "w"
    if res[1]:
        return "l"
    return None


# ------------------------------------------------------------------ player history (cross-event, leak-free)
def history_features(m: pd.DataFrame) -> pd.DataFrame:
    """Per match key and side (w/l): from events whose last week is before this event's first
    week only (the repo's visibility rule; nothing from the same event). Windows of 52 weeks:
    retirements (this player retired), matches, sets; decayed (half-life 52 weeks) hold rate,
    opponents' hold rate, tiebreaks per set, games per set."""
    sys.path.insert(0, REPO)
    from v5_fatigue_features import event_table
    ev = event_table(m)
    fw = ev["first_week"].to_dict(); lw = ev["last_week"].to_dict()
    m = m.copy()
    m["fw"] = [fw[(t, i)] for t, i in zip(m["tour"], m["tid"])]
    m["lw"] = [lw[(t, i)] for t, i in zip(m["tour"], m["tid"])]
    sets = m["score"].map(parse_sets_any)
    m["n_sets"] = sets.map(lambda s: len(s) if s else np.nan)
    m["n_tb"] = sets.map(lambda s: sum(1 for x in s if x[2]) if s else np.nan)
    m["n_games"] = sets.map(lambda s: sum(a + b for a, b, _ in s) if s else np.nan)
    recs = []
    for side, opp in (("w", "l"), ("l", "w")):
        r = pd.DataFrame({
            "pkey": m[f"{'winner' if side == 'w' else 'loser'}_key"].values, "tour": m["tour"].values,
            "fw": m["fw"].values, "lw": m["lw"].values,
            "played": (~m["walkover"].astype(bool)).astype(float).values,
            "ret": ((side == "l") & m["retired"].astype(bool)).astype(float).values if side == "l" else np.zeros(len(m)),
            "sets": m["n_sets"].fillna(0).values, "tb": m["n_tb"].fillna(0).values, "games": m["n_games"].fillna(0).values,
            "sv": m[f"{side}_SvGms"].values, "brk": (m[f"{side}_bpFaced"] - m[f"{side}_bpSaved"]).values,
            "osv": m[f"{opp}_SvGms"].values, "obrk": (m[f"{opp}_bpFaced"] - m[f"{opp}_bpSaved"]).values})
        recs.append(r)
    R = pd.concat(recs, ignore_index=True)
    R = R[R["played"] > 0]
    okh = (R["sv"] > 0) & (R["brk"] >= 0) & (R["brk"] <= R["sv"]) & (R["osv"] > 0) & (R["obrk"] >= 0) & (R["obrk"] <= R["osv"])
    R["hw"] = okh.astype(float)
    R["sv"], R["brk"], R["osv"], R["obrk"] = [np.where(okh, R[c], 0.0) for c in ("sv", "brk", "osv", "obrk")]
    fmax = float(R["fw"].max())
    R["wt"] = np.power(2.0, (R["fw"] - fmax) / 52.0)
    out = {}
    for pk, g in R.groupby("pkey", sort=False):
        g = g.sort_values("lw", kind="mergesort")
        lwv = g["lw"].to_numpy(); fwv = g["fw"].to_numpy(); wt = g["wt"].to_numpy()
        cs = {c: np.concatenate([[0.0], np.cumsum(g[c].to_numpy())]) for c in ("played", "ret", "sets")}
        cw = {c: np.concatenate([[0.0], np.cumsum(g[c].to_numpy() * wt)]) for c in ("sv", "brk", "osv", "obrk", "tb", "sets", "games")}
        out[pk] = (lwv, fwv, cs, cw)
    keys = m["key"].values
    res = {}
    for side in ("w", "l"):
        pkeys = m[f"{'winner' if side == 'w' else 'loser'}_key"].values
        fws = m["fw"].values
        cols = {c: np.full(len(m), np.nan) for c in ("ret52", "n52", "sets52", "hold", "opp_hold", "tb_rate", "gps", "n_all")}
        for i, (pk, q) in enumerate(zip(pkeys, fws)):
            h = out.get(pk)
            if h is None:
                cols["n_all"][i] = 0
                continue
            lwv, fwv, cs, cw = h
            k = np.searchsorted(lwv, q, side="left")          # records with last week < this first week
            k0 = np.searchsorted(lwv, q - 52, side="left")
            cols["n_all"][i] = cs["played"][k]
            cols["ret52"][i] = cs["ret"][k] - cs["ret"][k0]
            cols["n52"][i] = cs["played"][k] - cs["played"][k0]
            cols["sets52"][i] = cs["sets"][k] - cs["sets"][k0]
            sc = 2.0 ** ((q - fmax) / 52.0)                       # decayed sums in units at this week
            sv, brk, osv, obrk = cw["sv"][k] / sc, cw["brk"][k] / sc, cw["osv"][k] / sc, cw["obrk"][k] / sc
            tb, st, gm = cw["tb"][k] / sc, cw["sets"][k] / sc, cw["games"][k] / sc
            cols["hold"][i] = 1 - (brk + 20 * 0.22) / (sv + 20)
            cols["opp_hold"][i] = 1 - (obrk + 20 * 0.22) / (osv + 20)
            cols["tb_rate"][i] = (tb + 4 * 0.17) / (st + 4)
            cols["gps"][i] = (gm + 4 * 9.6) / (st + 4)
        for c, v in cols.items():
            res[f"{side}_{c}"] = v
    return pd.DataFrame(res, index=keys)


def parse_sets_any(score):
    """Set games for any score incl. retirements (for set/tiebreak/game history counts)."""
    if not isinstance(score, str):
        return None
    out = []
    for a, b in re.findall(r"(\d+)-(\d+)", re.sub(r"\(\d+\)", "", score)):
        a, b = int(a), int(b)
        if a + b == 0:
            continue
        out.append((a, b, (a, b) in ((7, 6), (6, 7))))
    return out or None


def load_raw_svgms():
    cols = ["tourney_id", "round", "winner_id", "loser_id", "score", "w_SvGms", "l_SvGms", "w_bpSaved", "w_bpFaced", "l_bpSaved", "l_bpFaced"]
    fr = []
    for tour, names in (("MEN", ["ATP.csv", "ATPQualifiers.csv", "Challenger.csv"]), ("WTA", ["WTA.csv"])):
        for n in names:
            d = pd.read_csv(os.path.join(REPO, ".v5_history_cache", n), usecols=cols, low_memory=False,
                            dtype={"tourney_id": str, "winner_id": str, "loser_id": str})
            fr.append(d.assign(tour=tour))
    raw = pd.concat(fr, ignore_index=True)
    raw = raw.rename(columns={"tourney_id": "tourney_id_raw", "score": "raw_score"})
    raw = raw.drop_duplicates(["tour", "tourney_id_raw", "round", "winner_id", "loser_id"], keep=False)
    return raw


def build() -> pd.DataFrame:
    j = pd.read_pickle(os.path.join(SCR, "kaggle_data", "join", "joined.pkl"))
    j = j[j["odds_level"] != "ITF"].copy()
    j["date"] = pd.to_datetime(j["match_date_formatted"])
    j = j[j["date"] < SEALED]
    j["year"] = j["date"].dt.year
    j["gender"] = j["key"].str.split("|").str[0]
    j["bo"] = j["match_format"].astype(int)
    j["void"] = j["comment"] != "completed"
    j["T"] = j["total_games"].astype(float)
    j["Mw"] = (j["total_games_w"] - j["total_games_l"]).astype(float)       # winner's game margin
    # ---- moneyline at the two decision times (Betfair opening is unusable: in-play-like, see results)
    pw_bf = devig(j["bf_w"], j["bf_l"]); pw_b365 = devig(j["b365_w"], j["b365_l"])
    j["pw_close"] = np.where(np.isfinite(pw_bf), pw_bf, pw_b365)
    po = np.vstack([devig(j[f"{b}_w_opening"], j[f"{b}_l_opening"]) for b in ("b365", "lb", "ub")])
    j["pw_open"] = np.where(np.isfinite(po[0]), po[0], np.nanmean(np.where(np.isfinite(po[1:]), po[1:], np.nan), axis=0))
    tie_w = j["winner_key"].astype(str) < j["loser_key"].astype(str)        # tie-break by id, never by outcome
    for t in ("close", "open"):
        p = j[f"pw_{t}"]
        j[f"w_is_fav_{t}"] = (p > 0.5) | ((p == 0.5) & tie_w)
        j[f"q_{t}"] = np.maximum(p, 1 - p)                                   # favourite's fair win chance
    # ---- warehouse
    m = pd.read_pickle(os.path.join(SCR, "matches_serve.pkl"))
    m = m[m["date"] < SEALED]
    raw = load_raw_svgms()
    m = m.merge(raw, on=["tour", "tourney_id_raw", "round", "winner_id", "loser_id"], how="left")
    m = m.drop_duplicates("key", keep="first")
    hist = history_features(m)
    wcols = ["key", "stage", "rank", "minutes", "retired", "score", "raw_score", "w_SvGms", "l_SvGms", "w_svpt", "l_svpt"]
    j = j.merge(m[wcols].rename(columns={"retired": "wh_retired"}), on="key", how="left")
    j = j.join(hist, on="key")
    # ---- first server from score + service-game counts
    fs = [infer_first_server(parse_sets(s), a, b) for s, a, b in zip(j["raw_score"], j["w_SvGms"], j["l_SvGms"])]
    j["first_server"] = fs
    # ---- leak-free serve/return skills and pace
    cpp = os.path.join(SCR, "tests", "ml", "cp_feats.pkl")
    if not os.path.exists(cpp):
        import importlib.util
        sys.path.insert(0, REPO)
        spec = importlib.util.spec_from_file_location("cp", os.path.join(HERE, "court_pace_src.py"))
        cp = importlib.util.module_from_spec(spec); spec.loader.exec_module(cp)
        cp.run(m).to_pickle(cpp)
    cpf = pd.read_pickle(cpp).drop_duplicates("key").set_index("key")
    j = j.join(cpf[["S_w", "R_w", "S_l", "R_l", "pts_w", "pts_l", "pace", "pace_pts", "mu", "pw0", "pl0"]], on="key")
    # ---- schedule / workload (leak-free table of the feature-mining run), a/b -> w/l
    ff = pd.read_pickle(os.path.join(SCR, "tests", "features", "features.pkl"),)
    keep = ["a_ev_matches_before", "b_ev_matches_before", "a_prev_round_minutes", "b_prev_round_minutes",
            "a_weeks_since_prev_event", "b_weeks_since_prev_event", "a_age", "b_age", "a_ace_h20", "b_ace_h20",
            "a_elo_all", "b_elo_all", "indoor", "round_rank"]
    ff = ff[["key", "a_key"] + keep].drop_duplicates("key").set_index("key")
    j = j.join(ff, on="key")
    a_is_w = j["a_key"] == j["winner_key"]
    for c in ("ev_matches_before", "prev_round_minutes", "weeks_since_prev_event", "age", "ace_h20", "elo_all"):
        j[f"w_{c}"] = np.where(a_is_w, j[f"a_{c}"], j[f"b_{c}"])
        j[f"l_{c}"] = np.where(a_is_w, j[f"b_{c}"], j[f"a_{c}"])
        j = j.drop(columns=[f"a_{c}", f"b_{c}"])
    return j


if __name__ == "__main__":
    import time
    t = time.time()
    d = build()
    d.to_pickle(os.path.join(HERE, "prep.pkl"))
    print(d.shape, round(time.time() - t), "s")
    print(d["first_server"].value_counts(dropna=False))
