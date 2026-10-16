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

from v5_tournament_identity import _same_player, player_key as _folded_key, resolve_edition

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
# Not after g or q: Spanish and Portuguese "gue"/"que" are not umlauts (Guerra, Rodriguez).
_UMLAUT_PAIRS = re.compile(r"(?<=[a-fh-pr-z])(ae|oe|ue)")


def player_key(name) -> str:
    """Order-independent folded name, with German umlauts spelled either way equal:
    "Würth" folds to "wurth" and "Wuerth" (ü written as ue) to "wurth" too. Applied to
    both sides of every comparison, so "Manuel" becomes "manul" everywhere and still
    matches itself."""
    return " ".join(sorted(_UMLAUT_PAIRS.sub(lambda m: m.group(1)[0], w) for w in _folded_key(name).split()))


def _present(value) -> bool:
    """A real id: a non-empty string (None and NaN are not)."""
    return isinstance(value, str) and value != ""


def normalize_tml_id(value) -> str | None:
    s = str(value if value is not None else "").strip()
    s = re.sub(r"\.0$", "", s)
    return None if s.lower() in {"", "nan", "none"} else s


def _country(value) -> str:
    s = str(value if value is not None else "").strip().upper()
    return "" if s in {"", "NAN", "NONE"} else ISO3_TO_IOC.get(s, s)


ROW_CORRECTION_COLUMNS = ["tour", "tml_id", "name", "new_tml_id", "note"]


def load_tml_matches(history_dir: str | Path = ".v5_history_cache",
                     results_path: str | Path = "v5_results_ready/tennismylife_results.csv",
                     corrections_path: str | Path = "context_registry/players/tml_row_corrections.csv") -> pd.DataFrame:
    """One row per TennisMyLife match: tour (M/W), tourney, date, round and both players.

    tml_row_corrections.csv (user decisions) moves rows that TennisMyLife filed under the
    wrong player id: rows with this tour, id and exact name get new_tml_id instead (empty
    new_tml_id: no id, so the rows form their own player by name)."""
    cols = ["tourney_id", "tourney_date", "round", "winner_id", "winner_name", "winner_ioc", "winner_age",
            "loser_id", "loser_name", "loser_ioc", "loser_age"]
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
    fixes = load_table(corrections_path, ROW_CORRECTION_COLUMNS)
    for side in ("winner", "loser"):
        m[f"{side}_id"] = m[f"{side}_id"].map(normalize_tml_id)
        for fx in fixes.itertuples():
            hit = (m["tour"] == fx.tour) & (m[f"{side}_id"] == fx.tml_id) & (m[f"{side}_name"].astype(str).str.strip() == fx.name)
            m.loc[hit, f"{side}_id"] = fx.new_tml_id or None
        m[f"{side}_key"] = m[f"{side}_name"].map(player_key)
        m[f"{side}_ioc"] = m[f"{side}_ioc"].map(_country)
        # Birth date estimated from the age TennisMyLife records at each match. Ages
        # outside 13-50 are data errors (the 2026 WTA id scheme carries some).
        age = pd.to_numeric(m[f"{side}_age"], errors="coerce")
        birth = m["date"].dt.year + m["date"].dt.dayofyear / 365.25 - age
        m[f"{side}_birth"] = birth.where(age.between(13, 50))
    m["tourney_id"] = m["tourney_id"].astype(str)
    # The same match can sit in a history file and in the current-season file.
    m = m.drop_duplicates(["tour", "tourney_id", "round", "winner_key", "loser_key"]).reset_index(drop=True)
    return m


def _appearances(matches: pd.DataFrame) -> pd.DataFrame:
    a = pd.concat([
        matches[["tour", "tourney_id", "date", f"{s}_id", f"{s}_name", f"{s}_key", f"{s}_ioc", f"{s}_birth"]]
        .set_axis(["tour", "tourney_id", "date", "id", "name", "key", "ioc", "birth"], axis=1)
        for s in ("winner", "loser")], ignore_index=True)
    a["ioc"] = a["ioc"].map(_country)
    # A row without an id is its own node, named by tour and folded name.
    # Stored names of id-less nodes use the plain folded name, so a change to how names
    # are compared (e.g. umlauts) never renames a node and never mints a new player id.
    a["node"] = [i if _present(i) else f"name:{_folded_key(n)}" for i, n in zip(a["id"], a["name"])]
    # Tennis week: an event dated Saturday or Sunday belongs to the following Monday's week
    # (TennisMyLife dates Bad Homburg 2026 on Sunday June 21, the eve of its main draw).
    a["week"] = (a["date"] + pd.Timedelta(days=2)).dt.to_period("W-SUN").astype(str)
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


