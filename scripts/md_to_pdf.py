"""Render a Markdown file to a clean A4 PDF via Chromium. Usage: python scripts/md_to_pdf.py in.md out.pdf"""
import sys
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
body = markdown.markdown(src.read_text(encoding="utf-8"), extensions=["tables", "fenced_code", "toc"])
html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 18mm 16mm; }}
body {{ font-family: 'Segoe UI','Nirmala UI',system-ui,sans-serif; color:#1d2433; font-size:10.5pt; line-height:1.55; }}
h1 {{ font-size:22pt; margin:0 0 6pt; color:#0b3d6e; }} h2 {{ font-size:14pt; color:#0b3d6e; border-bottom:1px solid #d6dbe4; padding-bottom:3pt; margin-top:18pt; }}
h3 {{ font-size:11.5pt; margin-top:12pt; }} table {{ border-collapse:collapse; width:100%; margin:8pt 0; font-size:9.5pt; }}
th,td {{ border:1px solid #d6dbe4; padding:5pt 7pt; text-align:left; vertical-align:top; }} th {{ background:#eef3f9; }}
code {{ font-family:Consolas,monospace; font-size:9pt; background:#f3f5f8; padding:1px 3px; border-radius:3px; }}
pre {{ background:#f3f5f8; padding:8pt; border-radius:5px; overflow:hidden; white-space:pre-wrap; font-size:8.5pt; line-height:1.35; }}
pre code {{ background:none; padding:0; }} blockquote {{ border-left:3px solid #0b5cad; margin:8pt 0; padding:2pt 10pt; color:#444; }}
a {{ color:#0b5cad; }}
</style></head><body>{body}</body></html>"""
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(); pg.set_content(html); pg.pdf(path=str(dst), format="A4", print_background=True); b.close()
print("wrote", dst)
