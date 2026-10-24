# Gate 1 segment report (Phase 1: honest benchmark)

**DRAFT — pending user approval.**

Written 2026-10-23. Roadmap: `2026-10-12-fair-price-to-market-making-roadmap-design.md` §4.
Gate 1 asks for:
- a written segment report the user reviews and approves;
- candidate segments and Phase 2 metrics fixed in writing before Phase 2 starts.

Everything below uses data before the sealed period (matches on or after 2026-10-13 are sealed).

Evidence lives in `docs/experiments/`:
- 2026-10-21-first-server-effect
- 2026-10-21-kaggle-odds-edge-search
- 2026-10-23-intransitivity-bet365-band

It also draws on `research_tests/README.md` on the research branches
(`research/kalshi-making-sim`, `claude/clever-fermi-hv34lk`).

## 1. What Phase 1 asked for, and what was measured

| Roadmap item | Status | Finding |
|---|---|---|
| **Pinnacle close efficiency** (calibration, favourite-longshot bias by tour/tier, surface, price, time before start) | Done 2026-10-24 | `docs/experiments/2026-10-24-gate1-gaps.md`. Pinnacle's close beats its open by 0.0055 log loss; almost nothing arrives after t-24h. With the measured de-vig (λ 1.5) the close is near-calibrated (slope 1.06; multiplicative 1.15). The bias is strongest in Challenger and WTA125. Backing favourites does not pay at real prices. Long shots are overpriced at every soft book. |
| **Does the leak-free model add information beyond the market** (`logit p = a·logit p_mkt + b·logit p_model`, b by segment) | Done 2026-10-24 | Production-parameter Elo: b = −0.04 (−0.16, +0.08), never reliably above zero in any segment. Feature ensemble vs a correctly de-vigged Pinnacle close: +0.0001 (−0.0009, +0.0011). |
| **Open-to-close gap** (how much the market learns, and when) | Done | The close absorbs about 15% of the model's disagreement with the open: +1.0 point toward the model, +1.6 where the model differs by 5+ points. DraftKings opens a median 2 hours before Pinnacle. |

The model-versus-market results behind the second row:
- **Against soft books:** the model beats the soft-book consensus close by +0.0007 with a
  calibrated de-vig (+0.0013 with the multiplicative one; see §2b).
- **Against Pinnacle:** in 2026 at the close the gain is +0.0001 (−0.0009, +0.0011) with the
  calibrated de-vig (+0.0009 with the multiplicative one). On top of Pinnacle's open it is not
  significant.
- **Segment searches found nothing robust.** About 2,800 cells were searched per base, then
  pre-registered tests run on intransitivity and the Bet365 underdog band.
- **Leak found and fixed:** the research feature table chose an event's home country from
  match results; production has no such feature.

## 2. Candidate segments, ranked
No segment shows a reliable b > 0 against Pinnacle's close. The roadmap's rule for that case
is that Phase 2 focuses on the segments with the largest open-to-close movement, so the list
is ordered by evidence and by how the gate would treat each.

