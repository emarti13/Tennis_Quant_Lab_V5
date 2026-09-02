from __future__ import annotations

from pathlib import Path
import json

import pandas as pd

from v5_production_policy import load_production_config, score_policy


def apply_daily_policy(frame: pd.DataFrame, config: dict) -> pd.DataFrame:
    if frame is None or frame.empty:
        return frame.copy() if frame is not None else pd.DataFrame()
    out = frame.copy()
    enabled = []
    signals = []
    for _, row in out.iterrows():
        group = str(row.get("market_group") or "")
        signal = str(row.get("signal") or "")
        if group in {"game_spread", "total_games"}:
            policy = score_policy(str(row.get("tour_v5") or "MEN"), int(row.get("best_of") or 3), config)
            market_enabled = bool(policy["enabled"])
            if not market_enabled and signal in {"BET", "LEAN"}:
                signal = "REVIEW"
        else:
            market_enabled = True
        enabled.append(market_enabled)
        signals.append(signal)
    out["production_market_enabled"] = enabled
    out["signal"] = signals
    return out


def main(base_dir: str | Path = ".", config_path: str | Path = "v5_production_config.json") -> int:
    base = Path(base_dir)
    config = load_production_config(base / config_path)
    ready = base / "v5_daily_ready"
    targets = [ready / "latest_board.csv", ready / "frozen_predictions.csv"]
    summary = {"updated": [], "missing": []}
    for path in targets:
        if not path.exists():
            summary["missing"].append(str(path))
            continue
        frame = pd.read_csv(path, low_memory=False)
        frame = apply_daily_policy(frame, config)
        frame.to_csv(path, index=False)
        summary["updated"].append(str(path))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
