"""Player identity: our own player ids, and every source id or spelling as an alias.

Design: docs/superpowers/specs/2026-10-13-player-identity-design.md (approved 2026-10-13).

- Players are built from TennisMyLife results. TennisMyLife ids are mostly stable but not
  clean (a second WTA id scheme in 2026, ids stored as '211817.0', a few missing ids), and
  different people can share a name. Ids are joined into one player only when the folded
  name, the tour and the country agree and the two ids never play different events in
  the same week. Anything else goes to review; nothing is merged on a name alone.
- OddsPapi participant ids are linked by results: the same match, in the same edition
  (tournament crosswalks), between compatible names; then by draw order for the opponent
  of an already linked player. Before results exist, only a unique exact folded name is
  accepted; partial names and suffixes ('Jr', '(2001)') go to review. A player with no
  candidate at all is 'no_history', which is never a rating.
- Stored rows marked confirmed, user or rejected are never changed by a later build.
  Player ids are never reused or renumbered.

Production does not read these tables yet (rebuild plan, Step 2).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from v5_tournament_identity import _same_player, player_key, resolve_edition

HISTORY_FILES = {"ATP.csv": "M", "ATPQualifiers.csv": "M", "Challenger.csv": "M", "WTA.csv": "W"}
ROUND_ORDER = {"Q1": 0, "Q2": 1, "Q3": 2, "R128": 3, "R64": 4, "R32": 5, "RR": 5, "R16": 6, "QF": 7, "SF": 8, "BR": 8, "F": 9}
ODDSPAPI_TOUR = {"ATP": "M", "Challenger": "M", "WTA": "W", "WTA 125K": "W"}
# TennisMyLife mostly uses IOC codes; a few rows use ISO alpha-3.
ISO3_TO_IOC = {"PRT": "POR", "DEU": "GER", "CHE": "SUI", "NLD": "NED", "HRV": "CRO", "GRC": "GRE",
               "DNK": "DEN", "BGR": "BUL", "LVA": "LAT", "SVN": "SLO", "ZAF": "RSA", "IDN": "INA",
               "MYS": "MAS", "PHL": "PHI", "CHL": "CHI", "URY": "URU", "PRY": "PAR", "LKA": "SRI"}
KEPT_STATUSES = {"confirmed", "user", "rejected"}
USABLE_STATUSES = {"confirmed", "auto", "user"}
# Draw slots a feed lists before the player is known: "WQF1", "Qf3", "WSF2", "R16P14",
# "Q1", "LL2", "TBD", "Qualifier". They are not players and are never priced.
_PLACEHOLDER = re.compile(r"^(?:(?:W?Q[FS]?|W?SF|R\d+P|LL|Q)\d+|TBD|TBA|BYE|QUALIFIER(?: \d+)?|LUCKY LOSER(?: \d+)?)$", re.I)


def is_placeholder_participant(name) -> bool:
    return bool(_PLACEHOLDER.match(str(name or "").strip()))


_SUFFIX = re.compile(r"\(\s*\d{4}\s*\)|\b(?:jr|sr|ii|iii)\b\.?", re.I)

PLAYER_COLUMNS = ["player_id", "tour", "display_name", "country", "first_date", "last_date", "matches", "status", "note"]
TML_ALIAS_COLUMNS = ["tour", "tml_id", "player_id", "names", "countries", "matches", "status", "method", "set_on"]
ODDS_ALIAS_COLUMNS = ["participant_id", "tour", "names", "player_id", "status", "method",
                      "shared_matches", "candidates", "note", "set_on"]


# ---------------------------------------------------------------- TennisMyLife results
def normalize_tml_id(value) -> str | None:
    s = str(value if value is not None else "").strip()
    s = re.sub(r"\.0$", "", s)
    return None if s.lower() in {"", "nan", "none"} else s


def _country(value) -> str:
    s = str(value if value is not None else "").strip().upper()
    return "" if s in {"", "NAN", "NONE"} else ISO3_TO_IOC.get(s, s)


def load_tml_matches(history_dir: str | Path = ".v5_history_cache",
                     results_path: str | Path = "v5_results_ready/tennismylife_results.csv") -> pd.DataFrame:
    """One row per TennisMyLife match: tour (M/W), tourney, date, round and both players."""
    cols = ["tourney_id", "tourney_date", "round", "winner_id", "winner_name", "winner_ioc",
            "loser_id", "loser_name", "loser_ioc"]
    frames = []
    for name, tour in HISTORY_FILES.items():
        p = Path(history_dir) / name
        if p.exists():
            frames.append(pd.read_csv(p, usecols=cols, low_memory=False).assign(tour=tour))
    rp = Path(results_path)
    if rp.exists():
        r = pd.read_csv(rp, usecols=cols + ["result_file"], low_memory=False)
        r["tour"] = r["result_file"].astype(str).str.contains("wta", case=False).map({True: "W", False: "M"})
        frames.append(r.drop(columns="result_file"))
    m = pd.concat(frames, ignore_index=True)
    m["date"] = pd.to_datetime(m["tourney_date"].astype(str).str[:8], format="%Y%m%d", errors="coerce")
    for side in ("winner", "loser"):
        m[f"{side}_id"] = m[f"{side}_id"].map(normalize_tml_id)
        m[f"{side}_key"] = m[f"{side}_name"].map(player_key)
        m[f"{side}_ioc"] = m[f"{side}_ioc"].map(_country)
    m["tourney_id"] = m["tourney_id"].astype(str)
    # The same match can sit in a history file and in the current-season file.
    m = m.drop_duplicates(["tour", "tourney_id", "round", "winner_key", "loser_key"]).reset_index(drop=True)
    return m


def _appearances(matches: pd.DataFrame) -> pd.DataFrame:
    a = pd.concat([
        matches[["tour", "tourney_id", "date", f"{s}_id", f"{s}_name", f"{s}_key", f"{s}_ioc"]]
        .set_axis(["tour", "tourney_id", "date", "id", "name", "key", "ioc"], axis=1)
        for s in ("winner", "loser")], ignore_index=True)
    # A row without an id is its own node, named by tour and folded name.
    a["node"] = [i if i else f"name:{k}" for i, k in zip(a["id"], a["key"])]
    a["week"] = a["date"].dt.to_period("W-SUN").astype(str)
    return a


# ---------------------------------------------------------------- players
class _UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _compatible(a: dict, b: dict) -> tuple[bool, str]:
    """Can two TennisMyLife ids with the same folded name be one person?"""
    if a["countries"] and b["countries"] and not (a["countries"] & b["countries"]):
        return False, f"same name, different country ({'/'.join(sorted(a['countries']))} vs {'/'.join(sorted(b['countries']))})"
    clash = {w for w, t in a["week_tourneys"].items() if w in b["week_tourneys"] and t != b["week_tourneys"][w]}
    if clash:
        return False, f"same name, different events in the same week ({sorted(clash)[0]})"
    return True, ""


def build_players(matches: pd.DataFrame, existing_players: pd.DataFrame | None = None,
                  existing_alias: pd.DataFrame | None = None, *, set_on: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Players and the TennisMyLife alias table. Returns (players, alias_tennismylife, review).

    Stable ids: a TennisMyLife id keeps the player id it had. A user row in the stored
    alias table fixes its player id whatever the rules say.
    """
    a = _appearances(matches)
    nodes = {}
    for (tour, node), g in a.groupby(["tour", "node"], sort=False):
        nodes[(tour, node)] = {
            "tour": tour, "node": node, "tml_id": None if node.startswith("name:") else node,
            "keys": set(g["key"]), "names": Counter(g["name"].astype(str).str.strip()),
            "countries": set(c for c in g["ioc"] if c),
            "latest_country": next((c for c in g.sort_values("date")["ioc"][::-1] if c), ""),
            "week_tourneys": dict(zip(g["week"], g["tourney_id"])),
            "first": g["date"].min(), "last": g["date"].max(), "matches": len(g),
        }
    uf = _UnionFind()
    review = []
    by_key = defaultdict(list)
    for k, n in nodes.items():
        uf.find(k)
        for key in n["keys"]:
            by_key[(n["tour"], key)].append(k)
    for (tour, key), members in by_key.items():
        if len(members) < 2:
            continue
        for i, x in enumerate(members):
            for y in members[i + 1:]:
                ok, why = _compatible(nodes[x], nodes[y])
                if ok:
                    uf.union(x, y)
                else:
                    review.append({"kind": "tennismylife_ids", "tour": tour, "subject": f"{x[1]} / {y[1]}",
                                   "names": f"{nodes[x]['names'].most_common(1)[0][0]} / {nodes[y]['names'].most_common(1)[0][0]}",
                                   "reason": why, "candidates": ""})

    # Stable player ids.
    stored = existing_alias if existing_alias is not None and not existing_alias.empty else pd.DataFrame(columns=TML_ALIAS_COLUMNS)
    stored_pid = {(r.tour, r.tml_id): r.player_id for r in stored.itertuples()}
    user_pid = {(r.tour, r.tml_id): r.player_id for r in stored.itertuples() if r.status == "user"}
    comps = defaultdict(list)
    for k in nodes:
        comps[uf.find(k)].append(k)
    used = set()
    numbers = [int(p.split("-")[1]) for p in stored["player_id"] if isinstance(p, str) and "-" in p]
    if existing_players is not None and not existing_players.empty:
        numbers += [int(p.split("-")[1]) for p in existing_players["player_id"] if isinstance(p, str) and "-" in p]
    next_no = max(numbers, default=0) + 1
    pid_of = {}
    for root, members in sorted(comps.items(), key=lambda kv: -sum(nodes[m]["matches"] for m in kv[1])):
        forced = {user_pid[(m[0], m[1])] for m in members if (m[0], m[1]) in user_pid}
        prior = Counter(stored_pid[(m[0], m[1])] for m in members if (m[0], m[1]) in stored_pid)
        if len(forced) == 1:
            pid = forced.pop()
        else:
            pid = next((p for p, _ in prior.most_common() if p not in used), None)
            if pid is None:
                pid = f"{members[0][0]}-{next_no:06d}"
                next_no += 1
        used.add(pid)
        for m in members:
            pid_of[m] = pid

    players, alias = [], []
    for root, members in comps.items():
        pid = pid_of[members[0]]
        names = sum((nodes[m]["names"] for m in members), Counter())
        latest = max(members, key=lambda m: nodes[m]["last"])
        players.append({
            "player_id": pid, "tour": members[0][0], "display_name": names.most_common(1)[0][0],
            "country": nodes[latest]["latest_country"],
            "first_date": min(nodes[m]["first"] for m in members).date().isoformat(),
            "last_date": max(nodes[m]["last"] for m in members).date().isoformat(),
            "matches": sum(nodes[m]["matches"] for m in members), "status": "active",
            "note": f"{len(members)} TennisMyLife ids" if len(members) > 1 else "",
        })
        for m in members:
            n = nodes[m]
            keep = stored[(stored["tour"] == m[0]) & (stored["tml_id"] == m[1]) & stored["status"].isin(KEPT_STATUSES)]
            alias.append({
                "tour": m[0], "tml_id": m[1], "player_id": pid,
                "names": " | ".join(sorted(n["names"])), "countries": "/".join(sorted(n["countries"])),
                "matches": n["matches"],
                "status": keep["status"].iloc[0] if len(keep) else ("auto" if n["tml_id"] else "review"),
                "method": "tennismylife_id" if len(members) == 1 else "same name, tour and country; no same-week clash",
                "set_on": keep["set_on"].iloc[0] if len(keep) else set_on,
            })
            if not n["tml_id"]:
                review.append({"kind": "tennismylife_ids", "tour": m[0], "subject": m[1], "names": n["names"].most_common(1)[0][0],
                               "reason": "TennisMyLife rows without a player id", "candidates": pid})
    # Player ids that no component uses any more (merged by a later build) stay, marked.
    players = pd.DataFrame(players, columns=PLAYER_COLUMNS)
    if existing_players is not None and not existing_players.empty:
        gone = existing_players[~existing_players["player_id"].isin(players["player_id"])].copy()
        gone["status"] = gone["status"].where(gone["status"].str.startswith("merged_into"), "retired")
        players = pd.concat([players, gone[PLAYER_COLUMNS]], ignore_index=True)
    return (players.sort_values("player_id").reset_index(drop=True),
            pd.DataFrame(alias, columns=TML_ALIAS_COLUMNS).sort_values(["tour", "tml_id"]).reset_index(drop=True),
            pd.DataFrame(review, columns=["kind", "tour", "subject", "names", "reason", "candidates"]))


