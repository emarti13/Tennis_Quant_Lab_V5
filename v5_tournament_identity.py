"""Tournament identity: the master schedule and its reconciliation with each source.

Design: docs/superpowers/specs/2026-10-12-tournament-identity-design.md (draft).

The master schedule (built by the user from the official ATP, WTA and ATP Challenger
calendars) decides which editions exist. TennisMyLife and OddsPapi never create an
edition; their tournaments are matched to editions on tour family, dates and location,
and every match is reported with how it was made. Nothing is guessed: a source
tournament with no single candidate is reported as unmatched or ambiguous.

This module is read-only with respect to production: it loads and checks the sheet and
produces reconciliation tables. It does not change pricing yet.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

SHEET_DATE_FORMAT = "%m/%d/%Y"

SURFACE_CODES = {
    "H": ("Hard", "Outdoor"),
    "IH": ("Hard", "Indoor"),
    "C": ("Clay", "Outdoor"),
    "IC": ("Clay", "Indoor"),
    "G": ("Grass", "Outdoor"),
}

# Tokens that recur in provider tournament names but carry no identity.
_NAME_NOISE = {
    "atp", "wta", "125k", "challenger", "men", "women", "singles", "doubles", "open",
    "the", "de", "di", "la", "le", "of", "tennis", "international", "championships",
    "cup", "qualification", "qualifying", "presented", "by",
}


# ---------------------------------------------------------------- text helpers
def fix_mojibake(text: str) -> str:
    """Repair UTF-8 text that was decoded as Windows-1252 (Excel non-UTF-8 export)."""
    if not isinstance(text, str) or not re.search(r"[ÃÂâ]", text):
        return text
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return repaired


def fold(text) -> str:
    """Lowercase ASCII with accents removed and punctuation collapsed to spaces."""
    t = unicodedata.normalize("NFKD", fix_mojibake(str(text or ""))).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", t.lower()))


def name_tokens(text) -> set[str]:
    return {t for t in fold(text).split() if t not in _NAME_NOISE and not t.isdigit() and len(t) >= 3}


_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}


def trailing_number(text) -> int | None:
    """'Oeiras 2' -> 2, 'ATP Challenger Istanbul 3, Turkiye ...' -> 3, 'Shymkent II' -> 2."""
    tokens = [t for t in fold(text).replace("125k", "").split()]
    for t in reversed(tokens):
        if t.isdigit() and len(t) == 1:
            return int(t)
        if t in _ROMAN and t != "i":  # a lone 'i' is too often a word fragment
            return _ROMAN[t]
    return None


def player_key(name) -> str:
    """Order-independent player key: 'Ito, Aoi' and 'Aoi Ito' -> 'aoi ito'."""
    return " ".join(sorted(fold(str(name).replace(",", " ")).split()))


# ---------------------------------------------------------------- master schedule
def tour_family(circuit: str, end_date_present: bool, gender: str = "") -> tuple[str, str | None]:
    """Family used as a hard filter in matching. Returns (family, issue or None).

    The sheet's Circuit Type column (Men/Women) decides men's vs women's events. Without
    it, Grand Slam rows fall back to an end-date heuristic and are flagged.
    """
    c = fold(circuit)
    g = fold(gender)
    if g in {"men", "women"}:
        if "challenger" in c:
            return ("CHALLENGER", None) if g == "men" else ("UNKNOWN", f"Women's row with Circuit Tour '{circuit}'")
        if "125" in c and g == "women":
            return "WTA125", None
        if c.startswith("wta") and g == "men":
            return "UNKNOWN", f"Men's row with Circuit Tour '{circuit}'"
        return ("ATP" if g == "men" else "WTA"), None
    if "challenger" in c:
        return "CHALLENGER", None
    if "wta 125" in c:
        return "WTA125", None
    if c.startswith("wta"):
        return "WTA", None
    if c.startswith("atp") or c.startswith("nitto") or c in {"davis cup", "laver cup"}:
        return "ATP", None
    if c == "united cup":
        return "ATP", None
    if c == "grand slam":
        # The sheet has no men/women column. Men's rows carry an end date, women's do not.
        return ("ATP" if end_date_present else "WTA"), "Grand Slam row: tour inferred from End Date; add a Tour (Men/Women) column"
    return "UNKNOWN", f"Unrecognized Circuit Tour '{circuit}'"


def _parse_date(value) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    return pd.to_datetime(text, format=SHEET_DATE_FORMAT).date()


_NOTE_FLAGS = {
    "cancelled": r"\bcancell?ed\b",
    "added": r"\badded\b",
    "high_altitude": r"high altitude",
    "har_tru": r"har-tru",
}
_DAY_NOTES = r"\b(?:sunday|monday|tuesday|wednesday|thursday|friday|saturday) (?:start|final)\b"
# Fragments of the official calendar's other columns pasted into the notes cell.
_FOREIGN_NOTE = re.compile(r"\b(?:M1000|GSL|250|500|DC|LC|UTD|ATP)\b|✽|Qualifying\s+GSL")


@dataclass
class SheetIssue:
    row: int
    field: str
    severity: str  # "error" blocks use of the row; "warn" needs review; "info" is fillable
    message: str


def load_master_schedule(path: str | Path) -> tuple[pd.DataFrame, list[SheetIssue]]:
    """Load the user's sheet (TSV or CSV), normalize it, and list every problem found."""
    path = Path(path)
    sep = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    # utf-8-sig accepts Excel's "CSV UTF-8" byte-order mark as well as plain UTF-8.
    raw = pd.read_csv(path, sep=sep, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    issues: list[SheetIssue] = []
    rows = []
    for i, r in raw.iterrows():
        line = i + 2  # 1-based, after the header
        name = fix_mojibake(r.get("Tournament Name", "")).strip()
        city = fix_mojibake(r.get("City", "")).strip()
        notes = fix_mojibake(r.get("Scheduling / Notes", "")).strip()
        if name != r.get("Tournament Name", "").strip() or city != r.get("City", "").strip():
            issues.append(SheetIssue(line, "Tournament Name", "info", "Garbled accents repaired (save the sheet as CSV UTF-8)"))
        try:
            start = _parse_date(r.get("Start Date"))
            end = _parse_date(r.get("End Date"))
        except ValueError as exc:
            issues.append(SheetIssue(line, "Start Date", "error", f"Unparseable date: {exc}"))
            continue
        if start is None:
            issues.append(SheetIssue(line, "Start Date", "error", "Missing start date"))
            continue
        family, fam_issue = tour_family(r.get("Circuit Tour", ""), end is not None, r.get("Circuit Type", ""))
        if fam_issue:
            issues.append(SheetIssue(line, "Circuit Tour", "warn" if family != "UNKNOWN" else "error", fam_issue))
        end_derived = False
        if end is None:
            long_event = fold(r.get("Circuit Tour")) in {"wta 1000", "grand slam"}
            end = start + timedelta(days=13 if long_event else 6)
            end_derived = True
            issues.append(SheetIssue(line, "End Date", "info", f"End Date missing; assumed {end.isoformat()} for matching"))
        if end < start:
            issues.append(SheetIssue(line, "End Date", "error", "End Date before Start Date"))
        code = r.get("Surface Code", "").strip().upper()
        surface, setting = r.get("Surface", "").strip(), r.get("Setting", "").strip()
        if code in SURFACE_CODES and SURFACE_CODES[code] != (surface, setting):
            issues.append(SheetIssue(line, "Surface Code", "error", f"Code {code} disagrees with {surface}/{setting}"))
        if not surface:
            issues.append(SheetIssue(line, "Surface", "error", "Missing surface"))
        if not r.get("Country", "").strip():
            issues.append(SheetIssue(line, "Country", "info", "Country name empty" + (" (code given)" if r.get("Country Code", "").strip() else "")))
        if not r.get("Time Zone", "").strip():
            issues.append(SheetIssue(line, "Time Zone", "info", "Time zone empty"))
        flags = {k: bool(re.search(p, notes, flags=re.I)) for k, p in _NOTE_FLAGS.items()}
        day_notes = sorted(set(m.group(0).lower() for m in re.finditer(_DAY_NOTES, notes, flags=re.I)))
        if _FOREIGN_NOTE.search(notes):
            issues.append(SheetIssue(line, "Scheduling / Notes", "warn", "Notes contain text from another calendar column; review"))
        rows.append({
            "sheet_row": line,
            "edition_key": f"{family}|{start.isoformat()}|{fold(name).replace(' ', '-')}|{fold(city).replace(' ', '-')}",
            "tour_family": family,
            "circuit_type": r.get("Circuit Type", "").strip(),
            "circuit_tour": r.get("Circuit Tour", "").strip(),
            "tournament_name": name,
            "city": city,
            "state": r.get("State", "").strip(),
            "country": r.get("Country", "").strip(),
            "country_code": r.get("Country Code", "").strip(),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "end_date_assumed": end_derived,
            "category": r.get("Category", "").strip(),
            "surface": surface,
            "setting": setting,
            "status": "cancelled" if flags["cancelled"] else ("added" if flags["added"] else "scheduled"),
            "high_altitude": flags["high_altitude"],
            "har_tru": flags["har_tru"],
            "day_notes": "; ".join(day_notes),
            "notes_raw": notes,
            # Location values typed into the sheet always win over looked-up ones.
            "sheet_latitude": r.get("Latitude", "").strip(),
            "sheet_longitude": r.get("Longitude", "").strip(),
            "sheet_altitude_m": r.get("Altitude (m)", "").strip(),
            "sheet_time_zone": r.get("Time Zone", "").strip(),
        })
    out = pd.DataFrame(rows)
    dup = out[out.duplicated("edition_key", keep=False)]
    for _, d in dup.iterrows():
        issues.append(SheetIssue(int(d.sheet_row), "Tournament Name", "error", f"Duplicate edition {d.edition_key}"))
    # Same men's/women's event listed twice under different tours or dates (e.g. a team
    # event entered once as a team event and once as a tour event).
    out["dup_name"] = out["tournament_name"].map(fold)
    out["dup_city"] = out["city"].map(fold)
    out["dup_gender"] = out["circuit_type"].map(fold) if "circuit_type" in out else ""
    out["dup_start"] = pd.to_datetime(out["start_date"])
    for _, g in out.groupby(["dup_gender", "dup_name", "dup_city"]):
        if len(g) < 2:
            continue
        g = g.sort_values("dup_start")
        for a, b in zip(g.itertuples(), list(g.itertuples())[1:]):
            gap = (b.dup_start - a.dup_start).days
            # Weekly events with one name (e.g. three Antalya weeks) are legitimate: flag only the
            # same event under two tours, or two starts so close they cannot be separate weeks.
            if gap <= 7 and (a.circuit_tour != b.circuit_tour or gap <= 3):
                for row, other in ((a, b), (b, a)):
                    issues.append(SheetIssue(int(row.sheet_row), "Tournament Name", "warn",
                                             f"Possible duplicate entry: same event, city and Men/Women within a week; other row {other.sheet_row}"))
    out = out.drop(columns=["dup_name", "dup_city", "dup_gender", "dup_start"])
    return out, issues


# ---------------------------------------------------------------- source tournaments
def oddspapi_tournaments(fixtures: pd.DataFrame, year: int, gap_days: int = 4) -> pd.DataFrame:
    """One row per (OddsPapi tournament_id, date block). A block is a run of fixture
    dates with no gap longer than gap_days, so an id reused for two weeks gives two rows."""
    f = fixtures.copy()
    f["start"] = pd.to_datetime(f["start_time_utc"], utc=True, errors="coerce")
    f = f[f["start"].dt.year == year]
    f = f[~f["tournament_name"].astype(str).str.contains("doubles", case=False)]
    family = {"Challenger": "CHALLENGER", "ATP": "ATP", "WTA": "WTA", "WTA 125K": "WTA125"}
    f["family"] = f["category_name"].map(family)
    out = []
    for (tid, tname, fam), g in f.dropna(subset=["family"]).groupby(["tournament_id", "tournament_name", "family"]):
        days = sorted(g["start"].dt.date.unique())
        blocks, cur = [], [days[0]]
        for d in days[1:]:
            if (d - cur[-1]).days > gap_days:
                blocks.append(cur)
                cur = []
            cur.append(d)
        blocks.append(cur)
        for b in blocks:
            sub = g[g["start"].dt.date.between(b[0], b[-1])]
            players = set(sub["participant1_name"].map(player_key)) | set(sub["participant2_name"].map(player_key))
            out.append({
                "source": "oddspapi", "source_id": f"{int(tid)}@{b[0].isoformat()}",
                "tournament_id": int(tid), "name": tname, "family": fam,
                "first_date": b[0].isoformat(), "last_date": b[-1].isoformat(),
                "fixtures": len(sub), "players": players, "surface": "",
            })
    return pd.DataFrame(out)


def tennismylife_tournaments(results: pd.DataFrame, year: int) -> pd.DataFrame:
    """One row per TennisMyLife tourney_id. Davis Cup ties (level D) are excluded."""
    r = results.copy()
    r["date"] = pd.to_datetime(r["tourney_date"].astype(str).str[:8], format="%Y%m%d", errors="coerce")
    r = r[r["date"].dt.year == year]
    file_family = {
        f"{year}.csv": "ATP", f"{year}_atp_quali.csv": "ATP", "ongoing_tourneys.csv": "ATP",
        f"{year}_challenger.csv": "CHALLENGER", "challenger_ongoing_tourneys.csv": "CHALLENGER",
        f"{year}_wta.csv": "WTA", "wta_ongoing_tourneys.csv": "WTA",
    }
    r["family"] = r["result_file"].map(file_family)
    r = r[r["tourney_level"].astype(str) != "D"]
    out = []
    for (tid, fam), g in r.dropna(subset=["family"]).groupby(["tourney_id", "family"]):
        players = set(g["winner_name"].map(player_key)) | set(g["loser_name"].map(player_key))
        out.append({
            "source": "tennismylife", "source_id": str(tid), "tournament_id": str(tid),
            "name": str(g["tourney_name"].iloc[0]), "family": fam,
            "first_date": g["date"].min().date().isoformat(), "last_date": g["date"].max().date().isoformat(),
            "fixtures": len(g), "players": players,
            "surface": str(g["surface"].dropna().iloc[0]) if g["surface"].notna().any() else "",
            "level": str(g["tourney_level"].iloc[0]),
        })
    return pd.DataFrame(out)


# ---------------------------------------------------------------- matching
def _location_score(source_name: str, edition: pd.Series) -> float:
    """1.0 if the edition's city (or a distinctive name token) appears in the source name."""
    src = fold(source_name)
    city = fold(edition["city"])
    if city and re.search(rf"\b{re.escape(city)}\b", src):
        return 1.0
    full = fold(edition["tournament_name"])
    if full and re.search(rf"\b{re.escape(full)}\b", src):
        return 1.0
    src_tokens = name_tokens(source_name)
    ed_tokens = name_tokens(edition["tournament_name"]) | set(city.split())
    return 0.5 if src_tokens & ed_tokens else 0.0


def match_source(sources: pd.DataFrame, editions: pd.DataFrame, *, before_days: int = 3, slam_before_days: int = 8) -> pd.DataFrame:
    """Match each source tournament to at most one edition.

    Hard filters: same tour family, and the source must *start* inside the edition:
    edition start - before_days <= source first date <= edition end. Qualifying can
    begin a few days early (a full week for Grand Slams). Anchoring on the first date
    keeps back-to-back events in one city apart ('Tenerife 1' / 'Tenerife 2').
    Then location, then the trailing event number. The result is 'matched' only when
    exactly one candidate remains. TennisMyLife's first date is its tournament week
    start; OddsPapi's is the first fixture date.
    """
    eds = editions[editions["status"] != "cancelled"].copy()
    eds["_start"] = pd.to_datetime(eds["start_date"])
    eds["_end"] = pd.to_datetime(eds["end_date"])
    lead = eds["circuit_tour"].map(lambda c: slam_before_days if fold(c) == "grand slam" else before_days)
    eds["_window_start"] = eds["_start"] - pd.to_timedelta(lead, unit="D")
    out = []
    for _, s in sources.iterrows():
        first = pd.Timestamp(s["first_date"])
        cand = eds[(eds["tour_family"] == s["family"])
                   & (eds["_window_start"] <= first) & (first <= eds["_end"])].copy()
        cand["loc"] = [_location_score(s["name"], e) for _, e in cand.iterrows()]
        located = cand[cand["loc"] > 0]
        if len(located) > 1:
            best = located[located["loc"] == located["loc"].max()]
            num = trailing_number(s["name"])
            if len(best) > 1 and num is not None:
                numbered = best[[trailing_number(n) == num for n in best["tournament_name"]]]
                if len(numbered) == 1:
                    best = numbered
            located = best
        if len(located) > 1:
            # Several editions in one place still fit (e.g. weekly events whose end dates
            # are assumed). Take the one whose start is clearly closest to the source's
            # first date; otherwise leave it ambiguous.
            gap = (located["_start"] - first).abs().dt.days.sort_values()
            if gap.iloc[1] - gap.iloc[0] >= 5:
                located = located.loc[[gap.index[0]]]
        if len(located) == 1:
            e = located.iloc[0]
            status, method = "matched", "family+dates+" + ("city" if e["loc"] == 1.0 else "name")
        elif len(located) > 1:
            status, method, e = "ambiguous", "", None
        else:
            status, method, e = "unmatched", "", None
        out.append({
            "source": s["source"], "source_id": s["source_id"], "source_name": s["name"],
            "family": s["family"], "first_date": s["first_date"], "last_date": s["last_date"],
            "fixtures": s["fixtures"], "source_surface": s.get("surface", ""),
            "status": status, "method": method,
            "edition_key": "" if e is None else e["edition_key"],
            "sheet_row": "" if e is None else int(e["sheet_row"]),
            "sheet_name": "" if e is None else e["tournament_name"],
            "sheet_surface": "" if e is None else e["surface"],
            "candidates": "" if status == "matched" else " | ".join(
                f"{c.tournament_name} ({c.city}, {c.start_date})" for c in (located if len(located) else cand).itertuples()),
        })
    return pd.DataFrame(out)


def _same_player(a: str, b: str) -> bool:
    """Tolerant name match: one name's tokens contain the other's ('diego dedura' vs
    'diego dedura palomero'), or they share at least two tokens."""
    ta, tb = set(a.split()), set(b.split())
    return ta <= tb or tb <= ta or len(ta & tb) >= 2


def player_agreement(odds: pd.DataFrame, tml: pd.DataFrame, odds_matches: pd.DataFrame, tml_matches: pd.DataFrame) -> pd.DataFrame:
    """For editions matched by both sources: the share of TennisMyLife players (main
    draw, plus ATP qualifying) that also appear in the OddsPapi fixtures mapped to the
    same edition. OddsPapi also lists qualifying, so its larger set is the reference.
    High agreement confirms both mappings; low agreement flags one of them."""
    o = odds_matches[odds_matches.status == "matched"].merge(odds[["source_id", "players"]], on="source_id")
    t = tml_matches[tml_matches.status == "matched"].merge(tml[["source_id", "players"]], on="source_id")
    rows = []
    for key, og in o.groupby("edition_key"):
        tg = t[t["edition_key"] == key]
        if tg.empty:
            continue
        op = set().union(*og["players"])
        tp = set().union(*tg["players"])
        found = sum(1 for p in tp if p in op or any(_same_player(p, q) for q in op))
        rows.append({
            "edition_key": key, "sheet_row": og["sheet_row"].iloc[0], "sheet_name": og["sheet_name"].iloc[0],
            "oddspapi_ids": ", ".join(og["source_id"]), "tennismylife_ids": ", ".join(tg["source_id"]),
            "oddspapi_players": len(op), "tennismylife_players": len(tp),
            "share_found": round(found / len(tp), 3) if tp else None,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- locations
def load_countries(path: str | Path = "context_registry/countries.csv") -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def country_iso2(row: pd.Series, countries: pd.DataFrame) -> str:
    """ISO 3166 alpha-2 from the sheet's Country Code (IOC style, e.g. GER) or Country name."""
    code = str(row.get("country_code") or "").strip().upper()
    if code:
        hit = countries[countries["ioc"] == code]
        if len(hit):
            return hit["iso2"].iloc[0]
    name = fold(row.get("country"))
    hit = countries[countries["name"].map(fold) == name]
    return hit["iso2"].iloc[0] if len(hit) else ""


def location_key(city: str, state: str, iso2: str) -> str:
    return f"{fold(city)}|{fold(state)}|{iso2}"


def pick_location(candidates: list[dict], iso2: str, state: str, query: str = "", region: str = "",
                  match_name: str = "", same_place_km: float = 50.0) -> tuple[dict | None, str, str]:
    """Choose a geocoder result without guessing. Returns (result, status, note).

    Rules, in order: the result must be in the sheet's country; its name must equal the
    looked-up name, or the match_name given in location_aliases.csv (no airports or
    neighbouring towns); the sheet's State, or a region pinned in location_aliases.csv,
    must match its first-level region when given; several same-named results all within
    same_place_km of each other are one place (e.g. Hong Kong); otherwise the clearly
    largest wins (population at least twice the next), and anything else is ambiguous.
    status: 'matched' | 'state_mismatch' | 'ambiguous' | 'unresolved'.
    """
    in_country = [c for c in candidates if str(c.get("country_code", "")).upper() == iso2]
    if not in_country:
        return None, "unresolved", f"no result in country {iso2 or '?'}"
    # Only real places: populated places (PPL*), administrative areas (ADM*) and islands.
    # Airports, parks, dams and other features are never used as a city's location.
    in_country = [c for c in in_country if str(c.get("feature_code") or "PPL").startswith(("PPL", "ADM", "ISL"))]
    want = match_name or query
    if want:
        w = fold(want)
        # Same name, or the official name extends it as whole words ("Acapulco de Juarez",
        # "San Luis Potosi City"). An explicit match_name must match exactly.
        exact = [c for c in in_country if fold(c.get("name")) == w]
        if not match_name:
            # Towns (not islands or regions) whose official name extends the city's name.
            exact += [c for c in in_country if fold(c.get("name")).startswith(w + " ")
                      and str(c.get("feature_code") or "PPL").startswith("PPL")]
        if not exact:
            names = ", ".join(sorted({str(c.get("name")) for c in in_country})[:5])
            return None, "unresolved", f"no place named '{want}' in {iso2}; geocoder has: {names}"
        in_country = exact
    pin = region or state
    if pin:
        same = [c for c in in_country if fold(c.get("admin1")) == fold(pin)]
        if not same:
            found = sorted({str(c.get("admin1")) for c in in_country if c.get("admin1")})
            shown = ", ".join(found[:6]) + (f" and {len(found) - 6} more" if len(found) > 6 else "")
            # Fail closed: with the state/region wrong we cannot tell which same-named place is meant.
            return None, "state_mismatch", f"'{pin}' not found; geocoder has: {shown}"
        in_country = same
    if len(in_country) == 1:
        return in_country[0], "matched", ""
    spread = max(_haversine_km(a["latitude"], a["longitude"], b["latitude"], b["longitude"])
                 for a in in_country for b in in_country)
    if spread <= same_place_km:
        return max(in_country, key=lambda c: c.get("population") or 0), "matched", ""
    ranked = sorted(in_country, key=lambda c: c.get("population") or 0, reverse=True)
    top, nxt = ranked[0].get("population") or 0, ranked[1].get("population") or 0
    if top > 0 and top >= 2 * nxt:
        return ranked[0], "matched", ""
    regions = ", ".join(sorted({str(c.get("admin1")) for c in in_country})[:6])
    return None, "ambiguous", f"{len(in_country)} places named '{query or in_country[0].get('name')}' ({regions}); set the region in location_aliases.csv or type coordinates"


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def enrich_locations(editions: pd.DataFrame, cache: pd.DataFrame, countries: pd.DataFrame,
                     max_disagreement_km: float = 25.0, aliases: pd.DataFrame | None = None) -> tuple[pd.DataFrame, list[SheetIssue]]:
    """Add latitude, longitude, altitude_m, time_zone (IANA) and country fields.

    Sheet values win; otherwise the cached geocoder result is used. Every row gets a
    location_source ('sheet', 'geocoded' or 'missing') and a location_status. Nothing is
    guessed: an unresolved location stays empty and is reported.
    """
    import json
    by_key = {r["location_key"]: json.loads(r["results_json"] or "[]") for _, r in cache.iterrows()}
    query_of = {r["location_key"]: r.get("query", "") for _, r in cache.iterrows()}
    alias_rows = aliases if aliases is not None else pd.DataFrame(columns=["city", "country_iso2", "region", "match_name"])
    region_of = {(r["city"], r["country_iso2"]): r.get("region", "") for _, r in alias_rows.iterrows()}
    match_of = {(r["city"], r["country_iso2"]): r.get("match_name", "") for _, r in alias_rows.iterrows()}
    out = editions.copy()
    issues: list[SheetIssue] = []
    cols = {k: [] for k in ("country_iso2", "country_name", "latitude", "longitude", "altitude_m",
                            "time_zone", "region", "location_source", "location_status")}
    for _, e in out.iterrows():
        iso2 = country_iso2(e, countries)
        name = countries.loc[countries["iso2"] == iso2, "name"].iloc[0] if iso2 else ""
        key = location_key(e["city"], e["state"], iso2)
        pick, status, note = pick_location(by_key.get(key, []), iso2, e["state"], query=query_of.get(key, "") or e["city"],
                                           region=region_of.get((e["city"], iso2), ""),
                                           match_name=match_of.get((e["city"], iso2), ""))
        sheet_vals = {k: str(e.get(f"sheet_{k}", "")).strip() for k in ("latitude", "longitude", "altitude_m", "time_zone")}
        lat = float(sheet_vals["latitude"]) if sheet_vals["latitude"] else (pick or {}).get("latitude")
        lon = float(sheet_vals["longitude"]) if sheet_vals["longitude"] else (pick or {}).get("longitude")
        alt = float(sheet_vals["altitude_m"]) if sheet_vals["altitude_m"] else (pick or {}).get("elevation")
        tz = sheet_vals["time_zone"] or (pick or {}).get("timezone") or ""
        source = "sheet" if sheet_vals["latitude"] and sheet_vals["longitude"] else ("geocoded" if pick else "missing")
        if status == "state_mismatch" and source != "sheet":
            issues.append(SheetIssue(int(e["sheet_row"]), "State", "warn", f"{e['city']}: check State/region ({note}); location left empty until fixed"))
        elif status == "ambiguous" and source != "sheet":
            issues.append(SheetIssue(int(e["sheet_row"]), "City", "warn", f"{e['city']}: {note}"))
        elif pick is None and source != "sheet":
            issues.append(SheetIssue(int(e["sheet_row"]), "City", "warn", f"{e['city']}: location not found ({note}); correct City or type Latitude/Longitude/Time Zone in the sheet"))
        if source == "sheet" and pick is not None:
            d = _haversine_km(lat, lon, pick["latitude"], pick["longitude"])
            if d > max_disagreement_km:
                issues.append(SheetIssue(int(e["sheet_row"]), "Latitude", "warn", f"Sheet location is {d:.0f} km from the geocoded city; check"))
        for k, v in (("country_iso2", iso2), ("country_name", e["country"] or name), ("latitude", lat), ("longitude", lon),
                     ("altitude_m", alt), ("time_zone", tz), ("region", (pick or {}).get("admin1", "")),
                     ("location_source", source), ("location_status", "sheet" if source == "sheet" else status)):
            cols[k].append(v)
    for k, v in cols.items():
        out[k] = v
    return out, issues
