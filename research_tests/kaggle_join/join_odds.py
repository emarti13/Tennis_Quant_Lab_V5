"""Join the tennisexplorer/Kaggle odds CSV to the warehouse matches (winner-oriented)."""
import json, re, sys, time, unicodedata
T0 = time.time()
def log(*a, **k): print(round(time.time() - T0), *a, flush=True)
from collections import defaultdict
import numpy as np
import pandas as pd

ODDS, WH, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
LO, HI = -10, 20  # history Challenger/some event dates are the event end, not start

SPECIAL = str.maketrans({"ł": "l", "Ł": "l", "ø": "o", "Ø": "o", "đ": "d", "Đ": "d", "ß": "ss",
                         "æ": "ae", "œ": "oe", "ı": "i", "þ": "th", "ð": "d"})
DROP = {"jr", "sr", "ii", "iii", "iv", ""}


def toks(s):
    if not isinstance(s, str):
        return []
    s = unicodedata.normalize("NFKD", s.translate(SPECIAL))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z ]", " ", s.replace("-", " ").replace("'", ""))
    return [t for t in s.split() if t not in DROP]


def compat(o_all, o_last, w):
    """3 exact, 2 strong, 1 weak, 0 none."""
    O, L, W = set(o_all), set(o_last), set(w)
    if not O or not W:
        return 0
    if O == W or "".join(sorted(o_all)) == "".join(sorted(w)):
        return 3
    if "".join(o_all) == "".join(w) or "".join(o_all[::-1]) == "".join(w):
        return 3
    rest_o, rest_w = O - L, W - L
    if L and L <= W:
        if O <= W or (rest_o and rest_w and {t[0] for t in rest_o} & {t[0] for t in rest_w}):
            return 2
        return 1
    if W <= O and len(W) >= 2:
        return 2
    lj, wj = "".join(o_last), "".join(w)
    if len(lj) >= 4 and lj in wj:  # compound surname written together
        rest = wj.replace(lj, "", 1)
        if rest_o and rest and {t[0] for t in rest_o} & {rest[0]}:
            return 2
        return 1
    if L & W and max(L, key=len) in W:
        return 1
    return 0


def odds_level(name, tour):
    n = name.lower()
    if "itf" in n.split() or n.endswith(" itf"):
        return "ITF"
    if "challenger" in n or "chall." in n:
        return "Challenger"
    if "qualif" in n or "wc playoff" in n:
        return "qualifying"
    return f"{tour} main"


def parse_score(s):
    if not isinstance(s, str):
        return []
    out = []
    for p in s.split():
        m = re.match(r"^\[?(\d+)-(\d+)", p)
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    return out


# ---------------- load
od = pd.read_csv(ODDS, low_memory=False)
od["oid"] = np.arange(len(od))
od["wtour"] = od.tour.map({"ATP": "MEN", "WTA": "WTA"})
od["odate"] = pd.to_datetime(od.match_date_formatted).dt.normalize()
od["odds_level"] = [odds_level(t, u) for t, u in zip(od.tournament.astype(str), od.tour)]
for s in "ab":
    od[f"slug_{s}"] = od[f"player_{s}_url"].fillna("NAME:" + od[f"player_{s}"].fillna("?")).str.replace(
        "https://www.tennisexplorer.com/player/", "", regex=False)

log("loaded odds")
wh = pd.read_pickle(WH)
wh = wh[wh.date >= "2013-12-01"][["key", "tour", "tid", "tourney_name", "level", "round", "date", "winner_key",
                                    "loser_key", "winner_name", "loser_name", "score", "walkover", "retired"]].copy()

# ---------------- player-level candidates
whp = pd.concat([wh[["tour", "winner_key", "winner_name"]].set_axis(["tour", "k", "n"], axis=1),
                 wh[["tour", "loser_key", "loser_name"]].set_axis(["tour", "k", "n"], axis=1)]).drop_duplicates()
whp["t"] = whp.n.map(toks)
index = defaultdict(set)
whtok = defaultdict(list)
for tour, k, t in zip(whp.tour, whp.k, whp.t):
    whtok[k].append(t)
    for x in t:
        index[(tour, x)].add(k)
    j = "".join(t)
    for i in range(len(j) - 3):  # 4-gram index for written-together surnames
        index[(tour, "#" + j[i:i + 4])].add(k)

op = pd.concat([od[["wtour", f"slug_{s}", f"player_{s}", f"player_{s}_first_name", f"player_{s}_last_name"]]
                .set_axis(["tour", "slug", "n", "fn", "ln"], axis=1) for s in "ab"]).drop_duplicates(["tour", "slug"])
