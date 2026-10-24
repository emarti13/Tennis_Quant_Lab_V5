# Replication: first-round vs later-round favourites and underdogs (Pinnacle blog, 2026-10-22)

Claim checked: a Pinnacle "Educational" article (author "Nishikori", FavOrDog.io data). Universe:
ATP 250 / 500 / 1000 main draw, best of 3, 2017-2026, Pinnacle close. Claims:
- First round: favourites −1.7%, underdogs −5.9%.
- Second round to final: favourites −3.8%, underdogs 0.0%.
- That 8-point swing "does not happen by chance".
- Second round with the favourite off a bye: favourites −6.5%, underdogs +3.5%.
- The pattern is absent in 2010-2016.

Our data is independent of theirs. Code: `research_tests/round_effect/run_round_effect.py`
(QA checks pass). Favourite = higher de-vigged four-book consensus close (Kaggle) or Pinnacle
close (2026). "Fair" = return at the consensus fair price (margin removed: only the
favourite/underdog split matters).

| Data | First round: fav / dog | Later rounds: fav / dog | Swing (later gap − first-round gap), 95% range |
|---|---|---|---|
| Kaggle 2017-25, fair (n 15,420) | +0.8% / −3.9% | −0.9% / +0.5% | +6.0 points (−0.8, +13.2) |
| Kaggle 2017-25, Bet365 actual | −5.4% / −8.6% | −6.4% / −4.9% | +4.6 points (−1.9, +11.0) |
| Kaggle 2022-25, fair | +1.8% / −6.1% | −0.7% / −0.7% | +7.9 points (−1.8, +17.6) |
| Kaggle 2014-16, fair | +1.3% / −2.9% | +1.3% / −6.7% | −3.7 points (−16.1, +8.5) |
| Pinnacle 2026 actual (n 1,335) | +2.9% / −14.1% | −5.2% / −1.0% | +21 points (−0.5, +43) |

Second round, favourite coming off a bye (Kaggle 2017-25, fair): favourites −3.9%, underdogs
+3.7%. Gap +7.6 points (−2.4, +18.0), n 2,193.

**Reading:**
- **Direction replicates** on independent data (2017-25 and 2026): first-round underdogs are
  relatively overpriced, and seeds off a bye are relatively overpriced as favourites.
- **The size is similar** (+6 points against the article's +8).
- **Not significant at 95% on our data.** The article's "cannot be chance" is overstated. Each
  match contributes one favourite and one underdog bet with opposite outcomes, so the gap is
  noisy; its 95% range includes zero.
- **The pattern is absent in 2014-16**, as the article itself says. It is time-varying or partly noise.
- **Nothing profitable blind.**
  - First-round favourites are +0.8% at the fair price before any margin; −5.4% at Bet365.
  - 2026 Pinnacle first-round favourites +2.9% is on 565 matches with a wide range.

**Our model does not use it.** The rolling ensemble on top of the consensus shifts towards the
favourite by the same +1.0 point in every round (a general favourite-longshot correction). Its
log-loss gain is larger in first rounds (+0.0018, range 0.0004-0.0030) than later (+0.0006, ns).

**Status:** a candidate feature (round × favourite and favourite-off-a-bye), not a betting rule.
Next step if pursued: a pre-registered market-offset test with those two terms. Fit on 2014-2021,
judge on 2022-2025 log loss against the consensus close, then on 2026 Pinnacle.
