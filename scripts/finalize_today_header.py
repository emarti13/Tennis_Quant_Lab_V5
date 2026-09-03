from pathlib import Path

path = Path("v5_ui_today.py")
text = path.read_text(encoding="utf-8")
block = '''    st_module.markdown('<div class="v5-eyebrow">Daily slate</div>', unsafe_allow_html=True)\n    st_module.markdown('<div class="v5-title">Today</div>', unsafe_allow_html=True)\n    st_module.markdown(\n        f'<div class="v5-subtitle">{summary["matches_analyzed"]} matches analyzed · refreshed {escape(str(summary["snapshot"]))}</div>',\n        unsafe_allow_html=True,\n    )\n\n'''
replacement = '''    st_module.caption(\n        f'{summary["matches_analyzed"]} matches analyzed · market snapshot {summary["snapshot"]}'\n    )\n\n'''
if block not in text:
    raise SystemExit("Today duplicate-header block not found")
path.write_text(text.replace(block, replacement, 1), encoding="utf-8")
print("Removed duplicate Today heading while retaining analyzed/snapshot context")