op = op[op.tour.notna()]
cands = []
for tour, slug, n, fn, ln in op.itertuples(index=False):
    o_all = toks(f"{fn} {ln}") if isinstance(ln, str) else toks(n)
    o_last = toks(ln) if isinstance(ln, str) else o_all[-1:]
    pool = set()
    for x in o_last:
        pool |= index.get((tour, x), set())
    lj = "".join(o_last)
    if not pool and len(lj) >= 4:
        pool = set(index.get((tour, "#" + lj[:4]), set()))
        for i in range(1, len(lj) - 3):
            pool &= index.get((tour, "#" + lj[i:i + 4]), set())
    for k in pool:
        c = max(compat(o_all, o_last, w) for w in whtok[k])
        if c:
            cands.append((tour, slug, k, c))
cand = pd.DataFrame(cands, columns=["tour", "slug", "k", "c"])
log("odds players", len(op), "with any candidate", cand.slug.nunique(), "pairs", len(cand), flush=True)


def match_rows(odds_sub, cand_tab, label):
    """Return candidate (oid, key, cw, cl, dd) rows with same orientation and date window."""
    cw = cand_tab.rename(columns={"slug": "slug_a", "k": "winner_key", "c": "cw"})
    cl = cand_tab.rename(columns={"slug": "slug_b", "k": "loser_key", "c": "cl"})
    x = wh.merge(cw, on=["tour", "winner_key"]).merge(cl, on=["tour", "loser_key"])
    x = x.merge(odds_sub[["oid", "wtour", "slug_a", "slug_b", "odate"]].rename(columns={"wtour": "tour"}),
                on=["tour", "slug_a", "slug_b"])
    x["dd"] = (x.odate - x.date).dt.days
    x = x[(x.dd >= LO) & (x.dd <= HI)]
    return x


def score_agree(o, s):
    ws = parse_score(s)
    osets = [(o[f"set{i}_score_a"], o[f"set{i}_score_b"]) for i in range(1, 6)]
    osets = [(int(a), int(b)) for a, b in osets if pd.notna(a) and pd.notna(b) and (a or b)]
    if not ws or not osets:
        return np.nan
    n = min(len(ws), len(osets))
    ok = all(ws[i] == osets[i] or (i == n - 1 and max(ws[i]) >= 10 and osets[i] in ((1, 0), (0, 1), (7, 6), (6, 7)))
             for i in range(n))
    return float(ok and (len(ws) == len(osets) or n >= 1))


def resolve(x, taken_oid, taken_key):
    """One-to-one selection; prefers higher name compat, then closer plausible date."""
    x = x[~x.oid.isin(taken_oid) & ~x.key.isin(taken_key)].copy()
    x["q"] = x[["cw", "cl"]].min(axis=1) * 10 + x[["cw", "cl"]].max(axis=1)
    best = x.groupby("oid").q.transform("max")
    x = x[x.q == best]
    x["pen"] = np.maximum(0, -x.dd) + np.maximum(0, x.dd - 14)
    x = x[x.pen == x.groupby("oid").pen.transform("min")]
    n_by_oid = x.groupby("oid").key.transform("nunique")
    x = x[n_by_oid == 1].drop_duplicates(["oid", "key"])
    n_by_key = x.groupby("key").oid.transform("nunique")
    return x[n_by_key == 1]


# ---------------- phase 1: name-based, strong on both sides
p1 = match_rows(od, cand[cand.c >= 2], "p1")
acc = resolve(p1, set(), set())
acc["phase"] = 1
log("phase1", len(acc), flush=True)

# ---------------- player map from unambiguous matches
def build_map(acc):
    pm = pd.concat([acc[["oid", "winner_key"]].merge(od[["oid", "wtour", "slug_a"]], on="oid")
                    .set_axis(["oid", "k", "tour", "slug"], axis=1),
                    acc[["oid", "loser_key"]].merge(od[["oid", "wtour", "slug_b"]], on="oid")
                    .set_axis(["oid", "k", "tour", "slug"], axis=1)])
    g = pm.groupby(["tour", "slug", "k"]).size().rename("n").reset_index()
    g["share"] = g.n / g.groupby(["tour", "slug"]).n.transform("sum")
    g = g[(g.share >= 0.9)]
    # key must map back to a single slug too
    g = g[g.groupby(["tour", "k"]).slug.transform("nunique") == 1]
    return g[["tour", "slug", "k"]]

