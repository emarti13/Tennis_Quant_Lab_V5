# Server status, 2026-11-23T08:19:33+00:00

Code: `09aab63 feat: paper tracker for registration 2026-11-21 (order-book wall on Kalshi tennis, scored on CLV)`  
Disk free: 31.1 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `526 passed, 7 skipped in 83.17s (0:01:23)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-17 | 48520 | 80 |
| 2026-11-18 | 31211 | 48 |
| 2026-11-19 | 23890 | 39 |
| 2026-11-20 | 25736 | 40 |
| 2026-11-21 | 18111 | 33 |
| 2026-11-22 | 47484 | 91 |
| 2026-11-23 | 13520 | 28 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| inplay_breaker_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 26 |
| inplay_fade_2026-11-18 | running | 70 / 300 | -3.689 | [-13.168, 6.7] | 70 scored |
| inplay_maker_2026-11-19 | running | 63 / 300 | -2.159 | [-6.006, 1.369] | 63 scored matches; -2.159c per contract |
| inplay_serve_out_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 56 |
| kalshi_blend_2026-11-04 | running | 11 / 300 | -1.359 | [-2.98, 0.083] | P&L -5.045c on 11 settled; 5 of 11 clear on signals alone |
| longshot_2026-11-03 | running | 218 / 300 | -2.453 | [-7.467, 1.947] | favourite won 0.8578 |
| season_end_2026-11-03 | running | 68 / 300 | 2.695 | [-8.178, 13.296] | favourite won 0.5 |
| wall_2026-11-21 | running | 12 / 300 | -1.4 | [-3.128, 1.23] | beat the close 0.417; P&L 26.182c |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 2178 | 7841 | -262.33 | -262.33 | -217.34 |
| 0.05 | 2178 | 2457 | -261.51 | -261.51 | -192.19 |
| join | 2178 | 262980 | -3135.04 | -3135.04 | -653.94 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 2178, contracts 7841, marked $-217.34, held $-262.33
h=0.05: markets 2178, contracts 2457, marked $-192.19, held $-261.51
h=join: markets 2178, contracts 262980, marked $-653.94, held $-3135.04
```
