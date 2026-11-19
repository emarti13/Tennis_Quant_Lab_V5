# In-play exploration: Kalshi prices a break of serve within a minute

Date: 2026-11-03. Exploration on the server's live logs before 2026-11-03 (175 matches, Oct 31 to
Nov 2, about 29,000 polls at 30 s). Script: `research_tests/inplay_score/explore_inplay.py`;
output: `research_tests/inplay_score/results.json`.

## Method

A score-based win probability for every poll: each player's chance of winning a point on serve
is constant; their sum is the tour average (ATP 1.26, WTA 1.12); their difference is set so the
model's pre-match chance equals Kalshi's mid at the first live poll. The live chance follows
exactly from sets, games, points, server and tiebreaks (best of 3). Results from Kalshi.
Median in-play spread: 1¢.

## Results

- **Calibration:** Kalshi's mid beats the model on outcomes (log loss 0.4172 against 0.4216,
  difference +0.0044, range −0.0055 to +0.0145); a 50/50 blend is no better than the mid.
- **Breaks (793 in 175 matches):** at the poll where a break appears, the model moves 6.7 points
  toward the breaker and the mid only 4.7, and the mid keeps moving 2.6 to 2.9 points toward
  the breaker over the next 5-10 minutes. The breaker then wins 3.5 points more often than that
  mid said (0.9 to 6.1).
- **That lag is a logging artifact.** In each poll the logger read every market's quote first
  and the scores afterwards (up to about 30 s apart at the old speed), so the price at the break
  poll is often older than the score. **One minute after the break the mid has it**: the breaker
  wins 0.9 points more than the mid then (−1.7 to +3.5); 2 and 5 minutes later the same.
- **Money:** backing the breaker at the ask 1, 2 or 5 minutes after the break, holding to the
  end, after the taker fee: −0.6¢, −0.8¢, −0.8¢ per contract (1 minute: −2.0 to +0.9; 791
  breaks). Buying whenever the model and the executable price differ by 5 or 10 points (first
  entry per match): +4.5¢ (−3.5 to +12.2, 134 matches) and +7.8¢ (−3.0 to +17.7, 83): not
  significant, and exposed to the same price-older-than-score artifact.

## What it means

Kalshi's in-play tennis prices are efficient at a one-minute horizon after breaks. An edge
there would need to act within seconds of the point, a speed race against courtside data, which
this project cannot win with public feeds. **Not registered.**

The logger now reads each live match's quote right after its score (feat/vm-runner), so later
in-play work is not exposed to this artifact.
