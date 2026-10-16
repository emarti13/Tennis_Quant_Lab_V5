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
| `docs/roadmap-fair-price-to-market-making` | Fully merged into `main` (PR #38) | 2026-10-12 |
| `fix/retired-infer-surface-imports` | Fully merged into `main` (PR #37) | 2026-10-12 |
| `fix/phase0-ci-green-and-season-rollover` | Merged (PR #39) | 2026-10-12 |
| `docs/rebuild-plan-and-tournament-identity` | Merged (PR #40) | 2026-10-12 |
| `feat/master-schedule-reconciliation` | Merged into #39's branch (PR #41), then into `main` via #43 | 2026-10-12 |
| `repair/step1-repo-cleanup` | Merged into #39's branch (PR #42), then into `main` via #43 | 2026-10-12 |
| `repair/land-step1-and-schedule-on-main` | Merged (PR #43) | 2026-10-12 |
| `feat/step2a-schedule-locations` | Merged (PR #44) | 2026-10-12 |
| `feat/step2b-tournament-crosswalks` | Merged (PR #45) | 2026-10-13 |
| `docs/player-identity-spec` | Merged (PR #47) | 2026-10-13 |
| `feat/official-ledger-switch` | Merged (PR #48) | 2026-10-13 |
| `fix/no-bet-without-player-history` | PR #46 closed without merging (owner decision: no patches to the old engine) | 2026-10-13 |
| `feat/step2c-player-identity` | Merged (PR #49) | 2026-10-15 |
| `feat/step2d-production-identity` | Merged (PR #50); its last commit moved to `feat/tournament-review-decisions` | 2026-10-15 |
| `feat/tournament-review-decisions` | Merged (PR #51) | 2026-10-16 |
| `feat/identity-decision-files` | Merged (PR #52) | 2026-10-16 |
| `docs/step3-market-data-spec` | Delete once its PR is merged | 2026-10-16 |
| `research/step3-probe` | One-off probe; findings in `docs/experiments/2026-10-16-step3-market-source-probe.md`. Never merged | 2026-10-16 |
| `claude/bootstrap-v5-history-setup-3pxlyr` | Agent session branch; all its work reached `main` via #39–#43 | 2026-10-12 |

```bash
git push origin --delete docs/roadmap-fair-price-to-market-making fix/retired-infer-surface-imports \
  fix/phase0-ci-green-and-season-rollover docs/rebuild-plan-and-tournament-identity \
  feat/master-schedule-reconciliation repair/step1-repo-cleanup \
  repair/land-step1-and-schedule-on-main feat/step2a-schedule-locations \
  feat/step2b-tournament-crosswalks docs/player-identity-spec feat/official-ledger-switch \
  fix/no-bet-without-player-history feat/step2c-player-identity feat/step2d-production-identity \
  feat/tournament-review-decisions feat/identity-decision-files docs/step3-market-data-spec \
  research/step3-probe \
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
