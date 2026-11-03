# How research is reported

Status: DRAFT — pending user approval. Proposed 2026-11-03, after the user had to challenge
verdicts to find errors.

## Every research result says

1. **What was tested:** the rule, written before any result was read, and the data, with n.
2. **The result against the close and with money at an executable price:** fees included, and
   no cost counted twice.
3. **What the test could detect** (minimum detectable effect), so that "nothing found" always
   comes with "below X".
4. **One label:**
   - confirmed effect;
   - candidate (worth a registered forward test);
   - inconclusive below X;
   - ruled out above X.

   "Closed" is used only for "ruled out above X" with X economically small.
5. **The checks** (research_kit) and any bug found and fixed on the way.
6. **Economically large slices** (|residual| ≥ 2 points or ROI ≥ 3%) even when not significant,
   marked if chosen after seeing the data.

## Before a verdict changes a decision

- The `research-auditor` agent (`.claude/agents/research-auditor.md`) audits it independently. Its
  report goes to the user unedited.
- A candidate becomes a registered forward test (`docs/registrations/`) before any money.

## When the idea queue is empty

The `idea-scout` agent (`.claude/agents/idea-scout.md`) proposes and ranks new hypotheses with free
data and a test design. The user picks which to run.

## Status page

`docs/experiments/` holds one note per test; `research_tests/README.md` is the index. The server's
`market_history/vm_status.md` (branch `data/vm-logs`) shows the registered forward tests daily.
