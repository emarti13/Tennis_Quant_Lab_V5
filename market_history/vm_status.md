# Server status, 2026-11-28T08:31:05+00:00

Code: `09aab63 feat: paper tracker for registration 2026-11-21 (order-book wall on Kalshi tennis, scored on CLV)`  
Disk free: 31.0 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `526 passed, 7 skipped in 79.68s (0:01:19)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-22 | 47484 | 91 |
| 2026-11-23 | 51065 | 87 |
| 2026-11-24 | 73208 | 91 |
| 2026-11-25 | 50848 | 48 |
| 2026-11-26 | 24452 | 38 |
| 2026-11-27 | 23403 | 34 |
| 2026-11-28 | 3773 | 7 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| inplay_breaker_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 67 |
| inplay_fade_2026-11-18 | running | 187 / 300 | -4.583 | [-9.774, 1.227] | 187 scored |
| inplay_maker_2026-11-19 | running | 170 / 300 | -1.948 | [-3.83, -0.164] | 170 scored matches; -1.948c per contract |
| inplay_serve_out_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 144 |
| kalshi_blend_2026-11-04 | running | 11 / 300 | -1.359 | [-2.98, 0.083] | P&L -5.045c on 11 settled; 5 of 11 clear on signals alone |
| longshot_2026-11-03 | running | 291 / 300 | -1.473 | [-5.182, 2.4] | favourite won 0.866 |
| season_end_2026-11-03 | running | 68 / 300 | 2.695 | [-8.178, 13.296] | favourite won 0.5 |
| wall_2026-11-21 | running | 47 / 300 | -1.107 | [-1.951, -0.1] | beat the close 0.426; P&L 1.361c |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 2638 | 9509 | -48.43 | -48.43 | -227.99 |
| 0.05 | 2638 | 3028 | -98.25 | -98.25 | -194.59 |
| join | 2638 | 323924 | -3772.13 | -3772.13 | -987.44 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 2638, contracts 9509, marked $-227.99, held $-48.43
h=0.05: markets 2638, contracts 3028, marked $-194.59, held $-98.25
h=join: markets 2638, contracts 323924, marked $-987.44, held $-3772.13
```
