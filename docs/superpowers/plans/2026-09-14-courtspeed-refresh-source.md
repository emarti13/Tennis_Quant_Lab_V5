# CourtSpeed Refresh / Primary Conditions Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CourtSpeed the automatically refreshed primary court-conditions source, with field-level V5 fallback, explicit freshness/provenance, last-known-good protection, and no live Streamlit dependency.

**Architecture:** Add one isolated CourtSpeed fetch/parse layer, one deterministic snapshot merge/resolution layer, and one lightweight scheduled workflow that runs before the daily production forecast. Downstream model/context code consumes a provider-agnostic resolved condition record; CourtSpeed-specific parsing stays outside model/UI logic and accepted probability math remains unchanged unless separately OOS-promoted.

**Tech Stack:** Python 3.12, pandas, requests/stdlib HTTP as already available in the repo, pytest, GitHub Actions YAML.

**Spec:** `docs/superpowers/specs/2026-09-14-courtspeed-refresh-source-design.md`

## Global Constraints

- CourtSpeed is primary for published condition evidence; V5 fallback is automatic and field-level.
- One normal CourtSpeed production refresh per day; manual dispatch allowed; no high-frequency polling.
- No CourtSpeed network calls from Streamlit or ordinary CI/unit tests.
- A failed fetch/parse/validation must preserve the last-known-good snapshot unchanged.
- No lookahead: prior-year fallback may only use source years `<= target_year`.
- Do not replace V5 `court_speed_blended` or add new predictive coefficients in this implementation.
- Do not trigger or consume extra OddsPapi calls as part of CourtSpeed refresh.
- Preserve source provider, source year, refreshed timestamp, freshness state, and fallback provenance per resolved field.
- Historical frozen predictions must not be rewritten.

---

### Task 1: Deterministic CourtSpeed fetch/parse contract

**Files:**
- Create: `v5_courtspeed_fetch.py`
- Create: `tests/fixtures/courtspeed_event_page.html`
- Create: `tests/test_v5_courtspeed_fetch.py`

**Interfaces:**
- Consumes: CourtSpeed HTTP response text only in production fetch mode.
- Produces: `parse_courtspeed_payload(text: str, *, fetched_at_utc: str) -> pd.DataFrame`, `fetch_courtspeed_snapshot(url: str, *, timeout_seconds: int = 20) -> pd.DataFrame`.

- [ ] **Step 1: Write parser tests against a static fixture**

```python
from pathlib import Path
from v5_courtspeed_fetch import parse_courtspeed_payload


def test_parser_extracts_supported_condition_fields_without_network():
    html = Path("tests/fixtures/courtspeed_event_page.html").read_text(encoding="utf-8")
    out = parse_courtspeed_payload(html, fetched_at_utc="2026-09-14T04:00:00+00:00")
    row = out.iloc[0]
    assert row["event_key"] == "paris_masters"
    assert row["year"] == 2026
    assert row["surface_type"] == "Hard"
    assert row["environment"] == "Indoor"
    assert row["cpi"] == 40.1
    assert row["ball_type"] == "Head Tour XT"
    assert row["source_name"] == "CourtSpeed"
    assert row["source_refreshed_at"] == "2026-09-14T04:00:00+00:00"
```

- [ ] **Step 2: Run the parser test and verify RED**

Run: `pytest tests/test_v5_courtspeed_fetch.py -v`

Expected: FAIL because `v5_courtspeed_fetch.py` does not exist.

- [ ] **Step 3: Implement minimal isolated parser/fetcher**

```python
# v5_courtspeed_fetch.py
from __future__ import annotations

from io import StringIO
import pandas as pd
import requests

from v5_court_conditions_source import normalize_event_name

SOURCE_NAME = "CourtSpeed"


def parse_courtspeed_payload(text: str, *, fetched_at_utc: str) -> pd.DataFrame:
    # Parse only source-level fields into the canonical snapshot schema.
    # Keep provider-specific selectors/parsing isolated here.
    ...


def fetch_courtspeed_snapshot(url: str, *, timeout_seconds: int = 20) -> pd.DataFrame:
    response = requests.get(url, timeout=timeout_seconds, headers={"User-Agent": "TennisQuantLabV5/1.0"})
    response.raise_for_status()
    return parse_courtspeed_payload(response.text, fetched_at_utc=pd.Timestamp.utcnow().isoformat())
```

Implementation must normalize numeric fields with `pd.to_numeric(..., errors="coerce")`, normalize event names through `normalize_event_name`, reject rows without event/year, and never import Streamlit/model modules.

