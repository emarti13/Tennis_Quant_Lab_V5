# Server status, 2026-11-01T07:18:27+00:00

Code: `1b82d32 feat: live logger also records every open Kalshi tennis quote every 5 minutes`  
Disk free: 33.4 GB  
Services: tql-paper active, tql-live active, tql-daily.timer active

Tests (pass): `492 passed, 7 skipped, 12 warnings in 70.54s (0:01:10)`

## Problems

- settle failed: TypeError: Can only string multiply by an integer.

## Live score log (last 7 days)

| day | rows | matches |
|---|---|---|
| 2026-10-31 | 10237 | 47 |
| 2026-11-01 | 2238 | 15 |

## Paper market-making (settled markets)

| setting | markets | contracts | held $ | held after fee $ | marked $ |
|---|---|---|---|---|---|
| 0.03 | 142 | 282 | -27.32 | -28.38 | 4.39 |
| 0.05 | 142 | 54 | 30.15 | 29.92 | 0.44 |
| join | 142 | 2981 | 144.05 | 133.86 | 3.79 |

run_failures.log: 1 lines

Settle output:
```
  File "/home/ubuntu/tql/scripts/paper_trade_kalshi.py", line 382, in <module>
    raise SystemExit(main())
  File "/home/ubuntu/tql/scripts/paper_trade_kalshi.py", line 359, in main
    out = settle(api)
  File "/home/ubuntu/tql/scripts/paper_trade_kalshi.py", line 337, in settle
    "end_position": float((f["contracts"] * f["side"].map({"buy": 1, "sell": -1})).sum())}
TypeError: Can only string multiply by an integer.
```
