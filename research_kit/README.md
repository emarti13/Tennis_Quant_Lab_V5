# Research toolkit and the checks every result must pass

Added 2026-10-31. Several research runs had bugs, and the bugs that were caught were mostly the
ones that made results look too good. A bug that hides an edge looks like one more "no edge"
result. These rules apply to every research test from now on.

## Use the shared pieces

`research_kit.core` has orientation (`coin_flip`, `orient`), `devig`, `logit`, `log_loss`,
`walk_forward`, `boot_mean` (seeded once; optional clusters), `back_bets` (fees) and
`kalshi_taker_fee`. Do not re-implement them in a script. They are tested in
`tests/test_research_kit.py`.

## Run the general checks (`research_kit.checks`) and report them with the result

| Check | What it proves | What it would have caught |
|---|---|---|
| `swap_source` | The model's inputs do not depend on which side the source listed first: bitwise identical after relabelling the source | the `1 - p` orientation leak (2026-10-31) |
| `time_travel` | Features rebuilt from history cut at each decision time equal the normal build | the DraftKings look-ahead, the qualifying seed leak |
| `planted_edge` | The test finds an edge of known size planted in the outcomes (reports the share recovered) | a test too weak or broken to see an edge |
| `market_null` | With outcomes drawn from the market, the test finds nothing; its result is the cost of fitting the features | "worse than the market" that is only fitting noise |
| `shuffled_null` | A model without the market is no better than a coin on shuffled outcomes | any use of the result as an input |
| `known_answers` | The market's log loss is in its known range; A wins about half | a broken join, orientation or de-vig |
| `alarms` | Flags results too good (audit for a leak) or worse than the market beyond chance (audit for a hidden-edge bug) | both directions |

Read a result against its checks: compare it with the market-null cost, and judge "no edge"
only as far as the planted-edge recovery shows the test could see one.

## Rebuild independently

For any result that changes a decision, a second agent rebuilds the test from the written
spec without reading the first implementation. A mismatch means one of them has a bug.

## Every bug becomes a check

When a bug is found, write it up in the experiment note and add a test (here or in
`tests/test_research_kit.py`) that fails on that kind of bug.

## Reproduce

Each run writes a manifest (`research_kit.provenance`): input fingerprints, git commit, seeds,
package versions and the command. Rerunning the command on the same inputs must give the same
numbers.

## The last check is the future

A backtest can be wrong in ways no check covers. An edge that passes is run as a paper strategy
on live prices it has never seen (the server runner), with rules fixed in advance, before any
real money, and then with small stakes before larger ones.
