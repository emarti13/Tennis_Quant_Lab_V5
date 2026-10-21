"""Leak-free wide feature table per match (stage 1 of run_features.py).

Ordering and visibility are the repo's (v5_baseline_elo.run): events in (first_week, tour, tid)
order; another event's results become visible only once its last week is before this event's
first week (pending list, committed in last-week order); inside an event rounds go in (stage, rank)
order and a round is concurrent; unknown-round matches see only the event's starting state and
inform nothing in their own event. Walkovers get no row and move nothing.

Every per-player state (Elo, exponentially weighted point stats, schedule, H2H) is updated by the
SAME record-apply function both inside an event (local copy) and at commit time.
"""
from __future__ import annotations

import copy
import math
import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = "/home/user/Tennis_Quant_Lab_V5"
sys.path.insert(0, ROOT)
import v5_baseline_elo as be  # noqa: E402
from v5_fatigue_features import _p1_is_winner  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
CUTOFF = pd.Timestamp("2026-10-12")      # rows dated on/after this are dropped (nothing from 10-13 on)
P = be.PRODUCTION_PARAMS
HL = (5.0, 20.0, 60.0)                   # half-lives in matches
DEC = np.array([0.5 ** (1.0 / h) for h in HL])

STATS = ["win", "over", "over2", "spw", "rpw", "tpw", "tpw_m", "tpw2", "ace", "df", "fin", "fwon", "swon",
         "bpsave", "bpconv", "bpsave_luck", "bpconv_luck", "bpf_rate", "bpc_rate", "games", "games_luck",
         "win_luck", "tb", "dec", "spw_adj", "rpw_adj", "upset", "giant", "opp_elo"]
SI = {s: i for i, s in enumerate(STATS)}
NS = len(STATS)
EXTRA = ["elo_all", "elo_surf", "n_all", "n_surf", "slope5", "slope10", "slope20", "surf_win", "surf_tpw",
         "surf_n", "weeks_since_prev_event", "m_2w", "m_4w", "ev_matches_before", "ev_minutes_before",
         "prev_round_minutes", "prev_round_sets", "surface_switch", "indoor_switch", "level_prev",
         "rank_prev", "stats_points", "days_since_last_match"]
PFEAT = [f"{s}_h{int(h)}" for s in STATS for h in HL] + EXTRA
NF = len(PFEAT)
LEVEL_ORD = {"G": 6, "M": 5, "1000": 5, "PM": 5, "P5": 5, "F": 5, "O": 5, "500": 4, "P": 4, "D": 3, "A": 3,
             "250": 3, "I": 3, "C": 2, "W": 2}
SURF_I = {"Hard": 0, "Clay": 1, "Grass": 2}


# ------------------------------------------------------------------ data
RAW_COLS = ["tourney_id", "round", "winner_id", "loser_id", "winner_name", "loser_name", "indoor", "draw_size",
            "winner_hand", "loser_hand", "winner_ht", "loser_ht", "winner_rank", "loser_rank",
            "winner_rank_points", "loser_rank_points", "winner_seed", "loser_seed", "winner_entry", "loser_entry",
            "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon", "w_SvGms", "w_bpSaved", "w_bpFaced",
            "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon", "l_SvGms", "l_bpSaved", "l_bpFaced"]
SERVE = [c for c in RAW_COLS if c[:2] in ("w_", "l_")]


def load_raw():
    frames = []
    for tour, names in (("MEN", ["ATP.csv", "ATPQualifiers.csv", "Challenger.csv"]), ("WTA", ["WTA.csv"])):
        for pr, n in enumerate(names):
            d = pd.read_csv(os.path.join(ROOT, ".v5_history_cache", n), low_memory=False,
                            dtype={"tourney_id": str, "winner_id": str, "loser_id": str})
            frames.append(d[RAW_COLS].assign(tour=tour, pr=pr))
    c = pd.read_csv(os.path.join(ROOT, "v5_results_ready/tennismylife_results.csv"), low_memory=False,
                    dtype={"tourney_id": str, "winner_id": str, "loser_id": str})
    tour = np.where(c["result_file"].astype(str).str.lower().str.contains("wta"), "WTA", "MEN")
    frames.append(c[RAW_COLS].assign(tour=tour, pr=10))
    raw = pd.concat(frames, ignore_index=True)
    raw["_nn"] = raw[RAW_COLS].notna().sum(axis=1)
    raw = raw.sort_values(["_nn", "pr"], ascending=False, kind="mergesort")
    return raw


