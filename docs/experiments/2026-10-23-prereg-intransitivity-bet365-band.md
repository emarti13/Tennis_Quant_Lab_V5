# Pre-registration: intransitivity segment and Bet365 underdog band

Written 2026-10-23, before either test was run. Research queue tests 1 and 2 in
`docs/Research/DIGEST.md`. Data: Kaggle odds file 2014-2025 joined to our matches (non-ITF,
completed, not retired), leak-fixed features. No sealed-period data (matches on or after
2026-10-13). Roadmap gate: Phase 1 (candidate segments for the Gate 1 report).

## Test 2: Bet365 underdog price band (market-only rule)
**Rule search (discovery, 2014-2019 only).** Bet on the underdog (the higher Bet365 price) at
Bet365's closing price. Bands of the underdog price:
[1.8, 2.2), [2.2, 2.6), [2.6, 3.2), [3.2, 4.0), [4.0, 6.0), plus the pooled band [2.2, 4.0).
The chosen rule is the band with the highest discovery return among bands with at least 1,000
bets. It is used only if its discovery 95% range is above zero; otherwise the test stops with
"no rule".

**Confirmation (2020-2025).** The chosen band's return at Bet365 closing prices, with a
match-resampled 95% range. The same bets are also reported:
- against the fair price from the other three books (Betfair, Ladbrokes, Unibet de-vigged);
- by tour group (ATP, Challenger, WTA).

**Success:** the confirmation range is above zero.
**Known contamination:** the 2026-10-21 study pooled 2017-25 when it saw model profits on
Bet365 underdogs priced 2.2-4.0. So 2020-25 is not fully unseen for the *idea*. It is unseen for
this market-only rule and its band choice. Clean proof needs post-seal data.

## Test 1: intransitivity (Clegg & Cartlidge 2025)
**Measure.** For each match (u, v) on surface s, compute everything from matches of events that
ended before the match's event started (completed events only; leak-free and conservative).
- **Dominance** (paper eq. 3): D(i, j) = Σ α β e^(−λΔt) g / Σ α β e^(−λΔt), where g is the
  share of games won. λ = 0.38 per year.
- **Surface transfer** (paper Table 3): from grass to hard 0.37, hard to grass 0.45, clay to
  hard 0.01, hard to clay 0.07, grass to clay 0.09, clay to grass 0.05; same surface 1.
- **Tier weight β:** Slams 1, Finals 0.94, Masters / WTA 1000 0.85, 500 0.69, every lower tier
  0.5 (our choice; the paper covers only the top tiers).
- **Common-opponent subgraph:** u, v and up to 25 common opponents, chosen by the smaller of
  their evidence weights with u and with v. Edges are all pairs in it with history.
- **Advantage:** A = logit(D), clipped to [0.02, 0.98].
- **Hodge split:** the least-squares potential gives the transitive part, the residual the
  cyclic part. I = (1 + ‖cyclic‖) / (1 + ‖transitive‖).
- **Evidence scaling:** I* = I · √(evidence weight of the direct u-v history). I* = 0 with no
  direct history.

**Claim tested:** the market is relatively worse at high I*. Measured as the per-match log-loss
gain of our rolling ensemble (`research_tests/kaggle_odds`, close base, leak-fixed) over the
consensus close, by I* bin:
- bin 0: I* = 0;
- bins 1-3: tertiles of I* > 0, with cut points fixed on 2017-2021.

**Success (both required):** on 2022-2025 the gain in the top bin exceeds the gain in bin 0, and
the difference's 95% range is above zero.

**Betting check.** Ensemble EV > 0 and I* ≥ γ, with γ taken from the grid {1, 1.5, 2, 2.55, 3,
4}. γ is chosen as the best Bet365 return on 2017-2021 (at least 300 bets) and judged on
2022-2025 at Bet365, the three-book average, and Betfair net of 5% commission.
Reported by tour; women's tour noted first (the paper finds it 11.5% more intransitive).
