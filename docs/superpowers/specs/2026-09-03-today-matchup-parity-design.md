# Today Matchup-Lab Parity Design

## Goal
Preserve the Apple-style Today experience while restoring the operational controls the user explicitly wants and making each Today match card contain the same core matchup outputs produced by Matchup Lab.

## Scope
Only Today and Slate Setup / Advanced change. Match Detail, All Markets, Performance, Model Health, and Matchup Lab remain unchanged.

## Today
- Keep sleek summary cards.
- Keep ranked BET / LEAN / REVIEW cards.
- Do not show giant tables by default.
- Each match card must expose the core Matchup Lab projection for that exact simulated matchup: player win probability and fair odds, expected game margin, expected total games, current form, match-day volatility, state confidence, simulator-vs-surface-Elo agreement, and current model-priced market signals for the fixture.
- Today must reuse the same simulation/result values already produced by the daily simulation path; it must not create a second model or alter probabilities.

## Slate Setup / Advanced
Inside a collapsed advanced section, retain:
- simulation precision selector;
- editable Tour / Surface / Best Of fields;
- surface inference/source warnings;
- unmatched-player diagnostics;
- current market slate preview;
- the existing Run Entire Daily Board action.

## Information hierarchy
The default viewport remains decision-first. Advanced controls and slate tables are collapsed. Match cards show the Matchup Lab-style output in compact grouped sections rather than full-width dataframes.

## Non-goals
- No changes to model calculations, thresholds, signal logic, or pricing logic.
- No changes to secondary pages.
- No removal of Matchup Lab.
- No new sportsbook-derived model features.

## Regression rule
Aesthetic simplification may change where information appears, but may not remove analytical or operational capability explicitly retained by this design.