def load():
    m = be.load_matches(ROOT)
    m = m[m["date"] < CUTOFF].copy()
    raw = load_raw()
    attrs = [c for c in RAW_COLS if c not in ("tourney_id", "round", "winner_id", "loser_id", "winner_name", "loser_name")]
    r1 = raw.drop_duplicates(["tour", "tourney_id", "round", "winner_id", "loser_id"])
    j = m.merge(r1[["tour", "tourney_id", "round", "winner_id", "loser_id"] + attrs].rename(columns={"tourney_id": "tourney_id_raw"}),
                on=["tour", "tourney_id_raw", "round", "winner_id", "loser_id"], how="left")
    miss = j["winner_hand"].isna() & j["w_svpt"].isna() & j["winner_rank"].isna()
    if miss.any():   # stray-id merges changed the id: fall back to names
        r2 = raw.drop_duplicates(["tour", "tourney_id", "round", "winner_name", "loser_name"])
        k = j.loc[miss, ["tour", "tourney_id_raw", "round", "winner_name", "loser_name"]].merge(
            r2[["tour", "tourney_id", "round", "winner_name", "loser_name"] + attrs].rename(columns={"tourney_id": "tourney_id_raw"}),
            on=["tour", "tourney_id_raw", "round", "winner_name", "loser_name"], how="left")
        j.loc[miss, attrs] = k[attrs].values
    j["indoor"] = j["indoor"].astype(str).str.upper().map({"I": 1.0, "O": 0.0})
    for c in SERVE + ["winner_ht", "loser_ht", "winner_rank", "loser_rank", "winner_rank_points", "loser_rank_points",
                      "winner_seed", "loser_seed", "draw_size"]:
        j[c] = pd.to_numeric(j[c], errors="coerce")
    return j.reset_index(drop=True)


def set_scores(score):
    """[(winner games, loser games)] per set, tiebreak flags."""
    import re
    s = "" if score is None or (isinstance(score, float) and math.isnan(score)) else str(score)
    out = []
    for a, b in re.findall(r"(\d+)-(\d+)", re.sub(r"\(\d+\)", "", s)):
        out.append((int(a), int(b)))
    return out


# ------------------------------------------------------------------ per-match record pieces (winner perspective)
def match_pieces(m, kg, kw):
    """Static per-side stat inputs (x, w) for each match row, vectorized. Returns dict of arrays
    shaped (N, NS) for x and w for the winner side and loser side, excluding entries that need
    pre-match state (over, upset, giant, adj, tb/dec residual, opp_elo) which are filled at match time."""
    N = len(m)
    out = {}
    for side, o in (("w", "l"), ("l", "w")):
        X = np.full((N, NS), np.nan)
        W = np.zeros((N, NS))
        g = lambda c: m[f"{side}_{c}"].to_numpy(float)
        h = lambda c: m[f"{o}_{c}"].to_numpy(float)
        svpt, fin, fw, sw, ace, df = g("svpt"), g("1stIn"), g("1stWon"), g("2ndWon"), g("ace"), g("df")
        osv, ofw, osw = h("svpt"), h("1stWon"), h("2ndWon")
        ok = (svpt > 0) & (osv > 0) & np.isfinite(fw + sw + ofw + osw)
        sv_won, rt_won = fw + sw, osv - ofw - osw
        with np.errstate(invalid="ignore", divide="ignore"):
            spw, rpw = sv_won / svpt, rt_won / osv
            tpw = (sv_won + rt_won) / (svpt + osv)

            def put(name, x, w, mask):
                i = SI[name]
                mask = mask & np.isfinite(x) & np.isfinite(w) & (w > 0)
                X[mask, i] = x[mask]
                W[mask, i] = w[mask]

            put("spw", spw, svpt, ok)
            put("rpw", rpw, osv, ok)
            put("tpw", tpw, svpt + osv, ok)
            put("tpw_m", tpw, np.ones(N), ok)
            put("tpw2", tpw ** 2, np.ones(N), ok)
            put("ace", ace / svpt, svpt, ok)
            put("df", df / svpt, svpt, ok)
            put("fin", fin / svpt, svpt, ok & (fin <= svpt))
            put("fwon", fw / fin, fin, ok & (fin > 0))
            put("swon", sw / (svpt - fin), svpt - fin, ok & (svpt - fin > 0))
            bps, bpf, obps, obpf = g("bpSaved"), g("bpFaced"), h("bpSaved"), h("bpFaced")
            put("bpsave", bps / bpf, bpf, ok & (bpf > 0))
            put("bpconv", (obpf - obps) / obpf, obpf, ok & (obpf > 0))
            put("bpsave_luck", bps / bpf - spw, bpf, ok & (bpf > 0))
            put("bpconv_luck", (obpf - obps) / obpf - rpw, obpf, ok & (obpf > 0))
            sg, osg = g("SvGms"), h("SvGms")
            put("bpf_rate", bpf / sg, sg, ok & (sg > 0))
            put("bpc_rate", obpf / osg, osg, ok & (osg > 0))
            gw = m["_gw"].to_numpy(float) if side == "w" else m["_gl"].to_numpy(float)
            gl = m["_gl"].to_numpy(float) if side == "w" else m["_gw"].to_numpy(float)
            gs = gw / (gw + gl)
            put("games", gs, gw + gl, (gw + gl) > 0)
            put("games_luck", gs - (0.5 + kg * (tpw - 0.5)), np.ones(N), ok & ((gw + gl) > 0))
            won = np.ones(N) if side == "w" else np.zeros(N)
            put("win_luck", won - 1 / (1 + np.exp(-kw * (tpw - 0.5))), np.ones(N), ok)
        out[side] = (X, W)
    return out