# ---------------------------------------------------------------- OddsPapi participants
def _tml_with_editions(matches: pd.DataFrame, crosswalk_tml: pd.DataFrame, alias_tml: pd.DataFrame, year: int) -> pd.DataFrame:
    m = matches[matches["date"].dt.year == year].copy()
    m["edition"] = [resolve_edition(crosswalk_tml, t, d, gap_days=6) for t, d in zip(m["tourney_id"], m["date"])]
    m = m[m["edition"].notna()].copy()
    pid = {(r.tour, r.tml_id): r.player_id for r in alias_tml.itertuples()}
    for side in ("winner", "loser"):
        m[f"{side}_pid"] = [pid.get((t, i if i else f"name:{k}")) for t, i, k in zip(m["tour"], m[f"{side}_id"], m[f"{side}_key"])]
    m["round_no"] = m["round"].map(ROUND_ORDER)
    return m


def _oddspapi_fixtures(fixtures: pd.DataFrame, crosswalk_odds: pd.DataFrame, year: int) -> pd.DataFrame:
    f = fixtures.copy()
    f["start"] = pd.to_datetime(f["start_time_utc"], utc=True, errors="coerce")
    f = f[(f["start"].dt.year == year) & ~f["tournament_name"].astype(str).str.contains("doubles", case=False)]
    f["tour"] = f["category_name"].map(ODDSPAPI_TOUR)
    f = f[f["tour"].notna()].copy()
    f["edition"] = [resolve_edition(crosswalk_odds, t, d, gap_days=4) for t, d in zip(f["tournament_id"], f["start"])]
    for s in ("1", "2"):
        f[f"p{s}"] = f[f"participant{s}_id"].astype("Int64").astype(str)
        f[f"k{s}"] = f[f"participant{s}_name"].map(player_key)
    return f


