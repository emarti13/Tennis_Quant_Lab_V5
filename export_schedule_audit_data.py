from pathlib import Path
import pandas as pd

OUT = Path('schedule_audit_export')
OUT.mkdir(exist_ok=True)

matches = pd.read_parquet('context_warehouse/matches.parquet')
# Keep the exact target universe used by the schedule forward ablation: 2025-2026.
date_col = 'match_date' if 'match_date' in matches.columns else 'match_start'
dates = pd.to_datetime(matches[date_col], errors='coerce')
target = matches.loc[dates.dt.year.isin([2025, 2026])].copy()
target.insert(0, 'audit_row', range(1, len(target) + 1))
target.to_csv(OUT / 'warehouse_matches_2025_2026.csv', index=False)

schedule = pd.read_csv('context_registry/tennis_master_schedule.csv', low_memory=False)
schedule.to_csv(OUT / 'tennis_master_schedule.csv', index=False)

print({'warehouse_rows': len(target), 'schedule_rows': len(schedule), 'date_column': date_col})
