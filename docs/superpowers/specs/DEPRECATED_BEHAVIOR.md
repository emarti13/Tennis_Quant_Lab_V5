# V5 Deprecated / Superseded Behavior

The following behaviors are explicitly superseded and must not be restored by following an older spec, plan, branch, screenshot, or remembered implementation:

- Card-only main experience that removes the complete Daily Forecast Board.
- Exactly one official/top bet per match regardless of independently qualifying markets.
- Discarding ancillary/review candidates with no audit trail when the day changes.
- Repricing that mutates an already frozen official recommendation.
- Calculating official performance from transient current-board state rather than the settled official ledger.
- Treating CourtSpeed as a mandatory dependency that can prevent the ordinary Daily Board from being produced solely because current coverage is absent.
- Requiring daily manual court-condition entry.
- Fabricating court-condition values solely to avoid unknown state.
- Treating Indian Wells Open and BNP Paribas Open as separate same-tour tournament identities.
- Publishing context warehouse artifacts by building first and then attempting `git pull --rebase` on the dirty worktree.
- Heavy upstream model/context/data rebuilds during Streamlit page load.
- Reactive model/policy changes based on recent isolated wins/losses.
- Declaring a production architecture fix complete solely because a unit/regression suite passed when the affected production workflow has not been verified.

If current code appears to implement one of these behaviors, treat it as a potential regression and investigate against `PROJECT_MANDATE.md` and `CURRENT_ARCHITECTURE.md` before normalizing it as intended behavior.