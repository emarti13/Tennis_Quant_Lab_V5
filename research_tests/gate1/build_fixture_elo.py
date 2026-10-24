"""Leak-free pre-match Elo probability for every stored fixture (blind replication).

Two sources, in order:
 A. "in_event": the fixture is the same match as a TennisMyLife match in the rating history
    (edition -> (tour, tid) via v5_pricing.edition_events, same unordered player_id pair, unique
    in that event). Its probability is the one v5_baseline_elo.run gives that match: the state
    before that round (event start ratings + earlier rounds of the same event), per the
    module's leak-free ordering. Orientation to player1 uses only the identity of the keys.
 B. "week": otherwise, ratings = newcomer + sum of the per-event deltas of every event whose
    last_week < tennis_week(fixture start), EXCLUDING the fixture's own event (if mapped) and
    any event containing a match between the same two players. No in-event information.
Parameters: be.PRODUCTION_PARAMS (chosen on 2025 log loss, per module docstring).
Run from the repo root:  python <this file>
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
import v5_baseline_elo as be  # noqa: E402
from v5_fatigue_features import tennis_week  # noqa: E402
from v5_pricing import edition_events  # noqa: E402

OUT = Path(__file__).resolve().parent  # writes elo_fixture_probs.csv here
P = be.PRODUCTION_PARAMS


def run_with_deltas(matches, params):
    """Copy of be.run's loop (no stop/live) that also records each event's deltas."""
    order, weeks = be._events(matches)
    by_event = {e: g for e, g in matches.groupby(["tour", "tid"], sort=False)}
    ratings, pending, rows, event_deltas = {}, [], [], []
    fresh = lambda: be._fresh(params)
    get = lambda store, key: store[key] if key in store else ratings.get(key, fresh())
    for e in order:
        first = weeks[e]["first_week"]
        still = []
        for last, deltas in sorted(pending, key=lambda x: x[0]):
            if last < first:
                for key, d in deltas.items():
                    ratings[key] = ratings.get(key, fresh()) + d
            else:
                still.append((last, deltas))
        pending = still
        g = by_event[e]
        g = g[~g["walkover"].astype(bool)]
        local, start, unknown_deltas = {}, {}, {}
        known = g[g["rank"].notna()]
        for (stage, rank), grp in sorted(known.groupby(["stage", "rank"], sort=False), key=lambda kv: kv[0]):
            updates = []
            for m in grp.itertuples():
                w, l = m.winner_key, m.loser_key
                for k in (w, l):
                    start.setdefault(k, get({}, k).copy())
                rw, rl = get(local, w), get(local, l)
                s = be.surface_of(m.surface)
                p = be.probability(rw, rl, s, params)
                rows.append((m.key, m.tour, m.tid, m.date, w, l, s, p, rw[4], rl[4]))
                updates.append((w, l, rw, rl, p, s))
            for w, l, rw, rl, p, s in updates:
                dw, dl = be._update(rw, rl, p, s, params)
                local[w] = get(local, w) + dw
                local[l] = get(local, l) + dl
        for m in g[g["rank"].isna()].itertuples():
            w, l = m.winner_key, m.loser_key
            rw, rl = ratings.get(w, fresh()), ratings.get(l, fresh())
            s = be.surface_of(m.surface)
            p = be.probability(rw, rl, s, params)
            rows.append((m.key, m.tour, m.tid, m.date, w, l, s, p, rw[4], rl[4]))
            dw, dl = be._update(rw, rl, p, s, params)
            unknown_deltas[w] = unknown_deltas.get(w, np.zeros(8)) + dw
            unknown_deltas[l] = unknown_deltas.get(l, np.zeros(8)) + dl
        deltas = {k: v - start[k] for k, v in local.items()}
        for k, d in unknown_deltas.items():
            deltas[k] = deltas.get(k, np.zeros(8)) + d
        pending.append((weeks[e]["last_week"], deltas))
        event_deltas.append((e, weeks[e]["first_week"], weeks[e]["last_week"], deltas))
    cols = ["key", "tour", "tid", "date", "winner_key", "loser_key", "surface", "p_winner", "n_winner", "n_loser"]
    return pd.DataFrame(rows, columns=cols), event_deltas


def load_fixtures():
    f = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in sorted(glob.glob("market_history/fixtures/*.csv"))])
    f = f[f["resolution"] == "ok"].drop_duplicates("fixture_id", keep="last").copy()
    f["start"] = pd.to_datetime(f["cutoff_utc"], utc=True)
    return f[f["start"] < pd.Timestamp("2026-10-13", tz="UTC")].reset_index(drop=True)


def main():
    matches = be.load_matches(".")
    rows, event_deltas = run_with_deltas(matches, P)
    # parity with the module's own run()
    ref = be.run(matches, P)
    assert len(ref) == len(rows) and np.allclose(ref["p_winner"].values, rows["p_winner"].values), "copy != be.run"
    print("parity with be.run: OK", len(rows))

    fx = load_fixtures()
    cw = pd.read_csv("context_registry/master_schedule/crosswalk_tennismylife.csv", dtype=str, keep_default_na=False)
    events = edition_events(matches, cw)
    surf = matches.groupby(["tour", "tid"])["surface"].first().to_dict()

    rows["pair"] = ["|".join(sorted((a, b))) for a, b in zip(rows["winner_key"], rows["loser_key"])]
    by_ev_pair = rows.groupby(["tour", "tid", "pair"])
    counts = by_ev_pair.size()
    uniq = rows[rows.groupby(["tour", "tid", "pair"])["key"].transform("size") == 1]
    unique_rows = {(t, i, p): r for t, i, p, r in zip(uniq["tour"], uniq["tid"], uniq["pair"], uniq.to_dict("records"))}
    pair_events = rows.groupby("pair").apply(lambda g: set(zip(g["tour"], g["tid"]))).to_dict()

    # master schedule surface for fallback (attributes only from the master schedule)
    from v5_tournament_identity import load_master_schedule
    ms = pd.concat([load_master_schedule(p)[0] for p in glob.glob("context_registry/master_schedule/master_schedule_*.csv")])
    ms_surface = {}
    if "edition_key" in ms.columns and "surface" in ms.columns:
        ms_surface = dict(zip(ms["edition_key"], ms["surface"]))

    out = []
    week_needed = []
    for f in fx.itertuples():
        a, b = f.player1_id, f.player2_id
        pair = "|".join(sorted((a, b)))
        ev = events.get(f.edition_key)
        rec = {"fixture_id": f.fixture_id, "event": ev}
        if ev is not None and counts.get((ev[0], ev[1], pair), 0) == 1:
            r = unique_rows[(ev[0], ev[1], pair)]
            p1_is_w = r["winner_key"] == a
            rec.update(src="in_event", p_elo=r["p_winner"] if p1_is_w else 1 - r["p_winner"],
                       n1=r["n_winner"] if p1_is_w else r["n_loser"], n2=r["n_loser"] if p1_is_w else r["n_winner"])
            out.append(rec)
        else:
            week_needed.append((f, ev, pair))
            out.append(rec)

    # fallback: per-week cumulative states, built incrementally over 2026 weeks
    ed_map = {e: (fw, lw, d) for e, fw, lw, d in event_deltas}
    ed_sorted = sorted(event_deltas, key=lambda x: x[2])
    fb = {}
    if week_needed:
        weeks_needed = sorted({tennis_week(f.start) for f, _, _ in week_needed})
        state, i = {}, 0
        for W in weeks_needed:
            while i < len(ed_sorted) and ed_sorted[i][2] < W:
                for k, d in ed_sorted[i][3].items():
                    state[k] = state.get(k, be._fresh(P)) + d
                i += 1
            for f, ev, pair in [x for x in week_needed if tennis_week(x[0].start) == W]:
                excl = set(pair_events.get(pair, set()))
                if ev is not None:
                    excl.add(ev)
                vecs = []
                for pid in (f.player1_id, f.player2_id):
                    v = state.get(pid)
                    for e2 in excl:
                        if e2 in ed_map and ed_map[e2][1] < W and pid in ed_map[e2][2]:
                            v = (v if v is not None else be._fresh(P)) - ed_map[e2][2][pid]
                    vecs.append(v)
                if any(v is None for v in vecs):
                    fb[f.fixture_id] = dict(src="week", p_elo=np.nan, n1=np.nan, n2=np.nan)
                    continue
                s = ms_surface.get(f.edition_key) or (surf.get(ev) if ev else None)
                s = be.surface_of(s)
                fb[f.fixture_id] = dict(src="week", p_elo=be.probability(vecs[0], vecs[1], s, P),
                                        n1=vecs[0][4], n2=vecs[1][4])
    res = []
    for rec in out:
        if "src" not in rec:
            rec.update(fb.get(rec["fixture_id"], dict(src="week", p_elo=np.nan, n1=np.nan, n2=np.nan)))
        rec["event"] = "" if rec["event"] is None else f"{rec['event'][0]}|{rec['event'][1]}"
        res.append(rec)
    res = pd.DataFrame(res)
    print(res["src"].value_counts(), res["p_elo"].isna().sum())
    res.to_csv(OUT / "elo_fixture_probs.csv", index=False)


if __name__ == "__main__":
    main()