class PS:
    __slots__ = ("num", "den", "elo_hist", "wk", "prev_ev", "surf", "last_week")

    def __init__(self):
        self.num = np.zeros((NS, len(HL)))
        self.den = np.zeros((NS, len(HL)))
        self.elo_hist = []          # overall Elo before each match (last 20)
        self.wk = []                # (week, tid) of each match (last 30)
        self.prev_ev = None         # (tid, surface, indoor, level_ord, rank, week) of the last event seen
        self.surf = np.zeros((3, 4))  # per surface: EW win num, den, tpw num, den
        self.last_week = np.nan

    def copy(self):
        c = PS.__new__(PS)
        c.num, c.den = self.num.copy(), self.den.copy()
        c.elo_hist, c.wk = list(self.elo_hist), list(self.wk)
        c.prev_ev, c.surf, c.last_week = self.prev_ev, self.surf.copy(), self.last_week
        return c


def apply(st: PS, rec: dict):
    x, w = rec["x"], rec["w"]
    mask = w > 0
    st.num[mask] = st.num[mask] * DEC + (w[mask] * x[mask])[:, None]
    st.den[mask] = st.den[mask] * DEC + w[mask][:, None]
    st.elo_hist.append(rec["elo_pre"])
    st.elo_hist = st.elo_hist[-20:]
    st.wk.append((rec["week"], rec["tid"], rec["minutes"], rec["sets"]))
    st.wk = st.wk[-30:]
    st.prev_ev = (rec["tid"], rec["surface"], rec["indoor"], rec["level"], rec["rank"], rec["week"])
    si = SURF_I.get(rec["surface"], 0)
    d = 0.5 ** (1 / 20.0)
    st.surf[si, :2] = st.surf[si, :2] * d + [rec["won"], 1.0]
    if np.isfinite(rec["tpw"]):
        st.surf[si, 2:] = st.surf[si, 2:] * d + [rec["tpw"], 1.0]
    st.last_week = rec["week"]


