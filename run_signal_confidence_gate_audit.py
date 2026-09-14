from __future__ import annotations

import numpy as np

import diagnose_signal_confidence_gate as audit


def _holdout_stability(frame, candidate: float, baseline: float = audit.CURRENT_THRESHOLD) -> list[dict]:
    """Pandas-3-safe chronological block splitter for the audit runner."""
    if frame.empty:
        return []
    fixture_times = (
        frame.groupby("fixture_id", as_index=False)["_analysis_time"]
        .min()
        .sort_values("_analysis_time", kind="stable")
        .reset_index(drop=True)
    )
    position_chunks = np.array_split(np.arange(len(fixture_times)), 3)
    out = []
    for i, positions in enumerate(position_chunks, 1):
        chunk = fixture_times.iloc[positions]
        ids = set(chunk["fixture_id"].astype(str))
        part = frame[frame["fixture_id"].astype(str).isin(ids)]
        cand = audit.policy_metrics(audit.select_fixture_actions(part, candidate), universe_fixtures=len(ids))
        base = audit.policy_metrics(audit.select_fixture_actions(part, baseline), universe_fixtures=len(ids))
        out.append({
            "block": i,
            "fixtures": len(ids),
            "candidate_units": cand["net_units"],
            "baseline_units": base["net_units"],
            "delta_units": cand["net_units"] - base["net_units"],
        })
    return out


def main() -> int:
    audit._holdout_stability = _holdout_stability
    return audit.main()


if __name__ == "__main__":
    raise SystemExit(main())
