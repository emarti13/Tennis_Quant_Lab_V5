# Server status, 2026-11-24T08:23:16+00:00

Code: `09aab63 feat: paper tracker for registration 2026-11-21 (order-book wall on Kalshi tennis, scored on CLV)`  
Disk free: 31.0 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active  
Live logger command: `/home/ubuntu/tql/.venv/bin/python scripts/log_kalshi_live.py --minutes 1440 --interval 10`  
Live polling gap (median seconds between a match's rows, latest day): 10

Tests (pass): `526 passed, 7 skipped in 85.99s (0:01:25)`

## Problems

- none

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-11-18 | 31211 | 48 |
| 2026-11-19 | 23890 | 39 |
| 2026-11-20 | 25736 | 40 |
| 2026-11-21 | 18111 | 33 |
| 2026-11-22 | 47484 | 91 |
| 2026-11-23 | 51065 | 87 |
| 2026-11-24 | 15687 | 30 |

## Registered forward tests (paper)

| test | status | settled / needed | cents per contract | 95% range | note |
|---|---|---|---|---|---|
| inplay_breaker_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 37 |
| inplay_fade_2026-11-18 | running | 99 / 300 | -3.309 | [-10.886, 5.051] | 99 scored |
| inplay_maker_2026-11-19 | running | 90 / 300 | -1.739 | [-4.177, 0.479] | 90 scored matches; -1.739c per contract |
| inplay_serve_out_2026-11-18 | running | 0 / 300 |  |  | 0 scored; other tours 80 |
| kalshi_blend_2026-11-04 | running | 11 / 300 | -1.359 | [-2.98, 0.083] | P&L -5.045c on 11 settled; 5 of 11 clear on signals alone |
| longshot_2026-11-03 | running | 248 / 300 | -1.968 | [-6.274, 1.921] | favourite won 0.8629 |
| season_end_2026-11-03 | running | 68 / 300 | 2.695 | [-8.178, 13.296] | favourite won 0.5 |
| wall_2026-11-21 | running | 23 / 300 | -1.154 | [-2.378, 0.256] | beat the close 0.478; P&L 12.777c |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 2326 | 8081 | -222.33 | -222.33 | -214.29 |
| 0.05 | 2326 | 2521 | -241.49 | -241.49 | -192.83 |
| join | 2326 | 282876 | -3966.49 | -3966.49 | -726.13 |

run_failures.log: 1 lines

Settle output:
```
h=0.03: markets 2326, contracts 8081, marked $-214.29, held $-222.33
h=0.05: markets 2326, contracts 2521, marked $-192.83, held $-241.49
h=join: markets 2326, contracts 282876, marked $-726.13, held $-3966.49
```