pmap = build_map(acc)
log("map size", len(pmap), flush=True)

# ---------------- phase 2: map first, weak names for the rest
rest = od[~od.oid.isin(acc.oid)]
mapped = set(zip(pmap.tour, pmap.slug))
c2 = cand[[(t, s) not in mapped for t, s in zip(cand.tour, cand.slug)]]
c2 = pd.concat([pmap.assign(c=3), c2])
# a key already owned by a different mapped slug can't be a weak candidate for another slug
owned = dict(zip(zip(pmap.tour, pmap.k), pmap.slug))
c2 = c2[[owned.get((t, k), s) == s for t, s, k in zip(c2.tour, c2.slug, c2.k)]]
p2 = match_rows(rest, c2, "p2")
a2 = resolve(p2, set(acc.oid), set(acc.key))
a2["phase"] = 2
acc = pd.concat([acc, a2])
log("phase2", len(a2), flush=True)

# ---------------- phase 3: one side mapped, other side unknown (name changes); require score agreement
pmap = build_map(acc)
rest = od[~od.oid.isin(acc.oid)]
m_slug2k = dict(zip(zip(pmap.tour, pmap.slug), pmap.k))
k2slug = dict(zip(zip(pmap.tour, pmap.k), pmap.slug))
taken_key = set(acc.key)
SETC = [f"set{i}_score_{x}" for i in range(1, 6) for x in "ab"]
parts = []
rest = rest.assign(kw=[m_slug2k.get((t, x)) for t, x in zip(rest.wtour, rest.slug_a)],
                   kl=[m_slug2k.get((t, x)) for t, x in zip(rest.wtour, rest.slug_b)])
one = rest[rest.kw.isna() != rest.kl.isna()]
for side, ok, other in (("kw", "winner_key", "loser_key"), ("kl", "loser_key", "winner_key")):
    q = one[one[side].notna()][["oid", "wtour", side, "odate"] + SETC].rename(columns={"wtour": "tour", side: ok})
    x = q.merge(wh, on=["tour", ok])
    dd = (x.odate - x.date).dt.days
    x = x[(dd >= LO) & (dd <= HI) & ~x.key.isin(taken_key)]
    x = x[[(t, k) not in k2slug for t, k in zip(x.tour, x[other])]]
    parts.append(x)
x = pd.concat(parts)
x = x[[score_agree(o, sc) == 1.0 for o, sc in zip(x[SETC].to_dict("records"), x.score)]]
x = x[x.groupby("oid").key.transform("nunique") == 1]
rows = list(zip(x.oid, x.key))
a3 = pd.DataFrame(rows, columns=["oid", "key"])
a3 = a3[~a3.key.duplicated(keep=False)].merge(wh, on="key")
a3["phase"] = 3
acc = pd.concat([acc, a3])
log("phase3", len(a3), flush=True)
assert acc.oid.is_unique and acc.key.is_unique

# ---------------- diagnostics: reversed-orientation hits among unmatched
rest = od[~od.oid.isin(acc.oid)]
pmap = build_map(acc)
cc = pd.concat([pmap.assign(c=3), cand[cand.c >= 2]])
rv = rest[rest.odds_level != "ITF"].rename(columns={"slug_a": "slug_b", "slug_b": "slug_a"})
rev = match_rows(rv, cc, "rev")
n_rev = int(rev.oid.nunique())

# ---------------- output
acc = acc[["oid", "key", "phase"]].merge(wh[["key", "level", "round", "date", "tid", "tourney_name", "score",
                                              "winner_key", "loser_key", "winner_name", "loser_name"]],
                                         on="key").rename(columns={"level": "wh_level", "round": "wh_round",
                                                                   "date": "wh_date", "score": "wh_score"})
ren = {}
books = {"bet365": "b365", "Betfair": "bf", "Ladbrokes": "lb", "Unibet": "ub"}
for c in od.columns:
    new = c
    for b, s in books.items():
        new = new.replace(f"{b}_", f"{s}_")
    new = new.replace("best_odds", "best").replace("player_", "p_")
    new = re.sub(r"_a(?=_|$)", "_w", new); new = re.sub(r"_b(?=_|$)", "_l", new)
    new = re.sub(r"score_a$", "score_w", new); new = re.sub(r"score_b$", "score_l", new)
    new = new.replace("odds_over", "over").replace("odds_under", "under").replace("odds_handicap", "hcp_odds")
    new = re.sub(r"^(b365|bf|lb|ub)_odds_", r"\1_", new)
    ren[c] = new
