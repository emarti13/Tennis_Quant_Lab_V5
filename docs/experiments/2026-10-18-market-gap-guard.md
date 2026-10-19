# Model guard: model versus market gap (2026-10-18)

User decision 2026-10-18: a model price more than **15 points** from the market's fair price
is labelled REVIEW (never BET, LEAN or an official recommendation). Rebuild plan Step 4: "The
model guard runs before anything is frozen or published: extreme model-vs-market gaps block a
price." Code: `v5_reprice_markets.apply_market_gap_guard` (reference: Pinnacle de-vigged with
its measured lam, else the feed's consensus fair price).

## Data

2026 matches before the sealed period with a Pinnacle close (not stale) and both players at
18+ rated matches (the pricing minimum): 5,857. Model: the baseline Elo
(`docs/experiments/2026-10-17-baseline-elo.md`). "Gap" = |model − Pinnacle fair|.

## Who is right when they disagree

| Gap | Share | Model log loss | Pinnacle log loss |
|---|---|---|---|
| up to 5 points | 42% | 0.610 | 0.609 |
| 5–10 | 30% | 0.619 | 0.614 |
| 10–15 | 16% | 0.627 | 0.587 |
| 15–20 | 7% | 0.686 | 0.617 |
| 20–25 | 3% | 0.703 | 0.564 |
| 25–30 | 1% | 0.754 | 0.606 |
| over 30 | 1% | 0.898 | 0.616 |

Above 20 points the model's side won 31.3% of the time; Pinnacle priced it at 33.2%. A large
disagreement is the model being wrong, not an edge.

## Threshold (chosen on January–June, checked on July–October 12)

"Excess" = model log loss − Pinnacle log loss.

| Flag above | Flagged Jan–Jun / Jul–Oct | Excess on flagged | Excess on kept |
|---|---|---|---|
| 10 points | 28.4% / 24.9% | +0.078 / +0.041 | +0.002 / +0.008 |
| 12.5 | 19.4% / 16.8% | +0.093 / +0.044 | +0.007 / +0.011 |
| **15** | **12.5% / 10.6%** | **+0.120 / +0.070** | **+0.009 / +0.010** |
| 17.5 | 8.6% / 6.7% | +0.142 / +0.121 | +0.012 / +0.009 |
| 20 | 5.8% / 4.1% | +0.160 / +0.186 | +0.015 / +0.009 |
| 25 | 2.3% / 1.6% | +0.190 / +0.256 | +0.019 / +0.013 |

15 points catches the clearly wrong prices in both halves without flagging a quarter of the
board. Even on the kept matches the model is still behind the market: the guard makes the
board safe; it does not create an edge (the model work that should is the next phase).

## Live check

Feed of 2026-10-17 03:15: 66 priced moneyline selections, all with a Pinnacle reference;
2 flagged (Sorribes Tormo 71% against Pinnacle 45%), which repricing had labelled BET.
