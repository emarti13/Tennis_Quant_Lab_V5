# Manual cleanup

Things an agent session could not remove itself (for example, deleting GitHub branches is
blocked from agent sessions). Work through the list when convenient, then delete the entry
from this file. Agents: add an item here instead of only mentioning it in chat (see CLAUDE.md).

Each item says what it is, why it can go, and how to remove it.

## GitHub branches

Delete from https://github.com/emarti13/Tennis_Quant_Lab_V5/branches (trash icon), or from a
local clone with the command shown.

| Branch | Why it can go | Added |
|---|---|---|


```bash
git push origin --delete docs/roadmap-fair-price-to-market-making fix/retired-infer-surface-imports \
  fix/phase0-ci-green-and-season-rollover docs/rebuild-plan-and-tournament-identity \
  feat/master-schedule-reconciliation repair/step1-repo-cleanup \
  repair/land-step1-and-schedule-on-main feat/step2a-schedule-locations \
  feat/step2b-tournament-crosswalks docs/player-identity-spec feat/official-ledger-switch \
  fix/no-bet-without-player-history feat/step2c-player-identity feat/step2d-production-identity \
  feat/tournament-review-decisions feat/identity-decision-files docs/step3-market-data-spec \
  research/step3-probe feat/pause-old-forecast research/step3a-trial \
  feat/step3a-price-store research/step3b-kalshi-shapes research/step3b-kalshi-trial \
  feat/step3b-kalshi feat/step3c-devig feat/step3-bet365-history feat/step3d-results-kalshi \
  feat/step3e-live-prices research/step3e-live-trial research/inplay-winners \
  feat/step4a-fixture-stage feat/step4b-results-inplay feat/step4c-lucky-loser \
  fix/market-history-expiry-by-date docs/repo-map-step4 repair/fatigue-v1-safety-layer \
  feat/step4e-baseline feat/step4f-pricing feat/step4f-pricing-to-main fix/oddspapi-network-errors \
  feat/step4g1-production-switch feat/step4-market-gap-guard docs/manual-cleanup-step4 \
  claude/bootstrap-v5-history-setup-3pxlyr
```

### Pending your decision (not yet recommended for deletion)

About 70 branches from September 2026 (for example `feature/court-conditions-source`,
`fix/market-feed-resilience`). `main`'s history was squashed into one commit on 2026-10-07,
so git cannot tell which of these are already contained in `main`, and they are the only
record of September's commit history. Recommendation: keep them. If you decide to delete
them, say so and they will be listed here with a command. Leave `btc-bot-test` alone either
way (it looks like a separate project).

## Session branches after their PRs merge

Once a PR is merged, its branch can be deleted on a computer browser: open the PR, scroll to
the bottom, click "Delete branch" (the GitHub phone app does not show this button). Agents
add each merged branch to the table above.