odr = od.rename(columns=ren)
odr = odr.rename(columns={"oid": "odds_row", "round": "round", "surface": "surface"})
j = acc.rename(columns={"oid": "odds_row"}).merge(odr, on="odds_row")
j["level"] = j.wh_level
j["score_agree"] = [score_agree({f"set{i}_score_{s}": r[f"set{i}_score_{t}"] for i in range(1, 6)
                                 for s, t in (("a", "w"), ("b", "l"))}, sc)
                    for r, sc in zip(j.to_dict("records"), j.wh_score)]
j = j.drop(columns=["wtour", "odate", "slug_w", "slug_l"], errors="ignore")
j.to_pickle(f"{OUT}/joined.pkl")
try:
    j.to_parquet(f"{OUT}/joined.parquet")
except Exception as e:
    print("parquet failed", e)

um = od[~od.oid.isin(j.odds_row)]
um.sample(min(200, len(um)), random_state=0).drop(columns=["wtour"]).to_csv(f"{OUT}/unmatched_sample.csv", index=False)

od["matched"] = od.oid.isin(j.odds_row)
od["year"] = od.odate.dt.year
by_year = od.groupby("year").matched.agg(["size", "sum"]).rename(columns={"size": "rows", "sum": "matched"})
by_lvl = od.groupby("odds_level").matched.agg(["size", "sum"]).rename(columns={"size": "rows", "sum": "matched"})
by_yl = od.groupby(["year", "odds_level"]).matched.agg(["size", "sum"])
for t in (by_year, by_lvl):
    t["unmatched"] = t.rows - t.matched; t["rate"] = (t.matched / t.rows).round(4)
# played-only denominators (exclude not_played)
played = od[od.comment != "not_played"]
# warehouse coverage in odds years
whw = wh[(wh.date >= "2014-01-01") & (wh.date < "2026-01-01") & ~wh.walkover]
whc = whw.assign(m=whw.key.isin(j.key)).groupby("level").m.agg(["size", "sum"])
sa = j.score_agree
rep = {
    "odds_rows": int(len(od)), "matched": int(len(j)), "match_rate": round(len(j) / len(od), 4),
    "matched_by_phase": {int(k): int(v) for k, v in j.phase.value_counts().items()},
    "by_year": {int(k): {c: (float(v) if c == "rate" else int(v)) for c, v in r.items()} for k, r in by_year.iterrows()},
    "by_odds_level": {k: {c: (float(v) if c == "rate" else int(v)) for c, v in r.items()} for k, r in by_lvl.iterrows()},
    "by_year_level": {f"{y}|{l}": [int(r["size"]), int(r["sum"])] for (y, l), r in by_yl.iterrows()},
    "matched_by_warehouse_level": {k: int(v) for k, v in j.wh_level.value_counts().items()},
    "matched_wh_qualifying_rounds": int(j.wh_round.astype(str).str.match(r"^Q\d").sum()),
    "date_window_days": [LO, HI],
    "warehouse_2014_2025_coverage_by_level": {k: [int(r["size"]), int(r["sum"])] for k, r in whc.iterrows()},
    "unmatched_by_comment": {k: int(v) for k, v in od[~od.matched].comment.value_counts().items()},
    "unmatched_non_itf_with_reversed_orientation_hit": n_rev,
    "score_agreement": {"checked": int(sa.notna().sum()), "agree": int((sa == 1).sum()),
                        "rate": round(float((sa == 1).sum() / max(1, sa.notna().sum())), 4),
                        "rate_completed_only": round(float(j.loc[j.comment == "completed", "score_agree"].mean()), 4),
                        "by_phase": {int(k): round(float(v), 4) for k, v in j.groupby("phase").score_agree.mean().items()}},
    "date_offset_days_odds_minus_event_start": {k: int(v) for k, v in (j.match_date_formatted.pipe(pd.to_datetime).dt.normalize() - j.wh_date).dt.days.describe().items() if k != "count"},
}
json.dump(rep, open(f"{OUT}/report.json", "w"), indent=1, default=str)
print(json.dumps({k: rep[k] for k in ("odds_rows", "matched", "match_rate", "matched_by_phase", "by_odds_level", "score_agreement", "unmatched_non_itf_with_reversed_orientation_hit", "matched_wh_qualifying_rounds", "warehouse_2014_2025_coverage_by_level")}, indent=1, default=str))
print(by_year)
