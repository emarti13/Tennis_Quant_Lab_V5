# Step 3 market source probe (2026-10-16)

User-approved small probe before building the market data layer
(`docs/superpowers/specs/2026-10-16-market-data-layer-design.md`). Three runs of
`scripts/probe_step3_market_sources.py` on branch `research/step3-probe` (never merged; raw
results in `research/step3_probe/result.json` on that branch's history). In total: 21
OddsPapi `/historical-odds` calls, 9 `/account` calls, and about 20 Kalshi calls.
Read-only.

## OddsPapi

| Question | Finding |
|---|---|
| Does `/historical-odds` count against the quota? | **No.** `request_count` was 70 before and after all three runs (21 historical calls, 9 `/account` calls). `/account` is free too. |
| Real quota | `request_limit` 250, used 70; subscription valid from 2026-08-26, **no end date given**, so whether it resets monthly is not shown. |
| Rate limit | About one call every 5 s per endpoint (HTTP 429 with `retryMs` otherwise). Each response takes under 1.1 s. |
| Books per call | **At most 3.** Polymarket only alone and with one `outcomeId`. Novig's name is `novig.us`. 488 book names are valid. |
| Execution books with history | **Bet365, FanDuel and BetMGM return full histories** (8,935 / 16,606 / 27,963 quotes on one ATP match). Kalshi via OddsPapi was not tested (rejected together with Polymarket). |
| How far back | 7, 21, 35, 45, 60, 90 and 120 days: yes. **180 and 270 days: "No historical odds found"** (including fixtures our stored backfill holds). History disappears after roughly 4–6 months. OddsPapi's docs say everything since January 2026 is available, but the stored backfill holds 2,026 Pinnacle quotes for the 2026-01-19 fixture `id1203388067924576` that now returns "not found". |
| Closing price quality (6 recent fixtures) | Pinnacle's last pre-start quote is 0.5–8 min before the start on tour events, 46 min on one Challenger. DraftKings 0.2–5 min. **BetRivers is often stale**: 2–27 min on tour events, but 595 and 676 min (10–11 h) on a WTA 125 and a Challenger. |
| Opening line | First quote 17–44 h before the start (Pinnacle 17–41 h). |
| Matches not yet started | **The endpoint answers before the start**, with every quote up to the latest change (Pinnacle's newest change was 18 min old when asked, 82 min before the start). That gives a free pre-match price source. |

## Kalshi (public API, no account)

- `/series?category=Sports` lists 4,000 series; 150 are tennis.
- Match-winner series in scope: `KXATPMATCH`, `KXWTAMATCH`, `KXATPCHALLENGERMATCH`,
  `KXWTACHALLENGERMATCH`. ITF series exist and are out of scope.
- A settled Challenger market (Gaston, 2026-10-16) has more than 1,000 trades (paged with a
  cursor), and 13 hourly candles over the market's life.
- Market rows carry bid, ask, sizes, open/close times and the result.

## What this changes

Proposed changes to the design are in the spec's §5 (pending the user's answers). Facts
that change nothing: past odds are free; the Kalshi API answers; the 5-second pace is
already assumed in §2.2.