SAME_BIRTH_YEARS = 0.1      # two ids born within ~5 weeks: one person
DIFFERENT_BIRTH_YEARS = 0.5  # born more than six months apart: two people
# The 2026 WTA rows with a second id or no id fall up to ~70 days after the main id's last
# match (Begu: last main-id match April 20, broken rows late June).
CAREER_MARGIN_DAYS = 90


def _compatible(a: dict, b: dict) -> tuple[str, str]:
    """Two TennisMyLife ids with the same folded name and tour: 'join', 'separate' or 'review'.

    Different TennisMyLife ids are different players unless the evidence says otherwise
    (the same name recurs across 2010-2026: two "David Warren" born 1988 and 1994).
    Evidence, in order: birth date (from recorded ages), country, same-week play, and
    for ids without a usable age, one id's matches lying inside the other's career.
    """
    if a["countries"] and b["countries"] and not (a["countries"] & b["countries"]):
        return "review", (f"same name, different country ({'/'.join(sorted(a['countries']))} vs "
                          f"{'/'.join(sorted(b['countries']))})" + _birth_note(a, b))
    clash = {w for w, t in a["week_tourneys"].items() if w in b["week_tourneys"] and t != b["week_tourneys"][w]}
    if clash:
        return "separate", f"same name, different events in the same week ({sorted(clash)[0]})"
    if a["birth"] is not None and b["birth"] is not None:
        gap = abs(a["birth"] - b["birth"])
        if gap <= SAME_BIRTH_YEARS:
            return "join", "same name, country and birth date"
        if gap > DIFFERENT_BIRTH_YEARS:
            return "separate", f"same name, born {a['birth']:.0f} and {b['birth']:.0f}"
        return "review", f"same name, birth dates {gap:.1f} years apart"
    inner, outer = sorted((a, b), key=lambda n: (n["last"] - n["first"]))
    margin = pd.Timedelta(days=CAREER_MARGIN_DAYS)
    if outer["first"] - margin <= inner["first"] and inner["last"] <= outer["last"] + margin:
        return "join", "same name and country; one id's matches lie within the other's career (no usable age)"
    return "review", "same name and country, no usable age, careers more than 90 days apart"


def _same_root(uf: "_UnionFind", tour: str, subject: str) -> bool:
    x, y = (t.strip() for t in subject.split(" / ", 1))
    return uf.find((tour, x)) == uf.find((tour, y))


