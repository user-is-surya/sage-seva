"""Generate synthetic sample documents for the demo (fictional person, dummy numbers).

The three cards deliberately spell the same name three ways, which is the
real-world problem SAGE Seva's name guard addresses. Rendered through
Chromium so Indic scripts get proper conjunct shaping.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "samples"
OUT.mkdir(exist_ok=True)

CSS = """
body{margin:0;font-family:'Nirmala UI','Noto Sans Telugu','Segoe UI',sans-serif;}
.c{width:1000px;height:620px;background:#fbfaf6;position:relative;overflow:hidden}
.h{height:96px;color:#fff;padding:14px 32px;box-sizing:border-box}
.h b{font-size:34px;display:block}.h span{font-size:20px}
.p{position:absolute;left:32px;top:130px;width:190px;height:230px;border:2px solid #9aa3b2;color:#9aa3b2;display:grid;place-items:center;font-size:28px}
.f{position:absolute;left:250px;top:120px;right:20px}
.l{font-size:18px;color:#5b6475;margin-top:10px}.v{font-size:27px;font-weight:700;color:#1d2433}
.n{position:absolute;left:32px;bottom:34px;font-size:28px;font-weight:700;color:#1d2433}
.w{position:absolute;left:150px;top:260px;font-size:78px;font-weight:800;color:rgba(200,30,30,.22);transform:rotate(-14deg)}
"""


def card(fname, title, subtitle, color, rows, number_label, number):
    fields = "".join(f'<div class="l">{l}</div><div class="v">{v}</div>' for l, v in rows)
    return fname, f"""<html><head><meta charset="utf-8"><style>{CSS}</style></head><body><div class="c">
<div class="h" style="background:{color}"><b>{title}</b><span>{subtitle}</span></div>
<div class="p">PHOTO</div><div class="f">{fields}</div>
<div class="n">{number_label}: {number}</div><div class="w">SAMPLE · SYNTHETIC</div></div></body></html>"""


CARDS = [
    card("1_identity_card.png", "Identity Card (SAMPLE)", "Synthetic document for demo · not a real ID", "#1f4e8c", [
        ("పేరు / Name", "కొండపల్లి వెంకట సుబ్బారావు"),
        ("Name", "Kondapalli Venkata Subba Rao"),
        ("Father", "Kondapalli Rama Rao"),
        ("DOB / Gender", "14/08/1979 &nbsp;·&nbsp; Male"),
        ("Address", "4-12 Gandhi Nagar, Kakinada, Kakinada Dist., Andhra Pradesh"),
    ], "ID No.", "9999 0000 4821"),
    card("2_ration_card.png", "Ration Card (SAMPLE)", "Synthetic household card for demo", "#2f7a3e", [
        ("కుటుంబ పెద్ద / Head of family", "కె. వెంకట్ సుబ్బారావు"),
        ("Name", "K. Venkat Subbarao"),
        ("Father", "K. Rama Rao"),
        ("Members", "4 &nbsp;·&nbsp; Category: BPL"),
        ("Address", "4-12 Gandhi Nagar, Kakinada, Andhra Pradesh"),
    ], "Card No.", "SMP-RC-0281-4471"),
    card("3_voter_id.png", "Voter Identity Card (SAMPLE)", "Synthetic document for demo · not a real EPIC", "#7a2f6a", [
        ("Elector's name", "Vemkata Subbarao Kondapalli"),
        ("పేరు", "వెంకట సుబ్బారావు కొండపల్లి"),
        ("Father's name", "Rama Rao Kondapalli"),
        ("DOB / Sex", "14/08/1979 &nbsp;·&nbsp; M"),
        ("Address", "4-12 Gandhi Nagar, Kakinada, Andhra Pradesh"),
    ], "EPIC No.", "SMP0000917"),
]

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1000, "height": 620})
    for fname, html in CARDS:
        pg.set_content(html)
        pg.screenshot(path=str(OUT / fname))
        print("wrote", OUT / fname)
    b.close()
