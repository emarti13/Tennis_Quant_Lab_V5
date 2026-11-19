# Does serving get worse the longer the set goes? (2026-11-19)

**Status:** exploratory. Historical data, before 2026-11-01.

**Hypothesis (user):** "the longer the set goes, the more pressure builds and the more serving errors occur".

**Test:** `research_tests/pressure/run_set_length.py`, design pushed (`c6380f5`) before the run.

**Data:** Match Charting Project:

| tour | matches | service games |
|---|---|---|
| WTA | 4,248 | 89,251 |
| ATP | 7,521 | 201,220 |

## Results as registered (expected hold from the server's serve over the whole match, this game left out)

| stage (game number in the set) | WTA held / expected | WTA double faults per 100 serve points | ATP held / expected | ATP double faults per 100 serve points |
|---|---|---|---|---|
| games 1–4 | 66.2 / 65.2 | 5.08 | 79.6 / 78.9 | 3.37 |
| games 5–8 | 65.9 / 65.7 | 4.80 | 79.7 / 79.4 | 3.29 |
| games 9–10 | 66.8 / 67.6 | 4.57 | 81.3 / 81.6 | 3.25 |
| games 11–12 (5-5, 6-5) | 67.8 / 67.6 | **4.27** | 80.4 / 82.6 | **3.10** |

**PRIMARY**, games 11–12 minus games 1–4:

| | WTA | ATP |
|---|---|---|
| hold deviation | −0.8 (−2.3, +0.8) | −2.9 (−3.7, −2.1) |
| double-fault deviation (per 100 serve points) | **−0.80 (−1.09, −0.54)** | **−0.18 (−0.31, −0.05)** |

## Check added after seeing the results: expected hold from the server's OTHER sets

A set that reaches 5-5 is one where both players held easily, so the whole-match serve rate is flattered by that set. That makes late games look worse.

With the expected hold taken from each server's other sets only:

| | games 11–12 minus 1–4 | games 9–10 minus 1–4 |
|---|---|---|
| WTA | +1.3 (−0.5, +3.0) | +0.3 (−0.9, +1.6) |
| ATP | −0.4 (−1.2, +0.4) | +1.0 (+0.4, +1.6) |

## Label

**Ruled out above about 1–2 points:** holds do not fall as a set gets longer. The ATP drop in the registered primary is a selection effect.

**Double faults go down late in sets, not up:**
- WTA 5.1 → 4.3 per 100 serve points;
- ATP 3.4 → 3.1.

Servers play safer second serves when the set is tight.
