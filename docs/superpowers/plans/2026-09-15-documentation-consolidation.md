# 2026-09-15 Documentation Consolidation

## Goal

Prevent future engineering sessions from regressing Tennis Quant Lab V5 by treating older dated plans/specs as the current implementation after later architecture changes.

## Changes in this consolidation

- Added `CURRENT_ARCHITECTURE.md` as the authoritative current-state bridge below `PROJECT_MANDATE.md`.
- Added `SUPERSESSION_MAP.md` to map common older assumptions to current rules.
- Added `ARCHITECTURE_CHANGELOG.md` for compact architecture history.
- Added `CURRENT_PRODUCTION_STATUS.md` to separate implemented/CI-verified behavior from live production verification.
- Added `READ_BEFORE_WORK.md` as a short mandatory pre-work checklist.
- Added `specs/2026-09-15-current-production-architecture.md` as the current consolidation spec.
- Added `specs/DEPRECATED_BEHAVIOR.md` to make superseded behavior explicit.
- Added `plans/2026-09-15-current-state-handoff.md` as the resume point.
- Added README files to specs/plans and updated the Superpowers root README so every path directs future agents through current architecture first.

## Rule going forward

Architectural documentation maintenance is part of completion. When a merged change alters the architecture, update the current-state contract and changelog in the same workstream. Historical documents may remain intact for traceability; they no longer need to be rewritten to pretend they were authored with future changes already known.

This approach preserves history while making the current architecture unambiguous.