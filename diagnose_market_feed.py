
from pathlib import Path
import pandas as pd
from v5_live_market import load_market_board, market_feed_status, canonical_name

print("STATUS")
print(market_feed_status())
df=load_market_board()
print("ROWS",len(df))
print("SOURCE",df.attrs.get("source_path") if not df.empty else None)

for target in ("Dougaz", "Guerrieri"):
    if not df.empty:
        m = df[
            df["player1"].astype(str).str.contains(target, case=False, na=False)
            | df["player2"].astype(str).str.contains(target, case=False, na=False)
        ]
        print(target, len(m))
        if len(m):
            print(m[["player1","player2","market_group","selection","best_bookmaker","best_american_odds"]].to_string(index=False))