def _birth_note(a: dict, b: dict) -> str:
    if a["birth"] is None or b["birth"] is None:
        return ""
    gap = abs(a["birth"] - b["birth"])
    return "; same birth date" if gap <= SAME_BIRTH_YEARS else f"; born {a['birth']:.0f} and {b['birth']:.0f}"


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
            "birth": float(g["birth"].median()) if g["birth"].notna().any() else None,
        }
    uf = _UnionFind()
    review = []
    joined_how = defaultdict(set)
    # One id, a name that shares no word with the id's usual name: a row filed under the
    # wrong player (MH30 is John Millman; one row says Marc-Andrea Huesler).
    for k, n in nodes.items():
        main = n["names"].most_common(1)[0][0]
        for other, cnt in n["names"].items():
            if other != main and not (set(player_key(other).split()) & set(player_key(main).split())):
                review.append({"kind": "tennismylife_ids", "tour": n["tour"], "subject": k[1],
                               "names": f"{main} / {other}",
                               "reason": f"{cnt} row(s) under another name for this id; the rows may belong to another player",
                               "candidates": ""})
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
                verdict, why = _compatible(nodes[x], nodes[y])
                if verdict == "join":
                    uf.union(x, y)
                    joined_how[x].add(why); joined_how[y].add(why)
                else:
                    review.append({"kind": "tennismylife_ids" if verdict == "review" else "kept_apart",
                                   "tour": tour, "subject": f"{x[1]} / {y[1]}",
                                   "names": f"{nodes[x]['names'].most_common(1)[0][0]} / {nodes[y]['names'].most_common(1)[0][0]}",
                                   "reason": why, "candidates": ""})

    # A person's decision that several ids are one player (user rows sharing a player id).
    stored_rows = existing_alias if existing_alias is not None and not existing_alias.empty else pd.DataFrame(columns=TML_ALIAS_COLUMNS)
    for _, g in stored_rows[stored_rows["status"] == "user"].groupby("player_id"):
        keys = [(t, i) for t, i in zip(g["tour"], g["tml_id"]) if (t, i) in nodes]
        for k in keys[1:]:
            uf.union(keys[0], k)
            joined_how[keys[0]].add("user decision"); joined_how[k].add("user decision")
    review = [r for r in review if not (" / " in r["subject"] and r["kind"] == "tennismylife_ids"
                                        and _same_root(uf, r["tour"], r["subject"]))]

    # Stable player ids.
    stored = existing_alias if existing_alias is not None and not existing_alias.empty else pd.DataFrame(columns=TML_ALIAS_COLUMNS)
    stored_pid = {(r.tour, r.tml_id): r.player_id for r in stored.itertuples()}
    stored_set_on = {(r.tour, r.tml_id, r.player_id): r.set_on for r in stored.itertuples()}
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
                "status": keep["status"].iloc[0] if len(keep) else (
                    "auto"),
                "method": "; ".join(sorted(joined_how[m])) or "tennismylife_id",
                "set_on": keep["set_on"].iloc[0] if len(keep) else stored_set_on.get((m[0], m[1], pid), set_on),
            })
            if not n["tml_id"] and not any(nodes[x]["tml_id"] for x in members):
                review.append({"kind": "information", "tour": m[0], "subject": m[1], "names": n["names"].most_common(1)[0][0],
                               "reason": "TennisMyLife rows without a player id; kept as their own player", "candidates": pid})
    # Player ids that no component uses any more (merged by a later build) stay, marked.
    players = pd.DataFrame(players, columns=PLAYER_COLUMNS)
    if existing_players is not None and not existing_players.empty:
        gone = existing_players[~existing_players["player_id"].isin(players["player_id"])].copy()
        # Where did a vanished id go? Follow its stored TennisMyLife ids to their new player.
        now = {(r["tour"], r["tml_id"]): r["player_id"] for r in alias}
        moved = {}
        for r in stored.itertuples():
            new = now.get((r.tour, r.tml_id))
            if new and new != r.player_id:
                moved.setdefault(r.player_id, new)
        gone["status"] = [st if str(st).startswith("merged_into") else (f"merged_into:{moved[p]}" if p in moved else "retired")
                          for p, st in zip(gone["player_id"], gone["status"])]
        players = pd.concat([players, gone[PLAYER_COLUMNS]], ignore_index=True)
    return (players.sort_values("player_id").reset_index(drop=True),
            pd.DataFrame(alias, columns=TML_ALIAS_COLUMNS).sort_values(["tour", "tml_id"]).reset_index(drop=True),
            pd.DataFrame(review, columns=["kind", "tour", "subject", "names", "reason", "candidates"]))


# ---------------------------------------------------------------- OddsPapi participants
def _editions(crosswalk: pd.DataFrame, tournament_ids, dates, *, gap_days: int) -> list:
    """resolve_edition for many rows, looked up once per (tournament, day)."""
    cache = {}
    out = []
    for t, d in zip(tournament_ids, dates):
        key = (str(t), pd.Timestamp(d).date())
        if key not in cache:
            cache[key] = resolve_edition(crosswalk, key[0], key[1], gap_days=gap_days)
        out.append(cache[key])
    return out


def _tml_with_editions(matches: pd.DataFrame, crosswalk_tml: pd.DataFrame, alias_tml: pd.DataFrame, year: int) -> pd.DataFrame:
    m = matches[matches["date"].dt.year == year].copy()
    m["edition"] = _editions(crosswalk_tml, m["tourney_id"], m["date"], gap_days=6)
    m = m[m["edition"].notna()].copy()
    pid = {(r.tour, r.tml_id): r.player_id for r in alias_tml.itertuples()}
    for side in ("winner", "loser"):
        m[f"{side}_pid"] = [pid.get((t, i if _present(i) else f"name:{_folded_key(n)}"))
                             for t, i, n in zip(m["tour"], m[f"{side}_id"], m[f"{side}_name"])]
    m["round_no"] = m["round"].map(ROUND_ORDER)
    return m


