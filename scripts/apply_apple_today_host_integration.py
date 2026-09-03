from pathlib import Path

path = Path("tennis_quant_app_v5.py")
text = path.read_text(encoding="utf-8")

import_line = "from v5_ui_host import run_v5_ui_app\n"
if import_line not in text:
    marker = "BASE = Path(__file__).resolve().parent\n"
    if marker not in text:
        raise SystemExit("BASE marker not found")
    text = text.replace(marker, import_line + "\n" + marker, 1)

app_marker = "\ndef app():\n"
idx = text.rfind(app_marker)
if idx < 0:
    raise SystemExit("app() marker not found")

new_tail = '''\ndef app():
    st.set_page_config(page_title="Tennis Quant Lab V5", layout="wide", page_icon="🎾")
    run_v5_ui_app(st, BASE, globals())


if __name__ == "__main__":
    app()
'''
text = text[:idx] + new_tail
path.write_text(text, encoding="utf-8")
print("Integrated Today-first UI host into tennis_quant_app_v5.py")
