# Server status, 2026-11-19T07:59:19+00:00

Code: `6a8d7b6 feat: paper tracker for registration 2026-11-18 (in-play rules: fade the favourite, WTA serve-out, WTA breaker)`  
Disk free: 31.1 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `520 passed, 7 skipped in 81.69s (0:01:21)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-13 | 23936 | 35 |
| 2026-11-14 | 12867 | 22 |
| 2026-11-15 | 56529 | 91 |
| 2026-11-16 | 47898 | 75 |
| 2026-11-17 | 48520 | 80 |
| 2026-11-18 | 31211 | 48 |
| 2026-11-19 | 7993 | 15 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| inplay_breaker_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 3 |
| inplay_fade_2026-11-18 | running | 2 / 300 | -24.23 | [-28.38, -20.08] | 2 scored |
| inplay_serve_out_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 3 |
| kalshi_blend_2026-11-04 | running | 10 / 300 | -1.6 | [-3.544, -0.054] | P&L 1.696c on 10 settled; 5 of 10 clear on signals alone |
| longshot_2026-11-03 | running | 158 / 300 | -2.414 | [-7.986, 2.887] | favourite won 0.8481 |
| season_end_2026-11-03 | running | 66 / 300 | 0.994 | [-9.616, 11.61] | favourite won 0.4848 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 1864 | 4479 | 144.38 | 130.64 | 41.98 |
| 0.05 | 1864 | 795 | 58.19 | 55.95 | 22.48 |
| join | 1864 | 208134 | -614.51 | -1359.36 | -370.32 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 1864, contracts 4479, marked $41.98, held $144.38
h=0.05: markets 1864, contracts 795, marked $22.48, held $58.19
h=join: markets 1864, contracts 208134, marked $-370.32, held $-614.51
```
