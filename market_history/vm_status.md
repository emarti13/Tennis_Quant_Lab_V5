# Server status, 2026-11-03T07:25:00+00:00

Code: `adaf98f feat: paper tracker for registration 2026-11-03 (season end: back the opponent of a player ranked 31-90)`  
Disk free: 33.3 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 31

Tests (pass): `501 passed, 7 skipped in 80.17s (0:01:20)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-10-31 | 10237 | 47 |
| 2026-11-01 | 18593 | 92 |
| 2026-11-02 | 13928 | 67 |
| 2026-11-03 | 2664 | 16 |

## Registered forward tests (paper)

none yet

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 460 | 799 | 97.60 | 94.96 | 0.88 |
| 0.05 | 460 | 86 | 23.85 | 23.52 | 1.16 |
| join | 460 | 26134 | 1524.49 | 1434.78 | -36.25 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 460, contracts 799, marked $0.88, held $97.60
h=0.05: markets 460, contracts 86, marked $1.16, held $23.85
h=join: markets 460, contracts 26134, marked $-36.25, held $1524.49
```
