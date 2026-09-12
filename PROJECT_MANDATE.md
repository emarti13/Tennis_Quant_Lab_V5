# Tennis Quant Lab V5 — Governing Project Mandate

## Purpose

This document is the highest-level operating contract for Tennis Quant Lab V5. It exists to prevent architectural drift, local fixes that undermine the product, reactive model changes, and work that does not move the project toward a reliable and sellable MVP.

Every meaningful architecture, model, workflow, UI, data, settlement, or production decision must be checked against this mandate before implementation.

## Precedence

When instructions appear to conflict, use this order:

1. **This governing mandate**
2. **Approved architecture/design specs in `docs/superpowers/specs/`**
3. **Approved implementation plans in `docs/superpowers/plans/`**
4. **Current production code and workflows**
5. **Local bug fixes, experiments, and convenience changes**

A local fix may solve an immediate problem, but it must not violate the governing mandate or the approved architecture.

---

# 1. Primary Goal

Build a **self-sufficient, statistically defensible, sellable tennis analytics product**.

The goal is not merely to make individual scripts run or individual pages load. The system must operate as a coherent production product that:

- refreshes itself;
- produces current recommendations without manual babysitting;
- settles and measures those recommendations accurately;
- preserves one source of truth across production artifacts;
- demonstrates durable out-of-sample predictive and market-pricing value;
- and can evolve into a paid MVP that a customer would find attractive, understandable, and useful.

The intended trajectory is:

**reliable production system → mathematically proven recommendation policy → polished paid MVP**

---

# 2. Production Rule — One System, One Source of Truth

Production must behave as one pipeline, not as a collection of independent scripts that happen to share files.

The target production chain is conceptually:

**data refresh → model/context refresh → frozen sportsbook-independent forecast → market repricing → official recommendation ledger → settlement → performance → UI**

The following are hard requirements:

- One canonical production source of truth for each stage.
- No duplicate production paths that can disagree with each other.
- No live model rebuilds, context rebuilds, external history fetches, or other heavy upstream work inside Streamlit page loads.
- Normal daily operation must not require manual intervention.
- External-source failures must degrade safely using explicit freshness states and last-known-good artifacts where mathematically appropriate.
- Stale data must never silently appear fresh.
- If required inputs are beyond their allowed freshness window, the system must fail closed rather than publish misleading official recommendations.
- Automatic recovery should occur when dependencies recover.
- Production workflows get priority over research, diagnostics, and historical backfills.
- GitHub Actions usage must stay within the available recurring budget without sacrificing useful production freshness.

A production bug is not considered fully solved merely because the immediate exception disappears. The fix must also be checked for whether it exposes or preserves a duplicated path, hidden dependency, stale artifact, manual requirement, or violation of the single-pipeline design.

---

# 3. Model and Profitability Rule

The project exists to identify recommendations with **durable statistical edge**, not to produce a high-looking daily win percentage.

No recommendation policy should be promoted because of:

- a short recent streak;
- a handful of memorable wins or losses;
- user intuition about favorites or underdogs;
- a single large underdog payout;
- or tuning after observing the latest live results.

The system must be evaluated using rigorous, chronological, out-of-sample methods.

Required principles:

- Use untouched walk-forward / chronological validation.
- Freeze predictions before match start.
- Keep sportsbook-independent model probabilities separate from market prices until the pricing/recommendation stage.
- Evaluate calibration, Brier score, log loss, hit rate where meaningful, net units, ROI, drawdown, price bands, favorite/underdog behavior, and fixture clustering.
- Account for correlated recommendations from the same match rather than inflating performance with multiple related markets.
- Report official recommendations separately from PASS, REVIEW, legacy, research, and diagnostic rows.
- Preserve historical frozen predictions; do not rewrite history to make a new policy look better.
- Use realistic available prices and vig-aware comparisons.
- Require enough sample size and stability across time windows before calling an edge durable.
- Continue live monitoring after promotion; a previously accepted policy can be demoted if evidence deteriorates materially.

There is no guarantee of future profitability. The product standard is that **only policies that earn promotion through durable out-of-sample evidence are allowed to drive official recommendations**.

---

# 4. Business Rule — Move Toward a Paid MVP

The eventual product should be something a customer would want to use and pay for.

Before mathematical proof, reliability and model validity take priority over cosmetic polish.

Once the recommendation policy has earned trust, the product should evolve from engineering/debugging tables into a clean customer experience centered on:

- Today’s official recommendations;
- clear model probability and fair price;
- market price and quantified edge;
- useful confidence/context without overwhelming the user;
- matchup detail when deeper analysis is wanted;
- transparent, honest performance history;
- model/data health visibility;
- and a polished, mobile-friendly interface.

The intended customer product should not expose raw engineering complexity unless it is useful to the customer.

The target is an MVP that can begin serious real-world use and productization once the mathematics and production reliability justify it, with the goal of progressing toward a usable paid product rather than remaining a permanent research dashboard.

---

