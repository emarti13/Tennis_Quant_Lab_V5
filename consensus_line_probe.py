"""One-off helper for consensus-line validation.

This file intentionally starts small: it verifies that a separate analysis
entry point can be committed on the isolated walk-forward branch without
changing production code.
"""
from pathlib import Path

if __name__ == "__main__":
    chunks = sorted(Path("oddspapi_history/chunks").glob("history_chunk_*.jsonl.gz"))
    print(f"historical_chunks={len(chunks)}")