- [ ] **Step 4: Run parser tests GREEN**

Run: `pytest tests/test_v5_courtspeed_fetch.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add v5_courtspeed_fetch.py tests/fixtures/courtspeed_event_page.html tests/test_v5_courtspeed_fetch.py
git commit -m "Add isolated CourtSpeed fetch parser"
```

---

### Task 2: Last-known-good merge and refresh status

**Files:**
- Create: `v5_refresh_court_conditions.py`
- Modify: `v5_court_conditions_source.py`
- Create: `tests/test_v5_refresh_court_conditions.py`

**Interfaces:**
- Consumes: existing `data/court_conditions/courtspeed_snapshot.csv`, parsed source dataframe.
- Produces: `merge_courtspeed_snapshot(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame`, `refresh_court_conditions(...) -> dict`, status artifact `data/court_conditions/courtspeed_refresh_status.json`.

- [ ] **Step 1: Write merge/LKG failure tests**

```python
def test_partial_refresh_does_not_erase_existing_metric():
    existing = pd.DataFrame([{"event_key":"paris_masters","year":2026,"cpi":40.1,"ball_type":"Head Tour XT"}])
    fresh = pd.DataFrame([{"event_key":"paris_masters","year":2026,"cpi":41.0,"ball_type":None}])
    merged = merge_courtspeed_snapshot(existing, fresh)
    row = merged.iloc[0]
    assert row["cpi"] == 41.0
    assert row["ball_type"] == "Head Tour XT"


def test_refresh_exception_preserves_last_known_good(tmp_path, monkeypatch):
    # Seed snapshot, force fetch exception, run refresh, assert bytes unchanged and status marks retained LKG.
    ...
```

- [ ] **Step 2: Run focused tests RED**

Run: `pytest tests/test_v5_refresh_court_conditions.py -v`

Expected: FAIL because refresh functions are missing.

- [ ] **Step 3: Implement deterministic merge and atomic writes**

Requirements:

```python
KEYS = ["event_key", "year"]
CONDITION_FIELDS = [
    "event_name", "surface_type", "environment", "cpi", "ace_rate_pct",
    "rally_length", "relative_air_density", "altitude_m", "ball_type",
    "overall_speed_rating", "source_name", "source_updated_at", "source_refreshed_at",
]
```

For each `(event_key, year)`, fresh non-null values overwrite existing values; fresh null values never erase existing non-null values. Write a temporary CSV/JSON then `Path.replace()` only after validation succeeds. On exception, do not touch the snapshot; emit status with `last_known_good_retained: true`, `state: "STALE_LKG"` if existing data is still within the permitted age else `state: "FALLBACK_V5"`.

- [ ] **Step 4: Add schema validation**

Reject refresh output if any of these are true:
- duplicate `(event_key, year)` rows;
- missing/blank `event_key`;
- year not numeric;
- `environment` outside `Indoor/Outdoor/Unknown` when present;
- `surface_type` outside `Hard/Clay/Grass` when present;
- empty parsed result when an existing non-empty snapshot exists.

- [ ] **Step 5: Run tests GREEN**

Run: `pytest tests/test_v5_refresh_court_conditions.py tests/test_v5_court_conditions_source.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add v5_refresh_court_conditions.py v5_court_conditions_source.py tests/test_v5_refresh_court_conditions.py
git commit -m "Add CourtSpeed last-known-good refresh"
```

---

### Task 3: Field-level freshness and V5 fallback resolver

**Files:**
- Modify: `v5_court_conditions_source.py`
- Create: `tests/test_v5_court_conditions_resolution.py`

**Interfaces:**
- Consumes: CourtSpeed snapshot row, refresh status, V5 fallback condition dict.
- Produces: `resolve_court_conditions(tournament: str, year: int, *, v5_fallback: dict, now_utc: str | None = None, max_source_age_hours: int = 72, snapshot: pd.DataFrame | None = None, refresh_status: dict | None = None) -> dict`.

- [ ] **Step 1: Write precedence/freshness tests**

```python
def test_exact_year_courtspeed_outranks_v5():
    resolved = resolve_court_conditions(...)
    assert resolved["cpi"] == 40.1
    assert resolved["cpi_source"] == "CourtSpeed"


def test_missing_courtspeed_field_falls_only_that_field_to_v5():
    resolved = resolve_court_conditions(...)
    assert resolved["cpi_source"] == "CourtSpeed"
    assert resolved["altitude_source"] == "V5"


def test_stale_courtspeed_field_falls_to_v5():
    resolved = resolve_court_conditions(..., max_source_age_hours=72)
    assert resolved["cpi_source"] == "V5"
    assert resolved["source_freshness"] == "FALLBACK_V5"
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_v5_court_conditions_resolution.py -v`

