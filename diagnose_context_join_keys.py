from __future__ import annotations

import json
import pandas as pd

from build_v5_context_warehouse import load_tennismylife_history, normalize_results
from build_v5_context_matchups import load_walkforward
from v5_settlement import canonical_name


def main() -> int:
    raw, _ = load_tennismylife_history(years=(2025, 2026))
    matches = normalize_results(raw)
    wf = load_walkforward('.')

    matches = matches[matches['match_date'].dt.year.isin([2025, 2026])].copy()
    wf['date'] = pd.to_datetime(wf['date'], errors='coerce').dt.normalize()
    wf = wf[wf['date'].dt.year.isin([2025, 2026])].copy()

    matches['wkey'] = matches['winner_name'].map(canonical_name)
    matches['lkey'] = matches['loser_name'].map(canonical_name)
    matches['pair'] = list(zip(matches['wkey'], matches['lkey']))
    matches['rpair'] = list(zip(matches['lkey'], matches['wkey']))
    matches['dkey'] = matches['match_date'].dt.normalize()

    winner_col = 'winner' if 'winner' in wf.columns else 'winner_name'
    loser_col = 'loser' if 'loser' in wf.columns else 'loser_name'
    wf['wkey'] = wf[winner_col].map(canonical_name)
    wf['lkey'] = wf[loser_col].map(canonical_name)
    wf['pair'] = list(zip(wf['wkey'], wf['lkey']))
    wf['rpair'] = list(zip(wf['lkey'], wf['wkey']))

    m_exact = set(zip(matches['dkey'], matches['tour'], matches['wkey'], matches['lkey']))
    w_exact = set(zip(wf['date'], wf['tour'], wf['wkey'], wf['lkey']))
    pair_matches = set(matches['pair'])
    pair_wf = set(wf['pair'])
    reverse_overlap = set(matches['pair']) & set(wf['rpair'])

    # For shared oriented pairs, inspect nearest date differences.
    by_pair = {p: g['dkey'].sort_values().tolist() for p, g in matches.groupby('pair', sort=False)}
    deltas = []
    examples = []
    for _, row in wf.iterrows():
        dates = by_pair.get(row['pair'])
        if not dates:
            continue
        target = row['date']
        nearest = min(dates, key=lambda d: abs((d-target).days))
        delta = int((target-nearest).days)
        deltas.append(delta)
        if len(examples) < 20 and delta != 0:
            examples.append({
                'wf_date': str(target.date()), 'result_date': str(nearest.date()), 'delta_days': delta,
                'winner': str(row[winner_col]), 'loser': str(row[loser_col]), 'tour': str(row['tour'])
            })

    report = {
        'result_rows': int(len(matches)),
        'walkforward_rows': int(len(wf)),
        'exact_key_overlap': int(len(m_exact & w_exact)),
        'oriented_pair_overlap': int(len(pair_matches & pair_wf)),
        'reverse_pair_overlap': int(len(reverse_overlap)),
        'date_delta_counts_for_oriented_pair_matches': {str(k): int(v) for k, v in pd.Series(deltas).value_counts().sort_index().to_dict().items()},
        'nonzero_delta_examples': examples,
        'result_sample': matches[['match_date','tour','winner_name','loser_name']].head(5).astype(str).to_dict('records'),
        'walkforward_sample': wf[['date','tour',winner_col,loser_col]].head(5).astype(str).to_dict('records'),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
