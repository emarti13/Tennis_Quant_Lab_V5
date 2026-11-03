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
| `feat/backfill-newest-first` | Merged (PR #73) | 2026-11-03 |
| `docs/research-hub` | Merged (PR #74) | 2026-11-03 |
| `fix/pandas-3-1-timedelta` | Merged (PR #75) | 2026-11-03 |
| `docs/rolling-forward-test` | Merged (PR #76) | 2026-11-03 |
| `docs/registration-kalshi-longshot` | Merged (PR #77) | 2026-11-03 |
| `docs/manual-cleanup-nov` | This change, once merged | 2026-11-03 |

```bash
git push origin --delete feat/backfill-newest-first docs/research-hub fix/pandas-3-1-timedelta \
  docs/rolling-forward-test docs/registration-kalshi-longshot docs/manual-cleanup-nov
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
