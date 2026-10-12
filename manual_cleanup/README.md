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

```bash
git push origin --delete docs/roadmap-fair-price-to-market-making fix/retired-infer-surface-imports
```

### Pending your decision (not yet recommended for deletion)

About 70 branches from September 2026 (for example `feature/court-conditions-source`,
`fix/market-feed-resilience`). `main`'s history was squashed into one commit on 2026-10-07,
so git cannot tell which of these are already contained in `main`, and they are the only
record of September's commit history. Recommendation: keep them. If you decide to delete
them, say so and they will be listed here with a command. Leave `btc-bot-test` alone either
way (it looks like a separate project).

## Session branches after their PRs merge

Once a PR is merged, its branch can be deleted with GitHub's "Delete branch" button on the PR.
Open as of 2026-10-12: #39, #40, #41 and the Step 1 cleanup PR, plus the agent session branch
`claude/bootstrap-v5-history-setup-3pxlyr` (all of its work was split into #39–#41).