Expected: FAIL because resolver is missing.

- [ ] **Step 3: Implement the field-level resolver**

The resolver must preserve existing no-lookahead lookup behavior, then resolve each field independently in this order: exact-year CourtSpeed, allowed prior-year CourtSpeed, supplied V5 fallback, missing. Each field returns value + provider + source year + fallback flag. The aggregate `source_freshness` is `READY`, `STALE_LKG`, `FALLBACK_V5`, or `MISSING` based on the actual resolved inputs.

- [ ] **Step 4: Run GREEN**

Run: `pytest tests/test_v5_court_conditions_resolution.py tests/test_v5_court_conditions_source.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add v5_court_conditions_source.py tests/test_v5_court_conditions_resolution.py
git commit -m "Resolve CourtSpeed fields with V5 fallback"
```

---

### Task 4: Feed the canonical resolved record into live/daily context

**Files:**
- Modify: `v5_full_context_live.py`
- Modify: `v5_forecast_context.py`
- Modify: `v5_daily_batch.py` only where needed to pass canonical condition fields through the existing fixture contract
- Test: `tests/test_v5_forecast_context.py`
- Create: `tests/test_v5_court_conditions_integration.py`

**Interfaces:**
- Consumes: `resolve_court_conditions(...)` result.
- Produces: one effective condition record in target rows and forecast artifacts; no duplicate source selection downstream.

- [ ] **Step 1: Write integration tests**

```python
def test_daily_context_uses_resolved_condition_record_once():
    # Build a target fixture with CourtSpeed CPI + V5 altitude fallback.
    # Assert the enriched target carries both values and their distinct sources.
    ...


def test_indoor_resolved_environment_suppresses_outdoor_weather():
    # Assert indoor target exposes environment=Indoor and weather applicability prevents exposed-weather features.
    ...
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_v5_court_conditions_integration.py tests/test_v5_forecast_context.py -v`

Expected: FAIL because the canonical resolver is not yet consumed end-to-end.

- [ ] **Step 3: Wire one source-resolution layer**

Add resolved fields to the fixture/target context contract and make `v5_full_context_live.py` read them without re-deciding provider precedence. Keep `court_speed_blended` unchanged as the production model's validated court-speed input. Persist raw CourtSpeed evidence/provenance alongside it.

- [ ] **Step 4: Verify model math unchanged**

Add a regression assertion comparing baseline accepted model probability before/after when only raw CourtSpeed evidence fields are populated but no accepted candidate uses them.

- [ ] **Step 5: Run GREEN**

Run: `pytest tests/test_v5_court_conditions_integration.py tests/test_v5_forecast_context.py tests/test_v5_production_ui_unification.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add v5_full_context_live.py v5_forecast_context.py v5_daily_batch.py tests/test_v5_court_conditions_integration.py tests/test_v5_forecast_context.py
git commit -m "Use resolved court conditions in daily context"
```

---

### Task 5: Scheduled production refresh workflow

**Files:**
- Create: `.github/workflows/courtspeed_conditions_refresh.yml`
- Create: `tests/test_v5_courtspeed_workflow_contract.py`

**Interfaces:**
- Consumes: existing canonical fixture/tournament artifacts for target discovery; production CourtSpeed endpoint from code/config.
- Produces: updated `data/court_conditions/courtspeed_snapshot.csv` and `data/court_conditions/courtspeed_refresh_status.json` committed by the workflow only when changed.

- [ ] **Step 1: Write workflow contract test**

```python
def test_courtspeed_workflow_has_one_daily_schedule_and_manual_dispatch():
    text = Path(".github/workflows/courtspeed_conditions_refresh.yml").read_text()
    assert "workflow_dispatch:" in text
    assert "schedule:" in text
    assert text.count("- cron:") == 1
    assert "v5_refresh_court_conditions.py" in text
    assert "oddspapi" not in text.lower()
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_v5_courtspeed_workflow_contract.py -v`

Expected: FAIL because workflow does not exist.

- [ ] **Step 3: Add lightweight daily workflow**

Use one UTC cron scheduled before the existing forecast/context production window. Workflow steps: checkout, setup Python, install only required dependencies from `requirements.txt`, run `python v5_refresh_court_conditions.py`, run focused validation tests, commit/push only snapshot/status changes. Include `concurrency` so overlapping refreshes cancel/serialize rather than duplicate work.

