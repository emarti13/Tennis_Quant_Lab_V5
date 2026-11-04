# Registration: bet the blend's side at Kalshi's opening quote; the price should move toward it by the close

Registered 2026-11-04 under `docs/superpowers/specs/2026-11-01-rolling-forward-test-amendment.md`.
This file is never edited; a changed rule is a new registration.

## Hypothesis and the decision it would change

Pre-match information about the body and the schedule changes what a player is worth before the start:
- a recent final;
- a layoff;
- a change of surface;
- coming through qualifying;
- age;
- the end of the season;
- defending points;
- a walkover in the last round.

The market prices this information **between the open and the close**. A bettor who acts at the opening quote, on the side these signals favour, gets a price better than the close.

On the sportsbook data this was true, but Bet365's 6.7% opening margin ate the gain. Kalshi's cost is lower: a taker fee of about 1.75¢ at 50¢, plus the spread. So the same bets should beat the Kalshi close after costs.

- **If it passes:** betting the blend early on Kalshi joins the candidates for small real stakes, after the research_kit checks and a second forward window.
- **If it fails:** betting early on these signals is dropped for Kalshi.

## Where it came from (data before 2026-11-01)

- `docs/experiments/2026-11-04-betting-early.md`: 82,199 matches from 2016–25, with all checks passing.
  - The signals predict the move from Bet365's open to the close. For example:
    - after a final, +1.3 pts toward the finalist;
    - a returning player, 1.1 pts toward the opponent;
    - a surface switch, 0.8 pts toward the opponent.
  - The blend's bets at a 3-point edge moved +2.1 pts toward the bet, with the close better than the price taken 64% of the time.
  - The expected return from the close at Bet365's open was −0.9% to −1.6%, because of the margin.
- `research_tests/open_clv/freeze_kalshi_blend.py` (branch `research/kit`, commit `2a9a27d`) froze the weights of the reduced model below. Walk-forward on 2022–25 it is as good as the full blend: log loss against the open −0.00068 (−0.00117 to −0.00018).

The inputs were chosen on 2016–25, so only this forward window counts.

## The rule (scored by `scripts/track_kalshi_blend_rule.py` at commit `a6469af09c03dd985918847f41b167963fb639cd`, branch `feat/vm-runner`)

- **Markets:** Kalshi series KXATPMATCH, KXWTAMATCH and KXATPCHALLENGERMATCH.
- **Window:** matches whose scheduled start (Kalshi milestone `start_date`) is after **2026-11-04T18:00:00Z** (set in the code before this file was committed).
- **Opening snapshot:** the **first** 5-minute pre-match snapshot from the server's logger that meets all of these:
  - both markets have a bid and an ask;
  - each spread is at most 5¢;
  - it is at least 60 minutes before the scheduled start;
  - it is before the match first appears in the live log.
- **Base price:** p_A = mid_A / (mid_A + mid_B) at that snapshot.
- **Model:** P(A) = sigmoid(w_open × logit(p_A) + Σ w_i × (x_i,A − x_i,B)). There is no intercept, so the order of the players does not matter. The weights are frozen in `research_tests/open_clv/kalshi_blend_weights.json`:
  - open 1.0777, age_gap −0.0595, qualifier +0.0999, season_end −0.2073, wildcard +0.0252, defending +0.0149, hangover −0.0135, venue −0.0143, layoff −0.1547, surface −0.0426, surface_spec +0.0500, freepass +0.0053.
  - The weight on the open (1.08) also stretches the price slightly toward the favourite. That is part of the frozen model.
- **Inputs:** built by the same functions as the research (`research_tests/scout/run_scout.py`, `research_tests/incentives/run_incentives.py`, `v5_fatigue_features.load_repo_matches`). Parity with the research inputs is exact on 2,980 sampled 2016–25 matches.
  - The match facts are entry code, round, ages, ranks and earlier matches. They are read from the match's TennisMyLife row (history cache plus `v5_results_ready/tennismylife_results.csv` on `main`). Only facts public before the match are used.
  - The row appears after the match, so the paper decision is reconstructed then, at the logged opening price.
  - A match with no row after 14 days, a player name that does not match, or a missing input means **no bet**.
  - Inputs that need start times, venue coordinates or the next Slam's dates are not used: jet_lag, short_rest, altitude, pre_slam, the ranking bubbles.
- **Cost of backing a player:** the cheaper of YES on them (the ask) and NO on the opponent (1 − the opponent's bid), plus the Kalshi taker fee rounded up to the cent on 100 contracts: ceil(0.07 × 100 × P × (1 − P) × 100) / 100 dollars.
- **Bet (paper):** the side whose model chance minus cost is larger, if that is at least **3 points**. 100 contracts.
- **Close:** the last 5-minute snapshot before the match first appears in the live log (or before the scheduled start) in which both markets have a bid and an ask. p_close of the backed player = its mid / the sum of the two mids.

## Metric, pass rule, sample, end

- **Primary metric:** CLV per contract = p_close(backed) − price − fee. This is the expected return if the Kalshi close is the true price.
- **Pass:** the 95% range (2,000 resamples of bets, seed 20261103) is wholly above zero.
- **Minimum sample:** 300 bets.
- **Ends:** at 300 bets, or on 2027-10-31 if fewer, then scored once. If it ends with fewer than 300, it is recorded as inconclusive.
- **Reported alongside (not part of the pass rule):**
  - realised P&L on Kalshi results (the backed player's market: `yes` or `no`; anything else is void);
  - the move in mid toward the bet;
  - the share of bets with positive CLV;
  - results by series;
  - **where each bet's edge came from:**
    - the stretch of the opening price by w_open alone (with no signals);
    - the signals' part;
    - whether the bet would still clear 3 points with the signals on the unstretched price (w_open = 1);
    - CLV for the bets that clear on signals alone versus the rest.

    This splits the result between the long-shot correction and the signals. It does not change which bets are made.
  - A Pinnacle-close version of the CLV will be added as a separate report when the Pinnacle closes are joined to these fixtures. It is not part of this rule.

## Not allowed during the window

Changing any of these:
- the weights;
- the inputs;
- the edge bar;
- the snapshot rules;
- the series;
- the size;
- the fee model;
- the name matching;
- the void rules.

Watching the running number is allowed; acting on it is not.
