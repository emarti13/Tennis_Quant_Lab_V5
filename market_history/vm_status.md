# Server status, 2026-11-03T01:54:30+00:00

Code: `9c44f46 fix: server scripts run as one function so a self-update cannot corrupt the run`  
Disk free: 33.3 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 31

Tests (pass): `494 passed, 7 skipped in 81.35s (0:01:21)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-10-31 | 10237 | 47 |
| 2026-11-01 | 18593 | 92 |
| 2026-11-02 | 13928 | 67 |
| 2026-11-03 | 441 | 5 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 450 | 768 | 84.17 | 81.63 | 1.62 |
| 0.05 | 450 | 86 | 23.85 | 23.52 | 1.16 |
| join | 450 | 24156 | 1216.29 | 1133.71 | -27.85 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 450, contracts 768, marked $1.62, held $84.17
h=0.05: markets 450, contracts 86, marked $1.16, held $23.85
h=join: markets 450, contracts 24156, marked $-27.85, held $1216.29
```