def link_oddspapi(fixtures: pd.DataFrame, crosswalk_odds: pd.DataFrame, matches: pd.DataFrame,
                  crosswalk_tml: pd.DataFrame, alias_tml: pd.DataFrame, players: pd.DataFrame,
                  existing: pd.DataFrame | None = None, *, year: int, set_on: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Link each OddsPapi participant id to a player. Returns (alias_oddspapi, review, drift)."""
    f = _oddspapi_fixtures(fixtures, crosswalk_odds, year)
    t = _tml_with_editions(matches, crosswalk_tml, alias_tml, year)
    evidence: dict[str, Counter] = defaultdict(Counter)
    method: dict[str, Counter] = defaultdict(Counter)
    counted: set[tuple[str, str]] = set()   # (fixture_id, participant) already used as evidence

    # 1. Same match, compatible names on both sides.
    tml_by_ed = {e: g for e, g in t.groupby("edition")}
    for e, fg in f[f["edition"].notna()].groupby("edition"):
        tg = tml_by_ed.get(e)
        if tg is None:
            continue
        pairs = list(zip(tg["winner_key"], tg["loser_key"], tg["winner_pid"], tg["loser_pid"]))
        for fid, p1, k1, p2, k2 in zip(fg["fixture_id"].astype(str), fg["p1"], fg["k1"], fg["p2"], fg["k2"]):
            hits = set()
            for wk, lk, wp, lp in pairs:
                if not (wp and lp):
                    continue
                if _same_player(k1, wk) and _same_player(k2, lk):
                    hits.add((wp, lp))
                elif _same_player(k1, lk) and _same_player(k2, wk):
                    hits.add((lp, wp))
            if len(hits) == 1:
                a, b = hits.pop()
                evidence[p1][a] += 1; method[p1]["same match"] += 1
                evidence[p2][b] += 1; method[p2]["same match"] += 1
                counted |= {(fid, p1), (fid, p2)}

    # 2. Draw order: a linked player's fixtures in an edition, in time order, against the
    #    player's results in round order. Used only when both counts agree.
    linked = {p: c.most_common(1)[0][0] for p, c in evidence.items() if len(c) == 1 and sum(c.values()) >= 2}
    for e, fg in f[f["edition"].notna()].groupby("edition"):
        tg = tml_by_ed.get(e)
        if tg is None:
            continue
        for p, pid in linked.items():
            mine = fg[(fg["p1"] == p) | (fg["p2"] == p)].sort_values("start")
            if mine.empty:
                continue
            res = tg[(tg["winner_pid"] == pid) | (tg["loser_pid"] == pid)].dropna(subset=["round_no"]).sort_values("round_no")
            if len(res) != len(mine) or res["round_no"].duplicated().any():
                continue
            for fx, rs in zip(mine.itertuples(), res.itertuples()):
                opp = fx.p2 if fx.p1 == p else fx.p1
                opp_pid = rs.loser_pid if rs.winner_pid == pid else rs.winner_pid
                if opp_pid and (str(fx.fixture_id), opp) not in counted:
                    evidence[opp][opp_pid] += 1; method[opp]["draw order"] += 1
                    counted.add((str(fx.fixture_id), opp))

    # Names, for participants results cannot link.
    names_by_tour = defaultdict(lambda: defaultdict(set))
    for r in alias_tml.itertuples():
        for n in str(r.names).split(" | "):
            names_by_tour[r.tour][player_key(n)].add(r.player_id)
    tokens_by_tour = {tour: [(set(k.split()), pids) for k, pids in idx.items()] for tour, idx in names_by_tour.items()}

    seen = pd.concat([f[["p1", "participant1_name", "tour"]].set_axis(["pid", "name", "tour"], axis=1),
                      f[["p2", "participant2_name", "tour"]].set_axis(["pid", "name", "tour"], axis=1)])
    rows = []
    for pid_odds, g in seen.groupby("pid"):
        tour = g["tour"].mode().iloc[0]
        names = sorted(set(g["name"].astype(str)))
        ev = evidence.get(pid_odds, Counter())
        row = {"participant_id": pid_odds, "tour": tour, "names": " | ".join(names), "player_id": "",
               "status": "", "method": "", "shared_matches": int(sum(ev.values())), "candidates": "", "note": "", "set_on": set_on}
        if any(is_placeholder_participant(n) for n in names):
            row.update(status="placeholder", method="draw slot, not a player")
        elif len(ev) == 1:
            p, n = ev.most_common(1)[0]
            row.update(player_id=p, status="confirmed" if n >= 2 else "auto",
                       method=" + ".join(sorted(method[pid_odds])))
        elif len(ev) > 1:
            row.update(status="review", method="results disagree",
                       candidates=", ".join(f"{p} ({n})" for p, n in ev.most_common()))
        else:
            key = player_key(names[0])
            exact = names_by_tour[tour].get(key, set())
            if len(exact) == 1:
                row.update(player_id=next(iter(exact)), status="auto", method="exact name, unique in tour")
            elif len(exact) > 1:
                row.update(status="review", method="exact name, several players", candidates=", ".join(sorted(exact)))
            else:
                stripped = player_key(_SUFFIX.sub(" ", names[0]))
                toks = set(stripped.split())
                cands = set(names_by_tour[tour].get(stripped, set()))
                for kt, pids in tokens_by_tour.get(tour, []):
                    if len(toks) >= 2 and len(kt) >= 2 and (toks <= kt or kt <= toks) and len(toks & kt) >= 2:
                        cands |= pids
                if cands:
                    row.update(status="review", method="partial name or suffix", candidates=", ".join(sorted(cands)[:6]))
                else:
                    row.update(status="no_history", method="no candidate in our history")
        rows.append(row)
    fresh = pd.DataFrame(rows, columns=ODDS_ALIAS_COLUMNS)

    # Kept rows win; report where the fresh build disagrees.
    drift = pd.DataFrame(columns=["participant_id", "stored", "fresh", "fresh_status"])
    if existing is not None and not existing.empty:
        kept = existing[existing["status"].isin(KEPT_STATUSES)].copy()
        cmp = kept.merge(fresh[["participant_id", "player_id", "status"]], on="participant_id", suffixes=("", "_fresh"))
        drift = cmp[(cmp["player_id"] != cmp["player_id_fresh"]) & (cmp["status_fresh"] != "")].rename(
            columns={"player_id": "stored", "player_id_fresh": "fresh", "status_fresh": "fresh_status"})[
            ["participant_id", "stored", "fresh", "fresh_status"]]
        fresh = pd.concat([kept[ODDS_ALIAS_COLUMNS], fresh[~fresh["participant_id"].isin(kept["participant_id"])]], ignore_index=True)

    review = fresh[fresh["status"] == "review"].assign(kind="oddspapi_participant")
    review = review.rename(columns={"participant_id": "subject", "method": "reason"})[["kind", "tour", "subject", "names", "reason", "candidates"]]
    return fresh.sort_values("participant_id").reset_index(drop=True), review.reset_index(drop=True), drift.reset_index(drop=True)


# ---------------------------------------------------------------- lookups
def load_table(path: str | Path, columns: list[str]) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=columns)
    return pd.read_csv(p, dtype=str, keep_default_na=False)


def resolve_oddspapi_player(alias_oddspapi: pd.DataFrame, participant_id) -> tuple[str | None, str]:
    """(player_id, status) for an OddsPapi participant. player_id is None unless the link
    is usable; status says why (review, no_history, placeholder, rejected, unknown)."""
    rows = alias_oddspapi[alias_oddspapi["participant_id"].astype(str) == str(participant_id)]
    if rows.empty:
        return None, "unknown"
    r = rows.iloc[0]
    if r["status"] in USABLE_STATUSES and r["player_id"]:
        return r["player_id"], r["status"]
    return None, r["status"]