# 5. Debugging Rule — Fix the Problem Without Losing the Product

Isolated fixes are acceptable and often necessary.

However, every production bug must be evaluated at two levels:

### Immediate level
Fix the specific failure correctly and verify it.

### System level
Ask whether the failure reveals:

- a duplicate production path;
- a hidden live dependency;
- a missing freshness contract;
- a missing retry/recovery path;
- a stale artifact being treated as current;
- an unnecessary manual action;
- an Actions-budget problem;
- inconsistent settlement/performance logic;
- or a violation of an approved architecture spec.

If it does, correct the system-level condition rather than waiting for the next page or workflow to expose it again.

Do not turn every bug into an unnecessary redesign. But do not repeatedly patch symptoms of the same architectural defect.

---

# 6. Completion Rule — End-to-End Verification

A task is not complete merely because code was written or one test passed.

For production-affecting changes, completion means the relevant end-to-end path has been verified as far as the available environment allows.

Examples:

- A live-market fix is not complete until a fresh market artifact is actually produced and consumed correctly downstream.
- A settlement fix is not complete until completed matches settle and Results/Performance update from the resulting canonical artifact.
- A UI fix is not complete if the UI still depends on a broken hidden production path.
- A workflow fix is not complete if it creates excessive recurring Actions usage or another duplicate trigger.
- A model-policy change is not complete until it has appropriate out-of-sample validation and performance reporting.

If a required external dependency prevents full verification, say exactly what remains unverified. Do not claim completion prematurely.

---

# 7. Four Work Categories

Before substantial work, classify it into one or more of these categories:

1. **Production Reliability** — data, workflows, freshness, automation, settlement, canonical artifacts, uptime, recovery.
2. **Model Profitability** — predictive modeling, calibration, selection policy, walk-forward validation, market pricing, performance measurement.
3. **Product UX** — customer-facing Today, Match Detail, Performance, Model Health, mobile usability, subscription-ready presentation.
4. **Research** — diagnostics, experiments, candidate models, historical analysis, non-production investigations.

Production Reliability and Model Profitability are the gating categories for the MVP. Product UX becomes increasingly important once those foundations are trustworthy. Research must not consume production resources or silently alter the live system.

---

# 8. Anti-Drift Check

After any meaningful cluster of changes, explicitly evaluate:

1. **Did this reduce or preserve low manual intervention?**
2. **Did this preserve one canonical source of truth?**
3. **Did this improve or preserve statistical validity?**
4. **Did this move the project toward a proven, sellable MVP?**

If the answer to one of these is no, the work should be reconsidered before additional complexity is built on top of it.

---

# 9. Operating Behavior for the Assistant / Engineering Agent

When working on Tennis Quant Lab V5:

- Read this mandate before making meaningful architecture/model/production decisions.
- Read the relevant approved spec(s) in `docs/superpowers/specs/` before changing behavior governed by them.
- Read the relevant plan(s) in `docs/superpowers/plans/` before continuing previously planned implementation work.
- Prefer execution and concrete outputs over repeated proposals.
- Do not wait for a new prompt between obvious approved implementation steps unless a real user decision is required.
- Do not reactively swing the model toward favorites, underdogs, overs, unders, or any other market because of recent outcomes.
- Do not introduce a second production source of truth as a convenience workaround.
- Do not claim that something is fixed without verification evidence.
- Do not optimize a local component in a way that makes the complete product less reliable or less statistically defensible.
- Preserve historical auditability.
- Keep the long-term target visible: **hands-off operation + durable edge + sellable MVP**.

---

# 10. Definition of Success

The project is moving in the correct direction when:

- the user can open the app on an ordinary day and current production data is already there;
- external outages are handled automatically and transparently rather than causing cascading manual failures;
- official recommendations come from one frozen, auditable pipeline;
- Results and Performance update automatically and accurately;
- the recommendation policy has demonstrated durable out-of-sample value under realistic market pricing;
- the performance page communicates both strengths and weaknesses honestly;
- and the customer-facing app is progressively becoming something useful enough to charge for.

The project is **not** successful merely because the repository has sophisticated code, many diagnostics, or a visually attractive interface.

The governing outcome is:

> **A self-sufficient tennis analytics product that reliably produces statistically defensible recommendations with demonstrated long-run market value and can mature into a paid MVP.**

---

# Reusable Calibration Instruction

When starting or resuming work, use this instruction:

> Before doing any Tennis Quant Lab V5 work, read `PROJECT_MANDATE.md` and the relevant approved documents in `docs/superpowers/specs/` and `docs/superpowers/plans/`. Treat the mandate as the highest-level acceptance contract. Classify the task as Production Reliability, Model Profitability, Product UX, and/or Research. Then execute the work in a way that preserves one source of truth, hands-off daily operation, rigorous out-of-sample profitability validation, and forward progress toward a sellable MVP. Do not solve a local problem in a way that violates the overall architecture. Do not stop at advice when the next implementation step is already approved, and do not call the work complete without relevant end-to-end verification.