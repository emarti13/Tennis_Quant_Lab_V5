from __future__ import annotations

from collections import defaultdict

from normalize_oddspapi_snapshot import market_group, outcome_lookup, normalize_selection, normalized_line


def map_snapshot_rows(snapshot_rows, fixture: dict, market_metadata: list[dict]) -> list[dict]:
    meta_by_id = {str(m.get("marketId")): m for m in market_metadata}
    p1 = fixture.get("participant1Name")
    p2 = fixture.get("participant2Name")
    out: list[dict] = []

    for row in snapshot_rows:
        meta = meta_by_id.get(str(row.get("market_id")))
        if not meta:
            continue
        group = market_group(meta)
        if group not in {"moneyline", "game_spread", "total_games"}:
            continue
        outcomes = outcome_lookup(meta)
        selection = normalize_selection(
            group,
            outcomes.get(str(row.get("outcome_id")), ""),
            row.get("outcome_id"),
            p1,
            p2,
        )
        line = normalized_line(group, meta, selection, p1, p2)
        dec = float(row["price_decimal"])
        mapped = dict(row)
        mapped.update({
            "start_time_utc": fixture.get("startTime"),
            "tournament": fixture.get("tournamentName"),
            "tour": fixture.get("categoryName"),
            "player1": p1,
            "player2": p2,
            "market_group": group,
            "market_name": meta.get("marketName"),
            "period": meta.get("period"),
            "selection": selection,
            "line": line,
            "raw_implied_prob": (1.0 / dec if dec > 1 else None),
            "no_vig_prob": None,
            "market_hold": None,
        })
        out.append(mapped)

    buckets = defaultdict(list)
    for idx, row in enumerate(out):
        key = (
            row.get("fixture_id"),
            row.get("snapshot_label"),
            row.get("bookmaker"),
            row.get("market_id"),
        )
        buckets[key].append(idx)

    for ids in buckets.values():
        probs = [out[i]["raw_implied_prob"] for i in ids if out[i]["raw_implied_prob"]]
        total = sum(probs)
        if len(probs) < 2 or total <= 0:
            continue
        for i in ids:
            p = out[i]["raw_implied_prob"]
            if p:
                out[i]["no_vig_prob"] = p / total
                out[i]["market_hold"] = total - 1.0

    return out
