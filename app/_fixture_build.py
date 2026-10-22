from pathlib import Path
import re

html = Path("templates/index.html").read_text(encoding="utf-8")
html = re.sub(
    r"\{\{ url_for\('static', filename='([^']+)'\) \}\}\?v=\{\{ version \}\}-ui57",
    r"static/\1",
    html,
)
html = html.replace("{{ version }}", "1")
if "{{" in html:
    raise SystemExit("jinja left in fixture")
Path("tmp-layout-check.html").write_text(html, encoding="utf-8")
print("wrote", len(html))
