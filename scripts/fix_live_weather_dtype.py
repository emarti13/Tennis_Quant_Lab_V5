from pathlib import Path

path = Path("v5_weather_features.py")
text = path.read_text(encoding="utf-8")
needle = '''    for target, source in mapping.items():\n        if target not in df.columns:\n            df[target] = np.nan if target not in {"weather_source_quality", "weather_forecast_hour"} else ""\n        df.loc[mask, target] = df.loc[mask, "match_id"].map(lambda match_id: values_by_match.get(match_id, {}).get(source, np.nan))\n'''
replacement = '''    text_targets = {"weather_source_quality", "weather_forecast_hour"}\n    for target, source in mapping.items():\n        if target not in df.columns:\n            df[target] = "" if target in text_targets else np.nan\n        elif target in text_targets and not (pd.api.types.is_object_dtype(df[target].dtype) or pd.api.types.is_string_dtype(df[target].dtype)):\n            # Historical all-null metadata can be read from parquet as float64.\n            # Cast only text metadata before assigning live source labels under Pandas 3.\n            df[target] = df[target].astype("object")\n        df.loc[mask, target] = df.loc[mask, "match_id"].map(lambda match_id: values_by_match.get(match_id, {}).get(source, np.nan))\n'''
if needle not in text:
    raise SystemExit("weather assignment block not found")
path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
print("Applied Pandas-3-safe live weather metadata assignment")