- [ ] **Step 4: Ensure tests/CI never call the live site**

Workflow contract and parser tests must rely on the static fixture. Only `courtspeed_conditions_refresh.yml` may invoke production fetching.

- [ ] **Step 5: Run GREEN**

Run: `pytest tests/test_v5_courtspeed_workflow_contract.py tests/test_v5_courtspeed_fetch.py tests/test_v5_refresh_court_conditions.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/courtspeed_conditions_refresh.yml tests/test_v5_courtspeed_workflow_contract.py
git commit -m "Schedule daily CourtSpeed conditions refresh"
```

---

### Task 6: Production ordering / freshness gate integration

**Files:**
- Modify: the existing production context/forecast workflow that runs `v5_build_daily_forecast_artifacts.py`
- Modify: `v5_build_daily_forecast_artifacts.py` only if needed for status/freshness consumption
- Create: `tests/test_v5_court_conditions_production_gate.py`

**Interfaces:**
- Consumes: CourtSpeed refresh status and canonical resolved fields.
- Produces: production forecasts that proceed on V5 fallback when CourtSpeed is unavailable, while never presenting stale CourtSpeed as fresh.

- [ ] **Step 1: Write gate tests**

```python
def test_failed_courtspeed_refresh_does_not_block_valid_v5_fallback():
    ...


def test_stale_courtspeed_is_not_labeled_ready_in_forecast_artifact():
    ...
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_v5_court_conditions_production_gate.py -v`

- [ ] **Step 3: Integrate freshness status without adding a second forecast path**

The production chain remains exactly one forecast pipeline. CourtSpeed refresh is upstream evidence preparation; failed CourtSpeed refresh does not trigger OddsPapi or a parallel forecast. If V5 fallback resolves all required condition inputs, forecasting continues and records `FALLBACK_V5`; otherwise the relevant fixture fails closed.

- [ ] **Step 4: Run GREEN**

Run: `pytest tests/test_v5_court_conditions_production_gate.py tests/test_v5_forecast_context.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/<existing-production-workflow>.yml v5_build_daily_forecast_artifacts.py tests/test_v5_court_conditions_production_gate.py
git commit -m "Gate production on resolved court conditions freshness"
```

---

### Task 7: Full verification and anti-drift check

**Files:**
- No new production behavior unless verification exposes a defect.

**Interfaces:**
- Consumes: completed Tasks 1–6.
- Produces: evidence that refresh, fallback, Streamlit isolation, and accepted model behavior satisfy the spec.

- [ ] **Step 1: Run focused CourtSpeed suite**

Run:

```bash
pytest \
  tests/test_v5_courtspeed_fetch.py \
  tests/test_v5_refresh_court_conditions.py \
  tests/test_v5_court_conditions_source.py \
  tests/test_v5_court_conditions_resolution.py \
  tests/test_v5_court_conditions_integration.py \
  tests/test_v5_courtspeed_workflow_contract.py \
  tests/test_v5_court_conditions_production_gate.py -v
```

Expected: 0 failures.

- [ ] **Step 2: Run production/UI regressions**

Run:

```bash
pytest \
  tests/test_v5_forecast_context.py \
  tests/test_v5_production_ui_unification.py \
  tests/test_v5_ui_production_boundary.py \
  tests/test_v5_history_resilience.py \
  tests/test_streamlit_app_smoke.py -v
```

Expected: 0 failures and no network calls from Streamlit tests.

- [ ] **Step 3: Verify source artifacts**

Run a fixture-driven refresh into a temporary directory and confirm:
- exact/prior-year/V5 precedence is correct;
- failed refresh leaves snapshot bytes unchanged;
- status JSON contains timestamp, requested/matched/update counts, unresolved events, LKG flag, freshness, and error summary;
- no frozen prediction file is rewritten by refresh.

- [ ] **Step 4: Verify production workflow ordering**

Inspect the final workflow graph/text and confirm CourtSpeed refresh is upstream of context/forecast, does not trigger OddsPapi, and there is only one normal daily CourtSpeed schedule.

- [ ] **Step 5: Anti-drift check**

Record in the PR/commit review:
1. manual intervention reduced/preserved;
2. one canonical source of truth preserved;
3. statistical validity preserved because model math did not change;
4. paid-MVP direction improved through richer, auditable, resilient conditions data.

- [ ] **Step 6: Final commit if verification required fixes**

```bash
git add <only-files-changed-by-verification-fixes>
git commit -m "Harden CourtSpeed refresh verification"
```
