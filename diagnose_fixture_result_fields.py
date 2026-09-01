from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

PATH = Path("oddspapi_history/fixtures_2026.jsonl")


def flatten_keys(obj, prefix=""):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.append(key)
            out.extend(flatten_keys(v, key))
    elif isinstance(obj, list):
        for v in obj[:3]:
            out.extend(flatten_keys(v, prefix + "[]"))
    return out


def sanitize(obj, depth=0):
    if depth > 4:
        return "..."
    if isinstance(obj, dict):
        return {k: sanitize(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v, depth + 1) for v in obj[:5]]
    if isinstance(obj, str) and len(obj) > 160:
        return obj[:157] + "..."
    return obj


def main():
    key_counts = Counter()
    relevant_key_counts = Counter()
    examples = []
    rows = 0
    with PATH.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            keys = flatten_keys(row)
            key_counts.update(keys)
            relevant = [
                k for k in keys
                if any(term in k.lower() for term in ("score", "result", "set", "period", "winner", "home", "away"))
            ]
            relevant_key_counts.update(relevant)
            if relevant and len(examples) < 3:
                examples.append(sanitize(row))

    print(json.dumps({
        "rows": rows,
        "top_level_and_nested_keys": key_counts.most_common(120),
        "result_like_keys": relevant_key_counts.most_common(120),
        "sample_rows_with_result_like_fields": examples,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