def _oddspapi_fixtures(fixtures: pd.DataFrame, crosswalk_odds: pd.DataFrame, year: int) -> pd.DataFrame:
    f = fixtures.copy()
    f["start"] = pd.to_datetime(f["start_time_utc"], utc=True, errors="coerce")
    f = f[(f["start"].dt.year == year) & ~f["tournament_name"].astype(str).str.contains("doubles", case=False)]
    f["tour"] = f["category_name"].map(ODDSPAPI_TOUR)
    f = f[f["tour"].notna()].copy()
    f["edition"] = _editions(crosswalk_odds, f["tournament_id"], f["start"].dt.date, gap_days=4)
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
                if not (_present(wp) and _present(lp)):
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
    fixtures_of = defaultdict(list)   # (edition, participant) -> [(start, fixture_id, opponent, opponent key)]
    for e, fid, start, p1, p2, k1, k2 in zip(f["edition"], f["fixture_id"].astype(str), f["start"], f["p1"], f["p2"], f["k1"], f["k2"]):
        if e is not None:
            fixtures_of[(e, p1)].append((start, fid, p2, k2))
            fixtures_of[(e, p2)].append((start, fid, p1, k1))
    words_of = defaultdict(set)       # player_id -> every word of every TennisMyLife spelling
    for r in alias_tml.itertuples():
        for n in str(r.names).split(" | "):
            words_of[r.player_id] |= set(player_key(n).split())
    results_of = defaultdict(list)    # (edition, player_id) -> [(round_no, opponent player_id)]
    for e, rn, wp, lp in zip(t["edition"], t["round_no"], t["winner_pid"], t["loser_pid"]):
        if pd.notna(rn):
            if _present(wp):
                results_of[(e, wp)].append((rn, lp if _present(lp) else None))
            if _present(lp):
                results_of[(e, lp)].append((rn, wp if _present(wp) else None))
    for (e, p), mine in fixtures_of.items():
        pid = linked.get(p)
        res = results_of.get((e, pid)) if pid else None
        if not res or len(res) != len(mine) or len({r for r, _ in res}) != len(res):
            continue
        for (_, fid, opp, opp_key), (_, opp_pid) in zip(sorted(mine), sorted(res)):
            # Draw order links spellings that differ ("Pyotr"/"Petr" Nesterov) but must share
            # at least one name word, so a walkover or lucky loser cannot shift a link.
            if opp_pid and (fid, opp) not in counted and set(opp_key.split()) & words_of[opp_pid]:
                evidence[opp][opp_pid] += 1; method[opp]["draw order"] += 1
                counted.add((fid, opp))

    # Names, for participants results cannot link.
    names_by_tour = defaultdict(lambda: defaultdict(set))
    for r in alias_tml.itertuples():
        for n in str(r.names).split(" | "):
            names_by_tour[r.tour][player_key(n)].add(r.player_id)
    tokens_by_tour = {tour: [(set(k.split()), pids) for k, pids in idx.items()] for tour, idx in names_by_tour.items()}
    by_word = defaultdict(set)        # (tour, word) -> folded names containing it
    for tour, idx in names_by_tour.items():
        for k in idx:
            for w in k.split():
                if len(w) > 3:
                    by_word[(tour, w)].add(k)

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
            how = " + ".join(sorted(method[pid_odds]))
            if n >= 2:
                row.update(player_id=p, status="confirmed", method=how)
            elif "same match" in method[pid_odds]:
                row.update(player_id=p, status="auto", method=how)
            else:
                # One match lined up by draw order alone, names not compared: too weak
                # (a lucky loser or walkover shifts the order).
                row.update(status="review", method="one match by draw order only", candidates=f"{p} (1)")
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
                elif near := _near_spellings(toks, tour, by_word, names_by_tour):
                    row.update(status="review", method="near spelling", candidates=", ".join(sorted(near)[:6]))
                else:
                    row.update(status="no_history", method="no candidate in our history")
        rows.append(row)
    fresh = pd.DataFrame(rows, columns=ODDS_ALIAS_COLUMNS)
    if existing is not None and not existing.empty:
        prev = existing.drop_duplicates("participant_id").set_index("participant_id")
        same = [p in prev.index and prev.at[p, "player_id"] == pl and prev.at[p, "status"] == st
                for p, pl, st in zip(fresh["participant_id"], fresh["player_id"], fresh["status"])]
        fresh.loc[same, "set_on"] = [prev.at[p, "set_on"] for p in fresh.loc[same, "participant_id"]]

    # Kept rows win; report where the fresh build disagrees.
    drift = pd.DataFrame(columns=["participant_id", "stored", "fresh", "fresh_status"])
    if existing is not None and not existing.empty:
        kept = existing[existing["status"].isin(KEPT_STATUSES)].copy()
        cmp = kept.merge(fresh[["participant_id", "player_id", "status"]], on="participant_id", suffixes=("", "_fresh"))
        # Only a real contradiction: the fresh build would link this participant to another player.
        drift = cmp[(cmp["player_id_fresh"] != "") & (cmp["player_id"] != cmp["player_id_fresh"])].rename(
            columns={"player_id": "stored", "player_id_fresh": "fresh", "status_fresh": "fresh_status"})[
            ["participant_id", "stored", "fresh", "fresh_status"]]
        fresh = pd.concat([kept[ODDS_ALIAS_COLUMNS], fresh[~fresh["participant_id"].isin(kept["participant_id"])]], ignore_index=True)

    review = fresh[fresh["status"] == "review"].assign(kind="oddspapi_participant")
    review = review.rename(columns={"participant_id": "subject", "method": "reason"})[["kind", "tour", "subject", "names", "reason", "candidates"]]
    return fresh.sort_values("participant_id").reset_index(drop=True), review.reset_index(drop=True), drift.reset_index(drop=True)


