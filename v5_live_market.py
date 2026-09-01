from __future__ import annotations

from pathlib import Path
import re
import unicodedata
import pandas as pd

BASE = Path(__file__).resolve().parent
MARKET_FILE = BASE / "v5_market_ready" / "market_board_input.csv"
DEFAULT_MAX_SNAPSHOT_AGE_HOURS = 13


def canonical_name(name):
    s = "" if name is None else str(name).strip()

    # Remove disambiguators commonly appended by odds providers, e.g.
    # "Cretu, Cezar (2001)".
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()

    if "," in s:
        parts = [x.strip() for x in s.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            s = f"{parts[1]} {parts[0]}"

    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _as_utc_timestamp(value=None):
    ts = pd.Timestamp.now(tz="UTC") if value is None else pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def current_market_rows(df, now_utc=None, max_snapshot_age_hours=DEFAULT_MAX_SNAPSHOT_AGE_HOURS):
    """Return only fresh, strictly pre-match market rows.

    A stale market snapshot is rejected completely rather than allowing V5 to price
    a current fixture against yesterday's odds. This is intentionally conservative.
    """
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()

    out = df.copy()
    now = _as_utc_timestamp(now_utc)
    out.attrs["stale_market_feed"] = False

    if "snapshot_utc" not in out.columns:
        out.attrs["stale_market_feed"] = True
        return out.iloc[0:0].copy()

    snapshots = pd.to_datetime(out["snapshot_utc"], errors="coerce", utc=True)
    latest_snapshot = snapshots.max()
    out.attrs["latest_snapshot_utc"] = None if pd.isna(latest_snapshot) else latest_snapshot.isoformat()
    if pd.isna(latest_snapshot):
        out.attrs["stale_market_feed"] = True
        return out.iloc[0:0].copy()

    age_hours = (now - latest_snapshot).total_seconds() / 3600.0
    out.attrs["snapshot_age_hours"] = age_hours
    if age_hours > float(max_snapshot_age_hours):
        empty = out.iloc[0:0].copy()
        empty.attrs.update(out.attrs)
        empty.attrs["stale_market_feed"] = True
        return empty

    if "start_time_utc" not in out.columns:
        return out.iloc[0:0].copy()

    starts = pd.to_datetime(out["start_time_utc"], errors="coerce", utc=True)
    out = out.loc[starts.notna() & (starts > now)].copy()
    out.attrs["stale_market_feed"] = False
    out.attrs["latest_snapshot_utc"] = latest_snapshot.isoformat()
    out.attrs["snapshot_age_hours"] = age_hours
    return out


def load_market_board():
    if not MARKET_FILE.exists():
        return pd.DataFrame()
    df = pd.read_csv(MARKET_FILE, low_memory=False)
    df.attrs["source_path"] = str(MARKET_FILE)
    return current_market_rows(df)


def find_match_rows(df, p1, p2):
    if df.empty:
        return df
    a, b = canonical_name(p1), canonical_name(p2)
    c1 = df["player1"].map(canonical_name)
    c2 = df["player2"].map(canonical_name)
    m = ((c1 == a) & (c2 == b)) | ((c1 == b) & (c2 == a))
    return df[m].copy()


def is_half_line(x):
    try:
        v = float(x)
    except Exception:
        return False
    return abs(v * 2 - round(v * 2)) < 1e-9 and abs(v - round(v)) > 1e-9


def _float_map(result, key):
    return {float(k): float(v) for k, v in (result.get(key) or {}).items()}


def model_market_components(row, result, selected_p1, selected_p2):
    """Return push-aware probabilities for the offered market row.

    `conditional_probability` is P(win | no push), which is the correct quantity
    to compare with two-way no-vig market probabilities. Raw win/push/loss are
    retained separately so expected value can refund pushes correctly.
    """
    group = row.get("market_group")
    sel = canonical_name(row.get("selection"))
    p1 = canonical_name(selected_p1)
    p2 = canonical_name(selected_p2)

    if group == "moneyline":
        if sel == p1:
            win = float(result["pA_win"])
        elif sel == p2:
            win = 1.0 - float(result["pA_win"])
        else:
            return None
        return {
            "conditional_probability": win,
            "win_probability": win,
            "push_probability": 0.0,
            "loss_probability": 1.0 - win,
        }

    try:
        line = float(row.get("line"))
    except Exception:
        return None

    if group == "game_spread":
        spreads = _float_map(result, "spread")
        pushes = _float_map(result, "spread_push")
        if sel == p1:
            win = spreads.get(line)
            if win is None:
                return None
            push = pushes.get(line, 0.0)
        elif sel == p2:
            opposite = -line
            p1_cover = spreads.get(opposite)
            if p1_cover is None:
                return None
            push = pushes.get(opposite, 0.0)
            win = 1.0 - p1_cover - push
        else:
            return None

    elif group == "total_games":
        overs = _float_map(result, "over")
        pushes = _float_map(result, "total_push")
        over_win = overs.get(line)
        if over_win is None:
            return None
        push = pushes.get(line, 0.0)
        raw = str(row.get("selection", "")).strip().lower()
        if raw == "over":
            win = over_win
        elif raw == "under":
            win = 1.0 - over_win - push
        else:
            return None
    else:
        return None

    win = min(1.0, max(0.0, float(win)))
    push = min(1.0, max(0.0, float(push)))
    loss = min(1.0, max(0.0, 1.0 - win - push))
    no_push = win + loss
    if no_push <= 0:
        return None
    return {
        "conditional_probability": win / no_push,
        "win_probability": win,
        "push_probability": push,
        "loss_probability": loss,
    }


def model_probability_for_market(row, result, selected_p1, selected_p2):
    components = model_market_components(row, result, selected_p1, selected_p2)
    return None if components is None else float(components["conditional_probability"])


def fair_american(p):
    p = float(p)
    if p <= 0 or p >= 1:
        return None
    return -100 * p / (1 - p) if p >= 0.5 else 100 * (1 - p) / p


def add_model_pricing(match_rows, result, selected_p1, selected_p2):
    if match_rows.empty:
        return match_rows
    out = match_rows.copy()
    probs = []
    win_probs = []
    push_probs = []
    loss_probs = []
    fair = []
    edges = []
    evs = []
    for _, r in out.iterrows():
        components = model_market_components(r, result, selected_p1, selected_p2)
        if components is None:
            probs.append(None)
            win_probs.append(None)
            push_probs.append(None)
            loss_probs.append(None)
            fair.append(None)
            edges.append(None)
            evs.append(None)
            continue

        p = float(components["conditional_probability"])
        win = float(components["win_probability"])
        push = float(components["push_probability"])
        loss = float(components["loss_probability"])
        probs.append(p)
        win_probs.append(win)
        push_probs.append(push)
        loss_probs.append(loss)
        fair.append(fair_american(p))
        try:
            nv = float(r.get("consensus_no_vig_prob"))
        except Exception:
            nv = None
        try:
            dec = float(r.get("best_decimal_odds"))
        except Exception:
            dec = None
        edges.append(None if nv is None else p - nv)
        # Pushes return the original stake: net EV = P(win)*decimal + P(push) - 1.
        evs.append(None if dec is None else win * dec + push - 1.0)
    out["model_probability"] = probs
    out["model_win_probability"] = win_probs
    out["model_push_probability"] = push_probs
    out["model_loss_probability"] = loss_probs
    out["model_fair_american"] = fair
    out["edge_vs_consensus"] = edges
    out["expected_value"] = evs
    return out


def signal_row(row, disagreement_level=None, state_confidence=None):
    ev = row.get("expected_value")
    edge = row.get("edge_vs_consensus")
    if pd.isna(ev) or pd.isna(edge):
        return "N/A"
    ev = float(ev)
    edge = float(edge)
    if state_confidence is not None and state_confidence < 0.45:
        return "REVIEW"
    if disagreement_level == "HIGH":
        return "REVIEW"
    if disagreement_level == "MODERATE" and ev >= 0.05:
        return "REVIEW"
    if ev >= 0.05 and edge >= 0.025:
        return "BET"
    if ev >= 0.02 and edge >= 0.01:
        return "LEAN"
    return "PASS"


# ============================================================
# ALL-BOOK PRICE FEED
# ============================================================

ALL_PRICE_CANDIDATES = [
    BASE / "v5_market_ready" / "all_book_prices.csv",
    BASE / "all_book_prices.csv",
]


def load_all_book_prices():
    for p in ALL_PRICE_CANDIDATES:
        if p.exists():
            df = pd.read_csv(p, low_memory=False)
            df.attrs["source_path"] = str(p)
            out = current_market_rows(df)
            out.attrs["source_path"] = str(p)
            return out
    return pd.DataFrame()


def find_all_match_prices(df, p1, p2):
    if df.empty:
        return df
    a, b = canonical_name(p1), canonical_name(p2)
    if "player1" not in df.columns or "player2" not in df.columns:
        return pd.DataFrame()
    c1 = df["player1"].map(canonical_name)
    c2 = df["player2"].map(canonical_name)
    mask = ((c1 == a) & (c2 == b)) | ((c1 == b) & (c2 == a))
    return df[mask].copy()
