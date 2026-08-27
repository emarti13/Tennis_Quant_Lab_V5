
from __future__ import annotations
import json
from pathlib import Path
from oddspapi_client import OddsPapiClient

OUT = Path("oddspapi_markets_tennis.json")

def main():
    client = OddsPapiClient()
    payload = client.markets()
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected markets response type: {type(payload).__name__}")
    tennis = [m for m in payload if int(m.get("sportId", -1)) == 12]
    OUT.write_text(json.dumps(tennis, indent=2, default=str), encoding="utf-8")
    print(f"Saved {len(tennis)} tennis market definitions -> {OUT}")

if __name__ == "__main__":
    main()