def _near_spellings(toks: set, tour: str, by_word: dict, names_by_tour: dict) -> set:
    """Players whose name shares one word of 4+ letters and whose other words are near
    spellings of this name's ("Raluca Georgiana Serban" ~ "Raluka Serban")."""
    from difflib import SequenceMatcher
    out = set()
    for w in toks:
        for k in by_word.get((tour, w), ()):
            other = set(k.split()) - {w}
            rest = toks - {w}
            if other and rest and all(any(SequenceMatcher(None, o, r).ratio() >= 0.8 for r in rest) for o in other):
                out |= names_by_tour[tour][k]
    return out


# ---------------------------------------------------------------- decisions
# A person's decisions live in their own files, which only people edit (user decision
# 2026-10-16); the daily rebuild reads them and never writes them.
ODDS_DECISION_COLUMNS = ["participant_id", "player_id", "status", "note", "set_on"]
TML_DECISION_COLUMNS = ["tour", "tml_id", "player_id", "note", "set_on"]


def load_odds_decisions(path) -> pd.DataFrame:
    d = load_table(path, ODDS_DECISION_COLUMNS)
    bad = d[~d["status"].isin({"user", "rejected"}) | ((d["status"] == "user") & (d["player_id"] == ""))]
    if len(bad):
        raise ValueError(f"{path}: rows need status user (with a player_id) or rejected: {list(bad['participant_id'])}")
    if d["participant_id"].duplicated().any():
        raise ValueError(f"{path}: one decision per participant_id")
    return d


def apply_odds_decisions(alias: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    """alias_oddspapi with the decision file laid over it; user/rejected rows come only from
    the decision file."""
    out = alias.copy() if len(alias) else pd.DataFrame(columns=ODDS_ALIAS_COLUMNS)
    gone = out["status"].isin({"user", "rejected"}) & ~out["participant_id"].astype(str).isin(decisions["participant_id"].astype(str))
    out.loc[gone, ["status", "player_id"]] = ["review", ""]
    for d in decisions.itertuples():
        hit = out["participant_id"].astype(str) == str(d.participant_id)
        values = {"player_id": d.player_id if d.status == "user" else "", "status": d.status,
                  "method": "user decision", "note": d.note, "set_on": d.set_on}
        if hit.any():
            for k, v in values.items():
                out.loc[hit, k] = v
        else:
            out = pd.concat([out, pd.DataFrame([{c: "" for c in ODDS_ALIAS_COLUMNS} | values
                                                | {"participant_id": str(d.participant_id)}])], ignore_index=True)
    return out[ODDS_ALIAS_COLUMNS].reset_index(drop=True)


def apply_tml_decisions(alias: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    """alias_tennismylife with the user's joins (rows sharing a player_id are one player)."""
    out = alias.copy() if len(alias) else pd.DataFrame(columns=TML_ALIAS_COLUMNS)
    gone = (out["status"] == "user") & ~(out["tour"] + "|" + out["tml_id"]).isin(decisions["tour"] + "|" + decisions["tml_id"])
    out.loc[gone, "status"] = "auto"   # the join is re-decided by the rebuild's own rules
    for d in decisions.itertuples():
        hit = (out["tour"] == d.tour) & (out["tml_id"] == d.tml_id)
        values = {"player_id": d.player_id, "status": "user", "method": "user decision", "set_on": d.set_on}
        if hit.any():
            for k, v in values.items():
                out.loc[hit, k] = v
        else:
            out = pd.concat([out, pd.DataFrame([{c: "" for c in TML_ALIAS_COLUMNS} | values
                                                | {"tour": d.tour, "tml_id": d.tml_id}])], ignore_index=True)
    return out[TML_ALIAS_COLUMNS].reset_index(drop=True)


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