| # | Segment | Evidence so far | Type of gate it can pass |
|---|---|---|---|
| C1 | **Early decisions: model vs the line standing at decision time.** Pinnacle open, or the execution-book opener when Pinnacle is not yet up. | The model moves the close toward itself (about 15% of its disagreement). On DraftKings' opener (timing-safe, ensemble, EV > 5%): closing-line value vs Pinnacle's close +2.3% (1.3, 3.4), n 633. **Audit (`docs/experiments/2026-10-23-data-audit.md`):** 82% of that comes from the 5% of bets where DraftKings' opener is far from the market. With the gap capped at 0.10 it is +1.0% (0.3, 1.7). It fades: Jul +0.6%, Aug +0.4%. A blind replication with an Elo-based model finds negative closing-line value. DraftKings prices in our data stop on 2026-08-09. **DraftKings is not on the execution list (CLAUDE.md: Bet365, BetRivers, Kalshi, Polymarket, Novig)**, and from September the collector requests Pinnacle, Bet365 and BetRivers instead. At BetRivers' opener the same rule has negative closing-line value; Bet365 openers are thin in our data. | Not executable as it stands. Kept only as a Bet365/BetRivers-opener shadow (below); DraftKings only if you add it as an execution book. |
| C2 | **Challenger main draw and qualifying** (the roadmap's own example) | The model's largest gain over the soft-book consensus is here (+0.0018 in 2022-25 among matches with no prior meeting). Pinnacle's coverage of Challengers is thinner. | Gate 2 (log loss vs Pinnacle close) |
| C3 | **All tours, Pinnacle close** (the control segment) | +0.0001 (ns) on 2026 with the calibrated de-vig | Gate 2 |
| C4 | **Post-toss game handicaps** | The server shift is real (slope 0.84 totals, 1.22 margin). Pinnacle reprices only about 23% of the handicap shift. Model value about +3% on about 20% of fixtures. | Needs a live first-server feed; spread markets are out of the roadmap's gates (§6), so research only |
| C5 | **Bet365 prices that later move** (moneyline openers, handicap openers) | Another session's study: +5.1% / +10.8% on Bet365 openers, but only on openers Bet365 later corrected (openers that stood: −2.7% / −4.4%). Handicap openers +7.7% with closing-line value −4 to −5%. | Needs timestamped live Bet365 quotes; an upper bound until then |

Closed (not candidates):
- market-only Bet365 underdog bands;
- intransitive matchups;
- the pre-match first-server prior;
- post-toss totals;
- line-shopping alone;
- BetRivers;
- Kalshi in-play taker rules;
- betting at the 2026 close.

## 2b. Correction (2026-10-24)
The +0.0013 and +0.0009 model gains above used multiplicatively de-vigged prices, which make
the market look about 0.001 worse than it is. Against a calibrated benchmark they are +0.0007
(soft-book consensus) and +0.0001 (Pinnacle close, not significant). No model beats Pinnacle's
close. Under the roadmap's rule, Phase 2 should focus on the segments with the largest
open-to-close movement. The market learns mostly before t-24h, so that means early decisions
(C1); the lower tiers (C2) have the strongest remaining bias.

## 3. Phase 2 metrics (fixed here, before Phase 2 starts)
- **Primary (Gate 2):** per-match log loss of the frozen engine against the no-vig Pinnacle
  close, de-vigged with `v5_devig` at Pinnacle's measured λ (1.5 as of 2026-10-16), not
  multiplicatively.
  - Run in segments C2 and C3, plus C1's Pinnacle-open variant (engine vs Pinnacle's open) as a
    secondary.
  - Match-resampled bootstrap, 2,000 draws.
  - Pass: the 95% interval excludes zero with at least 300 sealed matches in the segment.
- **Evaluation timing:** each segment is evaluated once, when it first reaches 300 settled
  sealed matches, and again at 1,000. Nothing on the sealed period is used for tuning,
  selection or thresholds.
- **Engine:** frozen before the first sealed evaluation. That is the leak-fixed feature ensemble
  on top of the market input available at decision time (the Layer 3 blend). Its version hash is
  recorded in the evaluation write-up.
- **C1, shadow (Phase 3 measure, starts now, costs nothing):**
  - Rule: EV > 5% at the execution book's opener, that book's own opener as the only market input, and
    the opener within 0.10 of the model's probability (excludes stale or erroneous openers,
    which books may void under palpable-error rules).
  - Execution books only: run the shadow at Bet365's and BetRivers' openers (both collected
    now). DraftKings is not an execution book (CLAUDE.md) and has not been collected since
    2026-08-09; it would need your decision to add it.
  - Measure: closing-line value against Pinnacle's no-vig close, after fees.
  - Pass: at least 500 decisions with mean closing-line value > 0, interval excluding zero.
    These are Gate 3's numbers, applied early as a shadow.
- **Voids:** walkovers and matches retired before two completed sets
  (`v5_market_results.py`).

## 4. What must be done before Gate 1 can be approved
Gaps 1 and 2 were done on 2026-10-24 (see the table in §1). Remaining:

1. ~~**Gap 1:**~~ a Pinnacle calibration table by tour/tier, surface and price band for 2026
   pre-seal fixtures (OddsPapi).
2. ~~**Gap 2:**~~ fit `logit p = a·logit p_Pinnacle + b·logit p_V5` with the production V5
   probability, by segment.
3. The user approves the segment list and the metrics above, possibly amended. From then on
   they are fixed.

## 5. Open questions for the user
- Accept the C1 shadow test as described, measured by closing-line value rather than ROI?
- Keep C4 and C5 as research only? Both need data we do not collect: a live first-server feed;
  timestamped Bet365 quotes.
- The data cost rule (roadmap §5.1, "no paid data sources") rules out a paid live feed. Change
  it only by explicit decision.
