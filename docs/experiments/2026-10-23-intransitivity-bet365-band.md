# Results: intransitivity segment and Bet365 underdog band

Run 2026-10-23 exactly as pre-registered in `2026-10-23-prereg-intransitivity-bet365-band.md`.
Roadmap gate: Phase 1. No sealed-period data. Code and numbers (on the research branch
`claude/clever-fermi-hv34lk`):
- `research_tests/kaggle_odds/run_bet365_band.py`, `results_bet365_band.json`;
- `research_tests/intransitivity/run_intrans.py`, `results.json`.

## Test 2: Bet365 underdog band — FAILED (no rule)
Backing the underdog at Bet365's close loses in every band and both periods.

| Underdog price | 2014-19 (discovery) | 2020-25 (reference) |
|---|---|---|
| 1.8-2.2 | −6.3% (−8.4, −4.1), n 7,944 | −6.0% (−8.3, −3.9) |
| 2.2-2.6 | −6.7% | −5.1% |
| 2.6-3.2 | −9.8% | −7.1% |
| 3.2-4.0 | −7.0% | −3.5% (−7.1, +0.4) |
| 4.0-6.0 | −21.2% | −15.8% |
| 2.2-4.0 pooled | −7.9% | −5.4% |

No band's discovery range was above zero, so the pre-registered rule is "no rule".
**Reading:**
- Bet365 has no blanket underdog mispricing; its margin (about 6.7%) dominates.
- The +2.4 to +4.3% Bet365 returns in `2026-10-21-kaggle-odds-edge-search.md` came from the
  model's selection of bets, not from a market-wide Bet365 bias.
- Ciobanu (2023)'s "upsets at Bet365" is not supported as a market-only effect.

## Test 1: intransitivity — FAILED on its pre-registered criterion
I* was built leak-free from completed events only: dominance from the share of games won,
the paper's surface-transfer and tier weights, decay λ = 0.38 per year, and the Hodge split
on the common-opponent subgraph.
- **Coverage:** 72,555 matches. 63% have I* = 0 (no prior direct meeting); the paper has 58%.
- **Bins:** tertile cut points on 2017-21 I* > 0 are 0.51 and 0.95. Our I* scale is smaller
  than the paper's (decay and lower-tier weights), so the paper's γ = 2.55 is rarely reached.

Ensemble log-loss gain over the consensus close, by bin (positive = ensemble better):

| Bin | 2017-21 | 2022-25 |
|---|---|---|
| 0 (no meeting) | +0.0011 (0.0002, 0.0019) | +0.0014 (0.0007, 0.0022) |
| 1 (low I*) | +0.0016 | +0.0024 |
| 2 | +0.0005 | +0.0005 |
| 3 (high I*) | +0.0026 (0.0010, 0.0043) | +0.0014 (−0.0004, 0.0030) |

- **Decision test (2022-25, top bin minus bin 0):** −0.00005 (−0.0018, +0.0018). Not above zero.
- **By tour, top bin, 2022-25:** WTA −0.0001 (ns; the paper's more-intransitive tour shows
  nothing), ATP +0.0027 (0.0003, 0.0051), Challenger +0.0007 (ns). The ATP cell is one of six
  tour × period top-bin cells and was not pre-declared as the test.
- **Betting:** ensemble EV > 0 and I* ≥ γ. Only γ = 1 had 300 or more discovery bets: +5.0%
  at Bet365 (−2.2, +12.3), n 893. Judged on 2022-25:

| Prices | Return | n |
|---|---|---|
| Bet365 | +1.3% (−5.2, +7.7) | 1,290 |
| Three-book average | +2.2% (−4.5, +9.4) | 998 |
| Betfair net of 5% commission | +6.9% (−1.3, +15.9) | 1,408 |

None is significant.

**Reading:** on our data the market is not measurably worse at intransitive matchups. The
paper's result (top tiers only, Pinnacle, a graph network) may still hold for its own model and
segment. Our test replaces the graph network with our ensemble, so it tests "the market misprices
intransitive matchups" rather than "MagNet beats the market". Status: closed for the
market-inefficiency claim on this data. The ATP top-bin and Betfair cells are hypotheses at
most, to be pre-declared if revisited on post-seal data.
