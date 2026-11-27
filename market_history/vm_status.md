# Server status, 2026-11-27T08:32:06+00:00

Code: `09aab63 feat: paper tracker for registration 2026-11-21 (order-book wall on Kalshi tennis, scored on CLV)`  
Disk free: 31.0 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `526 passed, 7 skipped in 83.60s (0:01:23)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-21 | 18111 | 33 |
| 2026-11-22 | 47484 | 91 |
| 2026-11-23 | 51065 | 87 |
| 2026-11-24 | 73208 | 91 |
| 2026-11-25 | 50848 | 48 |
| 2026-11-26 | 24452 | 38 |
| 2026-11-27 | 5732 | 12 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| inplay_breaker_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 64 |
| inplay_fade_2026-11-18 | running | 171 / 300 | -4.444 | [-9.737, 1.696] | 171 scored |
| inplay_maker_2026-11-19 | running | 159 / 300 | -1.726 | [-3.638, 0.137] | 159 scored matches; -1.726c per contract |
| inplay_serve_out_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 133 |
| kalshi_blend_2026-11-04 | running | 11 / 300 | -1.359 | [-2.98, 0.083] | P&L -5.045c on 11 settled; 5 of 11 clear on signals alone |
| longshot_2026-11-03 | running | 287 / 300 | -1.673 | [-5.797, 1.996] | favourite won 0.8641 |
| season_end_2026-11-03 | running | 68 / 300 | 2.695 | [-8.178, 13.296] | favourite won 0.5 |
| wall_2026-11-21 | running | 45 / 300 | -1.219 | [-2.084, -0.242] | beat the close 0.4; P&L 3.003c |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 2590 | 9452 | -70.09 | -70.09 | -226.28 |
| 0.05 | 2590 | 3028 | -98.25 | -98.25 | -194.59 |
| join | 2590 | 315575 | -4413.52 | -4413.52 | -975.59 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 2590, contracts 9452, marked $-226.28, held $-70.09
h=0.05: markets 2590, contracts 3028, marked $-194.59, held $-98.25
h=join: markets 2590, contracts 315575, marked $-975.59, held $-4413.52
```