def player_vec(st: PS, elo, surface, tid, week, indoor, level, rank):
    v = np.full(NF, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(st.den > 1e-9, st.num / np.maximum(st.den, 1e-12), np.nan)
    v[:NS * len(HL)] = r.ravel()
    k = NS * len(HL)
    si = SURF_I.get(surface, 0)
    e = dict(zip(EXTRA, [np.nan] * len(EXTRA)))
    e["elo_all"], e["elo_surf"], e["n_all"], e["n_surf"] = elo[0], elo[1 + si], elo[4], elo[5 + si]
    for kk in (5, 10, 20):
        if len(st.elo_hist) >= kk:
            e[f"slope{kk}"] = elo[0] - st.elo_hist[-kk]
    e["surf_n"] = st.surf[si, 1]
    if st.surf[si, 1] > 0:
        e["surf_win"] = st.surf[si, 0] / st.surf[si, 1]
    if st.surf[si, 3] > 0:
        e["surf_tpw"] = st.surf[si, 2] / st.surf[si, 3]
    prior = [t for t in st.wk if t[1] != tid]
    inev = [t for t in st.wk if t[1] == tid]
    if prior:
        e["weeks_since_prev_event"] = week - prior[-1][0]
    e["m_2w"] = sum(1 for t in prior if t[0] >= week - 2) + len(inev)
    e["m_4w"] = sum(1 for t in prior if t[0] >= week - 4) + len(inev)
    e["ev_matches_before"] = len(inev)
    mins = [t[2] for t in inev]
    e["ev_minutes_before"] = float(np.sum(mins)) if inev and np.all(np.isfinite(mins)) else (0.0 if not inev else np.nan)
    if inev:
        e["prev_round_minutes"], e["prev_round_sets"] = inev[-1][2], inev[-1][3]
        e["days_since_last_match"] = 0.0
    elif prior:
        e["days_since_last_match"] = 7.0 * (week - prior[-1][0])
    pe = st.prev_ev
    if pe is not None and pe[0] != tid:
        e["surface_switch"] = float(pe[1] != surface)
        e["indoor_switch"] = float(pe[2] != indoor) if np.isfinite(pe[2]) and np.isfinite(indoor) else np.nan
        e["level_prev"] = level - pe[3] if np.isfinite(pe[3]) else np.nan
        e["rank_prev"] = (math.log(rank) - math.log(pe[4])) if (np.isfinite(rank) and np.isfinite(pe[4]) and rank > 0 and pe[4] > 0) else np.nan
    e["stats_points"] = st.den[SI["tpw"], 1]
    v[k:] = [e[n] for n in EXTRA]
    return v


def build(m: pd.DataFrame):
    t0 = time.time()
    # scores
    sc = m["score"].map(set_scores)
    m["_gw"] = [sum(a for a, b in s) if s else np.nan for s in sc]
    m["_gl"] = [sum(b for a, b in s) if s else np.nan for s in sc]
    tbw = np.array([sum(1 for a, b in s if (a, b) == (7, 6)) for s in sc], float)
    tbl = np.array([sum(1 for a, b in s if (a, b) == (6, 7)) for s in sc], float)
    bo = m["best_of"].fillna(3).to_numpy()
    nsets = np.array([len(s) for s in sc])
    dec_played = ((nsets == bo) & ~m["retired"].to_numpy()).astype(float)
    # structural constants from 2010-2011 only (before training years)
    early = m[(m["date"].dt.year <= 2011) & ~m["walkover"]]
    sv_w = early["w_1stWon"] + early["w_2ndWon"]
    sv_l = early["l_1stWon"] + early["l_2ndWon"]
    tpw_w = (sv_w + early["l_svpt"] - sv_l) / (early["w_svpt"] + early["l_svpt"])
    gs_w = early["_gw"] / (early["_gw"] + early["_gl"])
    ok = tpw_w.notna() & gs_w.notna()
    x = np.r_[tpw_w[ok] - 0.5, 0.5 - tpw_w[ok]]
    yg = np.r_[gs_w[ok] - 0.5, 0.5 - gs_w[ok]]
    kg = float((x * yg).sum() / (x * x).sum())
    from sklearn.linear_model import LogisticRegression
    lr = LogisticRegression(C=1e6, fit_intercept=False).fit(x[:, None], np.r_[np.ones(ok.sum()), np.zeros(ok.sum())])
    kw = float(lr.coef_[0, 0])
    pieces = match_pieces(m, kg, kw)
    # event country: modal ioc of the event's wildcards, else of all its entrants (draw known pre-event).
    # LEAK FIX 2026-10-21: count each player ONCE per event. Counting match rows weighted players
    # by how far they went, so the country whose players won most became "home" (home win rate
    # 54.4% with match rows vs 50.7% with one row per player).
    long = pd.concat([m[["tour", "tid", "winner_key", "winner_ioc", "winner_entry"]].set_axis(["tour", "tid", "pk", "ioc", "entry"], axis=1),
                      m[["tour", "tid", "loser_key", "loser_ioc", "loser_entry"]].set_axis(["tour", "tid", "pk", "ioc", "entry"], axis=1)])
    long = long.drop_duplicates(["tour", "tid", "pk"])
    long["entry"] = long["entry"].astype(str).str.upper()
    wc = long[long["entry"] == "WC"].groupby(["tour", "tid"])["ioc"].agg(lambda s: s.value_counts().index[0] if s.notna().any() else np.nan)
    def mode_share(s):
        vc = s.value_counts(normalize=True)
        return vc.index[0] if len(vc) and vc.iloc[0] >= 0.2 else np.nan
    allm = long.groupby(["tour", "tid"])["ioc"].agg(mode_share)
    country = allm.copy()
    country.loc[wc.index] = wc.where(wc.notna(), allm.reindex(wc.index))
    country = country.to_dict()

    order, weeks = be._events(m)
    ev = be.event_table(m)
    tw_main = ev["main_week"].to_dict()
    tw_first = ev["first_week"].to_dict()
    idx_of = {k: i for i, k in enumerate(m["key"])}
    N = len(m)
    FA = np.full((N, NF), np.nan)          # winner-side vector
    FB = np.full((N, NF), np.nan)          # loser-side vector
    PW = np.full(N, np.nan)
    H2H = np.full((N, 5), np.nan)          # winner wins vs loser, loser wins, surf w, surf l, winner over-sum
    done = np.zeros(N, bool)

    ratings: dict = {}
    states: dict = {}
    h2h: dict = {}
    pending = []
    by_event = {e: g for e, g in m.groupby(["tour", "tid"], sort=False)}
    level_ord = m["level"].map(LEVEL_ORD).astype(float).to_numpy()
    surf_arr = m["surface"].map(be.surface_of).to_numpy()
    indoor = m["indoor"].to_numpy(float)
    wrank, lrank = m["winner_rank"].to_numpy(float), m["loser_rank"].to_numpy(float)
    minutes, sets = m["minutes"].to_numpy(float), m["sets"].to_numpy(float)
    tid_arr = m["tid"].to_numpy()
    tbw_, tbl_ = tbw, tbl
    Xw, Ww = pieces["w"]
    Xl, Wl = pieces["l"]

    def commit_rec(key, rec):
        st = states.get(key)
        if st is None:
            st = states[key] = PS()
        apply(st, rec)

    def h2h_key(a, b):
        return (a, b) if a < b else (b, a)

    for ei, e in enumerate(order):
        first = weeks[e]["first_week"]
        still = []
        for last, deltas, recs in sorted(pending, key=lambda z: z[0]):
            if last < first:
                for key, d in deltas.items():
                    ratings[key] = ratings.get(key, be._fresh(P)) + d
                for key, rec in recs:
                    commit_rec(key, rec)
                    if rec["side"] == "w":
                        hk = h2h_key(key, rec["opp"])
                        hv = h2h.setdefault(hk, np.zeros(8))   # wins lo, wins hi, surf (3x2) folded below
                        j = 0 if key == hk[0] else 1
                        hv[j] += 1
                        si = SURF_I.get(rec["surface"], 0)
                        h2h.setdefault(hk + (si,), np.zeros(2))[j] += 1
                        h2h.setdefault(hk + ("over",), np.zeros(1))[0] += (1 - rec["p"]) * (1 if j == 0 else -1)
            else:
                still.append((last, deltas, recs))
        pending = still
        g = by_event[e]
        g = g[~g["walkover"].astype(bool)]
        week_main = tw_main.get(e)
        local_elo, start = {}, {}
        local_st = {}
        recs_ev = []
        unknown_deltas = {}

        def get_elo(k, use_local=True):
            if use_local and k in local_elo:
                return local_elo[k]
            return ratings.get(k, be._fresh(P))

        def get_st(k, use_local=True):
            if use_local and k in local_st:
                return local_st[k]
            return states.get(k) or PS()

        def make_rec(i, side, key, opp, p, elo_pre, opp_st, st_self, week):
            X, W = (Xw, Ww) if side == "w" else (Xl, Wl)
            x, w = X[i].copy(), W[i].copy()
            won = 1.0 if side == "w" else 0.0
            x[SI["win"]], w[SI["win"]] = won, 1
            x[SI["over"]], w[SI["over"]] = won - p, 1
            x[SI["over2"]], w[SI["over2"]] = (won - p) ** 2, 1
            x[SI["upset"]], w[SI["upset"]] = 1 - won, float(p > 0.6)
            x[SI["giant"]], w[SI["giant"]] = won, float(p < 0.4)
            x[SI["opp_elo"]], w[SI["opp_elo"]] = opp[1], 1
            tbn = tbw_[i] + tbl_[i]
            if tbn > 0:
                tw_ = tbw_[i] if side == "w" else tbl_[i]
                x[SI["tb"]], w[SI["tb"]] = tw_ / tbn - p, tbn
            if dec_played[i] > 0:
                x[SI["dec"]], w[SI["dec"]] = won - p, 1
            # opponent-adjusted serve/return: vs the opponent's pre-match EW (h20) return/serve
            o_den = opp_st.den
            if W[i, SI["spw"]] > 0 and o_den[SI["rpw"], 1] > 0:
                x[SI["spw_adj"]], w[SI["spw_adj"]] = X[i, SI["spw"]] - (1 - opp_st.num[SI["rpw"], 1] / o_den[SI["rpw"], 1]), 1
            if W[i, SI["rpw"]] > 0 and o_den[SI["spw"], 1] > 0:
                x[SI["rpw_adj"]], w[SI["rpw_adj"]] = X[i, SI["rpw"]] - (1 - opp_st.num[SI["spw"], 1] / o_den[SI["spw"], 1]), 1
            return {"x": np.nan_to_num(x), "w": w, "won": won, "p": p, "elo_pre": elo_pre, "week": week,
                    "tid": tid_arr[i], "minutes": minutes[i], "sets": sets[i], "surface": surf_arr[i],
                    "indoor": indoor[i], "level": level_ord[i], "rank": wrank[i] if side == "w" else lrank[i],
                    "tpw": X[i, SI["tpw"]], "side": side, "opp": opp[0]}

        def price(i, w, l, use_local):
            rw, rl = get_elo(w, use_local), get_elo(l, use_local)
            s = surf_arr[i]
            p = be.probability(rw, rl, s, P)
            stage = m_stage[i]
            week = week_main if (stage == 1 and week_main == week_main and week_main is not None) else tw_first[e]
            sw_, sl_ = get_st(w, use_local), get_st(l, use_local)
            FA[i] = player_vec(sw_, rw, s, tid_arr[i], week, indoor[i], level_ord[i], wrank[i])
            FB[i] = player_vec(sl_, rl, s, tid_arr[i], week, indoor[i], level_ord[i], lrank[i])
            PW[i] = p
            hk = h2h_key(w, l)
            hv = h2h.get(hk)
            if hv is not None:
                jw = 0 if w == hk[0] else 1
                hs = h2h.get(hk + (SURF_I.get(s, 0),), np.zeros(2))
                ov = h2h.get(hk + ("over",), np.zeros(1))[0] * (1 if jw == 0 else -1)
                H2H[i] = [hv[jw], hv[1 - jw], hs[jw], hs[1 - jw], ov]
            else:
                H2H[i] = [0, 0, 0, 0, 0]
            done[i] = True
            return rw, rl, p, s, sw_, sl_, week

        known = g[g["rank"].notna()]
        groups = sorted(known.groupby(["stage", "rank"], sort=False), key=lambda kv: kv[0])
        for (stage, rank), grp in groups:
            updates = []
            for key, w, l in zip(grp["key"], grp["winner_key"], grp["loser_key"]):
                i = idx_of[key]
                for k in (w, l):
                    start.setdefault(k, get_elo(k, False).copy())
                rw, rl, p, s, sw_, sl_, week = price(i, w, l, True)
                updates.append((i, w, l, rw, rl, p, s, sw_, sl_, week))
            for i, w, l, rw, rl, p, s, sw_, sl_, week in updates:
                dw, dl = be._update(rw, rl, p, s, P)
                local_elo[w] = get_elo(w) + dw
                local_elo[l] = get_elo(l) + dl
                rec_w = make_rec(i, "w", w, (l, rl[0]), p, rw[0], sl_, sw_, week)
                rec_l = make_rec(i, "l", l, (w, rw[0]), 1 - p, rl[0], sw_, sl_, week)
                for k, rec in ((w, rec_w), (l, rec_l)):
                    if k not in local_st:
                        local_st[k] = get_st(k, False).copy()
                    apply(local_st[k], rec)
                    recs_ev.append((k, rec))
        for key, w, l in zip(g.loc[g["rank"].isna(), "key"], g.loc[g["rank"].isna(), "winner_key"], g.loc[g["rank"].isna(), "loser_key"]):
            i = idx_of[key]
            rw, rl, p, s, sw_, sl_, week = price(i, w, l, False)
            dw, dl = be._update(rw, rl, p, s, P)
            unknown_deltas[w] = unknown_deltas.get(w, np.zeros(8)) + dw
            unknown_deltas[l] = unknown_deltas.get(l, np.zeros(8)) + dl
            recs_ev.append((w, make_rec(i, "w", w, (l, rl[0]), p, rw[0], sl_, sw_, week)))
            recs_ev.append((l, make_rec(i, "l", l, (w, rw[0]), 1 - p, rl[0], sw_, sl_, week)))
        deltas = {k: v - start[k] for k, v in local_elo.items()}
        for k, d in unknown_deltas.items():
            deltas[k] = deltas.get(k, np.zeros(8)) + d
        pending.append((weeks[e]["last_week"], deltas, recs_ev))
        if ei % 2000 == 0:
            print(f"  event {ei}/{len(order)}  {time.time() - t0:.0f}s", flush=True)
    return FA, FB, PW, H2H, done, country, kg, kw


m_stage = None


def main():
    global m_stage
    t0 = time.time()
    m = load()
    print("matches", len(m), f"{time.time() - t0:.0f}s", flush=True)
    m_stage = m["stage"].to_numpy()
    FA, FB, PW, H2H, done, country, kg, kw = build(m)
    print("built", f"{time.time() - t0:.0f}s", "priced", done.sum(), "kg", kg, "kw", kw, flush=True)
    # parity with the repo Elo
    ref = be.run(m, P).set_index("key")["p_winner"]
    mine = pd.Series(PW, index=m["key"]).dropna()
    gap = (mine - ref.reindex(mine.index)).abs()
    print("Elo parity: rows", len(mine), "vs", len(ref), "max |diff|", float(gap.max()), flush=True)
    assert len(mine) == len(ref) and float(gap.max()) < 1e-9, "Elo parity failed"
    keep = done
    mm = m[keep].reset_index(drop=True)
    FA, FB, PW, H2H = FA[keep], FB[keep], PW[keep], H2H[keep]
    # orientation: stable hash of the match key (not winner-first)
    a_is_w = np.array([_p1_is_winner(k) for k in mm["key"]])
    sgn = np.where(a_is_w, 1.0, -1.0)
    A = np.where(a_is_w[:, None], FA, FB)
    B = np.where(a_is_w[:, None], FB, FA)
    cols = {}
    for j, n in enumerate(PFEAT):
        cols[f"d_{n}"] = A[:, j] - B[:, j]
    for n in ("n_all", "n_surf", "elo_all", "stats_points", "weeks_since_prev_event", "ev_matches_before",
              "prev_round_minutes", "surf_n", "spw_h20", "rpw_h20", "ace_h20", "tpw_h20", "over_h20"):
        j = PFEAT.index(n)
        cols[f"a_{n}"], cols[f"b_{n}"] = A[:, j], B[:, j]
    F = pd.DataFrame(cols)
    pa = np.where(a_is_w, PW, 1 - PW)
    F["elo_p"] = pa
    F["elo_logit"] = np.log(pa / (1 - pa))
    # H2H from A's view
    F["h2h_a"] = np.where(a_is_w, H2H[:, 0], H2H[:, 1])
    F["h2h_b"] = np.where(a_is_w, H2H[:, 1], H2H[:, 0])
    F["h2h_surf_a"] = np.where(a_is_w, H2H[:, 2], H2H[:, 3])
    F["h2h_surf_b"] = np.where(a_is_w, H2H[:, 3], H2H[:, 2])
    F["h2h_diff"] = F["h2h_a"] - F["h2h_b"]
    F["h2h_n"] = F["h2h_a"] + F["h2h_b"]
    F["h2h_surf_diff"] = F["h2h_surf_a"] - F["h2h_surf_b"]
    F["h2h_over"] = H2H[:, 4] * sgn
    # pre-match attributes from the raw files (known before the match)
    def side(col_w, col_l):
        w, l = mm[col_w].to_numpy(), mm[col_l].to_numpy()
        return np.where(a_is_w, w, l), np.where(a_is_w, l, w)
    ra, rb = side("winner_rank", "loser_rank")
    ra, rb = ra.astype(float), rb.astype(float)
    F["a_rank"], F["b_rank"] = ra, rb
    F["d_logrank"] = np.log(ra) - np.log(rb)
    pa_, pb_ = side("winner_rank_points", "loser_rank_points")
    pa_, pb_ = pa_.astype(float), pb_.astype(float)
    F["d_logpts"] = np.log1p(pa_) - np.log1p(pb_)
    F["d_logpts_minus_elo"] = F["d_logpts"] - F["elo_logit"] / 1.0
    sa, sb = side("winner_seed", "loser_seed")
    F["a_seed"], F["b_seed"] = sa.astype(float), sb.astype(float)
    F["a_seeded"], F["b_seeded"] = np.isfinite(F["a_seed"]).astype(float), np.isfinite(F["b_seed"]).astype(float)
    # LEAK GUARD: in the historical ATPQualifiers file the seed field is blank far more often for the
    # WINNER (14% seeded) than the loser (26%) - the reverse of every other file - so its missingness
    # encodes the result (found by a 2012-2025 vs 2026 qualifying gap: AUC 0.85 vs 0.73). Seeds are
    # dropped for all qualifying rounds.
    q = mm["stage"].to_numpy() == 0
    for c in ("a_seed", "b_seed", "a_seeded", "b_seeded"):
        F.loc[q, c] = np.nan
    ea, eb = side("winner_entry", "loser_entry")
    ea = pd.Series(ea).astype(str).str.upper().str.strip()
    eb = pd.Series(eb).astype(str).str.upper().str.strip()
    for t in ("Q", "WC", "LL", "PR", "SE", "ALT"):
        F[f"a_entry_{t}"], F[f"b_entry_{t}"] = (ea == t).astype(float).values, (eb == t).astype(float).values
    F["entry_known"] = (~mm["level"].isin(["C"])).astype(float).values   # Challenger files carry no entry codes
    ha, hb = side("winner_hand", "loser_hand")
    F["a_lefty"] = (pd.Series(ha) == "L").astype(float).values
    F["b_lefty"] = (pd.Series(hb) == "L").astype(float).values
    F["hand_pair"] = F["a_lefty"] * 2 + F["b_lefty"]
    hta, htb = side("winner_ht", "loser_ht")
    F["a_ht"], F["b_ht"] = hta.astype(float), htb.astype(float)
    F["d_ht"] = F["a_ht"] - F["b_ht"]
    fast = ((mm["surface"].astype(str) == "Grass") | (mm["indoor"] == 1)).astype(float).values
    F["d_ht_x_fast"] = F["d_ht"] * fast
    ag, bg = side("winner_age", "loser_age")
    F["a_age"], F["b_age"] = ag.astype(float), bg.astype(float)
    F["d_age"] = F["a_age"] - F["b_age"]
    ia, ib = side("winner_ioc", "loser_ioc")
    ctry = np.array([country.get((t, i), np.nan) for t, i in zip(mm["tour"], mm["tid"])], dtype=object)
    F["a_home"] = (pd.Series(ia).values == ctry).astype(float)
    F["b_home"] = (pd.Series(ib).values == ctry).astype(float)
    F["d_home"] = F["a_home"] - F["b_home"]
    F["a_entry_Q_through"] = F["a_entry_Q"] * (A[:, PFEAT.index("ev_matches_before")] > 0)
    # Barnett-Clarke style serve matchup from h20 serve/return shares
    spa, spb = A[:, PFEAT.index("spw_h20")], B[:, PFEAT.index("spw_h20")]
    rpa, rpb = A[:, PFEAT.index("rpw_h20")], B[:, PFEAT.index("rpw_h20")]
    tour_rpw = np.where(mm["tour"] == "WTA", 0.44, 0.37)
    fab = spa - (rpb - tour_rpw)
    fba = spb - (rpa - tour_rpw)
    F["bc_fab"], F["bc_fba"] = fab, fba
    F["bc_p_logit"] = bc_match_logit(fab, fba, mm["best_of"].fillna(3).to_numpy())
    F["bigserve_vs_return"] = (A[:, PFEAT.index("ace_h20")] - B[:, PFEAT.index("ace_h20")]) * (rpa - rpb)
    F["lefty_vs_righty_ace"] = (F["a_lefty"] - F["b_lefty"]) * (A[:, PFEAT.index("ace_h20")] + B[:, PFEAT.index("ace_h20")])
    # context
    F["surface_c"] = mm["surface"].map(be.surface_of).map(SURF_I).astype(float).values
    F["indoor"] = mm["indoor"].astype(float).values
    F["level_ord"] = mm["level"].map(LEVEL_ORD).astype(float).values
    F["is_wta"] = (mm["tour"] == "WTA").astype(float).values
    F["is_chall"] = ((mm["tour"] == "MEN") & (mm["level"] == "C")).astype(float).values
    F["best_of"] = mm["best_of"].astype(float).values
    F["round_rank"] = mm["rank"].astype(float).values
    F["stage"] = mm["stage"].astype(float).values
    F["draw_size"] = mm["draw_size"].astype(float).values
    meta = pd.DataFrame({"key": mm["key"], "tour": mm["tour"], "tid": mm["tid"], "level": mm["level"],
                         "date": mm["date"], "year": mm["date"].dt.year, "a_key": np.where(a_is_w, mm["winner_key"], mm["loser_key"]),
                         "b_key": np.where(a_is_w, mm["loser_key"], mm["winner_key"]), "y": a_is_w.astype(int),
                         "n_min": np.minimum(F["a_n_all"], F["b_n_all"]), "retired": mm["retired"].values})
    meta["group"] = np.where(mm["tour"] == "WTA", "WTA", np.where(mm["level"] == "C", "Challenger", "ATP"))
    out = pd.concat([meta, F], axis=1)
    out.to_pickle(os.path.join(OUT, "features.pkl"))
    print("saved", out.shape, f"{time.time() - t0:.0f}s")


def bc_match_logit(fa, fb, bo):
    """P(A wins match) from serve-point probabilities (iid points), exact game/tiebreak/set DP."""
    fa = np.clip(np.nan_to_num(fa, nan=0.62), 0.3, 0.9)
    fb = np.clip(np.nan_to_num(fb, nan=0.62), 0.3, 0.9)

    def game(p):
        q = 1 - p
        return p ** 4 * (1 + 4 * q + 10 * q ** 2) + 20 * p ** 3 * q ** 3 * p ** 2 / (1 - 2 * p * q)

    def tiebreak(pa, pb):
        # A serves first point, then alternate in pairs; DP to 6-6 then closed form
        n = len(pa)
        P_ = {(0, 0): np.ones(n)}
        win = np.zeros(n)
        for tot in range(0, 12):
            for a in range(0, tot + 1):
                b = tot - a
                if (a, b) not in P_ or a >= 7 or b >= 7:
                    continue
                pr = P_.pop((a, b))
                server_a = ((tot + 1) // 2) % 2 == 0
                pw = pa if server_a else 1 - pb
                for (na, nb, w_) in ((a + 1, b, pw), (a, b + 1, 1 - pw)):
                    v = pr * w_
                    if na == 7 and nb <= 5:
                        win += v
                    elif nb == 7 and na <= 5:
                        pass
                    else:
                        P_[(na, nb)] = P_.get((na, nb), 0) + v
        p66 = P_.get((6, 6), np.zeros(n))
        # from 6-6 two points (one each serve): win both / split
        ww = pa * (1 - pb)
        ll = (1 - pa) * pb
        win += p66 * ww / (ww + ll)
        return win

    ga, gb = game(fa), game(fb)          # A holds, B holds
    tb = tiebreak(fa, fb)
    n = len(fa)
    S = {(0, 0): np.ones(n)}
    setw = np.zeros(n)
    for tot in range(0, 13):
        for a in range(0, tot + 1):
            b = tot - a
            if (a, b) not in S:
                continue
            pr = S.pop((a, b))
            if (a, b) == (6, 6):
                setw += pr * tb
                continue
            pw = ga if tot % 2 == 0 else 1 - gb
            for (na, nb, w_) in ((a + 1, b, pw), (a, b + 1, 1 - pw)):
                v = pr * w_
                if (na >= 6 and na - nb >= 2) or na == 7:
                    setw += v
                elif (nb >= 6 and nb - na >= 2) or nb == 7:
                    pass
                else:
                    S[(na, nb)] = S.get((na, nb), 0) + v
    s = setw
    m3 = s ** 2 * (3 - 2 * s)
    m5 = s ** 3 * (10 - 15 * s + 6 * s ** 2)
    pm = np.clip(np.where(bo == 5, m5, m3), 1e-4, 1 - 1e-4)
    return np.log(pm / (1 - pm))


if __name__ == "__main__":
    main()
