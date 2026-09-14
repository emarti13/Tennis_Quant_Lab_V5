# Court Conditions Source Amendment

Date: 2026-09-13
Status: User-approved amendment to `2026-09-13-surface-environment-speed-controls-design.md`
Repository: Tennis_Quant_Lab_V5

## Purpose

Add a source-agnostic court-conditions layer that can ingest the current CourtSpeed dataset immediately and later swap or supplement upstream providers without changing downstream model/UI contracts.

## Canonical condition contract

Each tournament-year condition record may expose:

- `surface_type`: Hard / Clay / Grass
- `environment`: Indoor / Outdoor / Unknown
- `cpi`
- `ace_rate_pct`
- `rally_length`
- `relative_air_density`
- `altitude_m`
- `ball_type`
- `overall_speed_rating`
- `source_name`
- `source_updated_at`
- `source_quality`

The downstream model must consume canonical field names, never provider-specific names.

## Source policy

For the first implementation, CourtSpeed is an allowed source adapter and snapshot source. The adapter boundary must permit later replacement with official ATP/TennisTV CPI, Tennis Abstract ace-rate data, tournament/ball data, Open-Meteo, or another licensed source without changing the simulation/control interface.

The production app must not scrape CourtSpeed during Streamlit page loads. Source data is persisted locally as a versioned snapshot and loaded from the repository/artifact path. A future scheduled refresh may replace the snapshot after source/licensing decisions are finalized.

## Model semantics

Surface Type, Environment, and Court Speed remain the three primary editable playing-condition controls.

CPI, ace rate, rally length, air density, altitude, and ball type are supporting condition inputs. They are not silently collapsed into a new synthetic surface category.

The accepted `court_speed_blended` internal scale is not the same numeric scale as CPI. Raw CPI must therefore remain a separate feature/metadata field until an explicitly validated transform maps external measurements into the accepted court-speed state. Do not assign CPI directly to `court_speed_blended`.

Existing opponent-adjusted, leak-safe current-event court-speed observations remain in place. External tournament-year conditions provide a historical/structural prior and descriptive context; live/current-event evidence may update that prior only under pre-match leakage rules.

## Immediate integration scope

The first implementation must:

1. Add a canonical `v5_court_conditions_source.py` loader/lookup layer.
2. Add a versioned repository snapshot with CourtSpeed-derived tournament-year fields for currently covered events.
3. Normalize tournament aliases and select the requested year, with nearest-prior-year fallback when the target year has not yet been played or a metric is unavailable.
4. Return field-level provenance so a 2026 fixture may legitimately use a 2025 CPI/ball prior without pretending it is a 2026 observation.
5. Expose the external condition fields to the effective simulation context and diagnostics.
6. Keep unknown events on the existing V5 court-speed/weather fallback path.
7. Preserve existing official production model probabilities unless a downstream feature is already part of the accepted model contract; new CPI/ace/rally/ball coefficients remain gated by walk-forward validation.

## Manual simulation controls

The Advanced / Simulation Precision editor should show the canonical inferred values and allow scenario overrides for:

- Surface Type
- Environment
- Court Speed (existing internal numeric court-speed scale)
- CPI
- Ace Rate %
- Rally Length
- Relative Air Density / altitude where applicable
- Ball Type

Only controls already connected to accepted model features may affect official model math immediately. Additional CPI/ace/rally/ball effects may be used in research/scenario analysis until promoted by chronological out-of-sample evidence.

## Indoor handling

Indoor tournament records must set `environment=Indoor`. Outdoor weather exposure is inapplicable for indoor matches; altitude and indoor venue metadata may remain descriptive/structural. Outdoor weather fields must not be injected into indoor simulations as exposed-play conditions.

## Fallback hierarchy

For an exact tournament/year lookup:

1. exact event + target year metric;
2. same event nearest prior year metric;
3. existing V5 same-event historical/current-event court-speed architecture;
4. existing tour/surface/environment fallback.

Fallback is metric-specific. A record may use current-year ball data and prior-year CPI if that is the best information available. Provenance must record each metric's effective source year.

## Testing contract

Tests must prove:

- event aliases normalize consistently;
- exact-year values win over prior-year values;
- prior-year fallback never looks forward;
- Indoor/Outdoor remains independent from surface;
- raw CPI is not assigned directly to `court_speed_blended`;
- metric provenance records the effective year;
- missing events safely return an empty/unknown condition record;
- manual condition overrides do not mutate the persisted source snapshot;
- external fields can be attached to the simulation context without creating a second prediction engine;
- no network call is required during normal UI/model execution.

## Mandate alignment

This amendment preserves one source of truth by introducing one canonical court-condition contract, preserves hands-off production by using a persisted snapshot, preserves statistical validity by separating raw external measurements from validated model effects, and improves the sellable MVP by making match conditions inspectable and editable without tying the product permanently to one provider.