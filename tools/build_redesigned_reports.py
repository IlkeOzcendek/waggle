from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pdf"

W, H = A4
M = 42

INK = HexColor("#202630")
MUTED = HexColor("#68717D")
CREAM = HexColor("#FAF7F0")
PAPER = HexColor("#FFFFFF")
LINE = HexColor("#E8DED0")
AMBER = HexColor("#C87B12")
AMBER_DARK = HexColor("#8D540C")
AMBER_PALE = HexColor("#FFF5E3")
RED = HexColor("#C92D2D")
RED_PALE = HexColor("#FFF0EF")
GREEN = HexColor("#25835F")
GREEN_PALE = HexColor("#ECF8F2")


def register_fonts() -> None:
    base = Path("/System/Library/Fonts/Supplemental")
    pdfmetrics.registerFont(TTFont("Body", str(base / "Arial.ttf")))
    pdfmetrics.registerFont(TTFont("BodyBold", str(base / "Arial Bold.ttf")))
    pdfmetrics.registerFont(TTFont("Display", str(base / "Georgia.ttf")))
    pdfmetrics.registerFont(TTFont("DisplayBold", str(base / "Georgia Bold.ttf")))


def rounded(c: canvas.Canvas, x, y, w, h, fill, stroke=LINE, radius=10, width=0.7):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(width)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def wrap(c: canvas.Canvas, text: str, x: float, y: float, width: float,
         font="Body", size=9, leading=13, color=INK, max_lines=None) -> float:
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pdfmetrics.stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if max_lines:
        lines = lines[:max_lines]
    c.setFont(font, size)
    c.setFillColor(color)
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def label(c, text, x, y, color=AMBER):
    c.setFillColor(color)
    c.setFont("BodyBold", 7.5)
    c.drawString(x, y, text.upper())


def bee_mark(c, x, y, scale=1.0):
    """Small geometric bee mark: brand detail, not a mascot."""
    c.saveState()
    c.setLineCap(1)
    c.setStrokeColor(AMBER_DARK)
    c.setFillColor(AMBER_PALE)
    c.setLineWidth(0.8 * scale)
    c.ellipse(x - 10*scale, y + 1*scale, x - 1*scale, y + 9*scale, fill=1, stroke=1)
    c.ellipse(x + 1*scale, y + 1*scale, x + 10*scale, y + 9*scale, fill=1, stroke=1)
    c.setFillColor(AMBER)
    c.ellipse(x - 7*scale, y - 6*scale, x + 7*scale, y + 5*scale, fill=1, stroke=0)
    c.setStrokeColor(INK)
    c.setLineWidth(2.0 * scale)
    c.line(x - 3*scale, y - 5*scale, x - 3*scale, y + 4*scale)
    c.line(x + 3*scale, y - 5*scale, x + 3*scale, y + 4*scale)
    c.setFillColor(INK)
    c.circle(x, y + 5*scale, 3.1*scale, fill=1, stroke=0)
    c.restoreState()


def header(c, lang, page):
    c.setFillColor(CREAM)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(AMBER)
    c.rect(0, H - 8, W, 8, fill=1, stroke=0)
    bee_mark(c, M + 8, H - 29, 0.55)
    c.setFillColor(INK)
    c.setFont("BodyBold", 8)
    c.drawString(M + 20, H - 30, "WAGGLE")
    c.setFillColor(MUTED)
    c.setFont("Body", 7)
    c.drawString(M + 67, H - 30, "EDGE AI HIVE MONITORING")
    c.drawRightString(W - M, H - 30, f"{page} / 2")


def footer(c, text):
    c.setStrokeColor(LINE)
    c.line(M, 28, W - M, 28)
    c.setFillColor(MUTED)
    c.setFont("Body", 6.7)
    c.drawString(M, 16, text)
    c.drawRightString(W - M, 16, "Generated 4 Sep 2026 · Local processing")


def pill(c, x, y, text, fill, color, width=None):
    width = width or max(46, pdfmetrics.stringWidth(text, "BodyBold", 7) + 18)
    rounded(c, x, y, width, 20, fill, fill, 10, 0)
    c.setFillColor(color)
    c.setFont("BodyBold", 7)
    c.drawCentredString(x + width / 2, y + 6.5, text)
    return width


COPY = {
    "tr": {
        "title": "Haftalık kovan değerlendirmesi",
        "period": "28 Ağu - 4 Eyl 2026",
        "meta": "3 kovan · 3 akustik kayıt · Yerel işleme",
        "urgent": "1 kovan acil kontrol gerektiriyor",
        "urgent_sub": "Çayır Kovanı (H3) için kalıcı akustik değişim algılandı.",
        "early": "Erken uyarı",
        "ai": "YAPAY ZEKA ÖZETİ",
        "summary": "Bahçe Kovanı (H1) normal akustik profilinde kaldı. Orman Kovanı (H2) için gelişen değişim izleniyor. Çayır Kovanı (H3) için kraliçe kaybıyla uyumlu olabilecek kalıcı akustik değişim algılandı; bu kesin tanı değildir.",
        "actions": "ÖNCELİKLİ EYLEMLER",
        "a1": "Çayır Kovanını 24 saat içinde fiziksel olarak kontrol edin.",
        "a2": "Kraliçenin varlığını ve koloni durumunu doğrulayın.",
        "model": "MODEL KARARI",
        "priority": "Öncelik",
        "immediate": "ACİL",
        "pattern": "Kalıcı akustik değişim",
        "inspection": "Fiziksel kontrol gerekli",
        "cross": "Çapraz kontrol: qwen2.5-1.5b aynı kararda",
        "metrics": ["TOPLAM KAYIT", "ORTALAMA AYKIRILIK", "EN YÜKSEK DEĞER", "ALARM ORANI"],
        "metric_values": ["3", "%59", "%100", "%33"],
        "page2": "Kanıtlar ve izlenebilirlik",
        "trend": "Akustik eğilim",
        "trend_sub": "Kovan bazında aykırı ses oranı",
        "interpret": "Dönem tek günlük bir anlık görünüm içeriyor; yön değişimi çıkarılamaz. H3 %100, H2 %68, H1 %8 ölçüldü.",
        "distribution": "Olay dağılımı",
        "field": "Saha kontrolü",
        "field_text": "Bu dönemde fiziksel olarak kontrol edilmiş alarm bulunmuyor.",
        "attention": "Dikkat isteyen kayıtlar",
        "columns": ["ZAMAN", "KOVAN", "DURUM", "AYKIRI SES", "KONTROL"],
        "rows": [["4 Eyl 15:54", "Çayır Kovanı", "ALARM", "%100", "Bekliyor"], ["4 Eyl 15:54", "Orman Kovanı", "İZLEME", "%68", "Yeni kayıt"]],
        "guidance": "Yerel kılavuzdan",
        "g1": "Uzun ve kesintisiz değişim geçici gürültüden farklıdır; fiziksel kontrolü öne alın.",
        "g2": "Kayıt bütünüyle farklıysa mikrofon yerini ve koloni durumunu birlikte kontrol edin.",
        "g3": "Sonbaharda varroa yükü sesi değiştirebilir; kışlatma öncesi sayım ve tedaviyi planlayın.",
        "sources": "Kaynak kimlikleri: alarm-sustained-run · alarm-very-high-fraction · alarm-interpretation · season-autumn-varroa",
        "disclaimer": "Bu rapor erken uyarı ve karar desteği sağlar; fiziksel kovan incelemesinin yerini almaz.",
    },
    "en": {
        "title": "Weekly hive assessment",
        "period": "28 Aug - 4 Sep 2026",
        "meta": "3 hives · 3 acoustic records · Local processing",
        "urgent": "1 hive requires urgent inspection",
        "urgent_sub": "Persistent acoustic change was detected for Meadow Hive (H3).",
        "early": "Early warning",
        "ai": "AI SUMMARY",
        "summary": "Garden Hive (H1) remained within its normal acoustic profile. A developing change is being monitored for Forest Hive (H2). Persistent acoustic change compatible with possible queen loss was detected for Meadow Hive (H3); this is not a definitive diagnosis.",
        "actions": "PRIORITY ACTIONS",
        "a1": "Physically inspect Meadow Hive within 24 hours.",
        "a2": "Verify queen presence and overall colony condition.",
        "model": "MODEL DECISION",
        "priority": "Priority",
        "immediate": "IMMEDIATE",
        "pattern": "Persistent acoustic change",
        "inspection": "Physical inspection required",
        "cross": "Cross-check: qwen2.5-1.5b reached the same decision",
        "metrics": ["TOTAL RECORDS", "MEAN ANOMALY", "PEAK VALUE", "ALARM RATE"],
        "metric_values": ["3", "59%", "100%", "33%"],
        "page2": "Evidence and traceability",
        "trend": "Acoustic trend",
        "trend_sub": "Anomalous audio ratio by hive",
        "interpret": "The period contains a single-day snapshot, so no direction of change can be inferred. H3 measured 100%, H2 68%, and H1 8%.",
        "distribution": "Event distribution",
        "field": "Field inspection",
        "field_text": "No alarm was physically inspected during this period.",
        "attention": "Records needing attention",
        "columns": ["TIME", "HIVE", "STATUS", "ANOMALOUS", "FOLLOW-UP"],
        "rows": [["4 Sep 15:54", "Meadow Hive", "ALARM", "100%", "Pending"], ["4 Sep 15:54", "Forest Hive", "WATCH", "68%", "Record again"]],
        "guidance": "From local guidance",
        "g1": "A long, uninterrupted change differs from passing noise; prioritise physical inspection.",
        "g2": "When nearly the whole recording differs, check microphone placement and colony condition together.",
        "g3": "Autumn varroa load may alter colony sound; plan counting and treatment before wintering.",
        "sources": "Source IDs: alarm-sustained-run · alarm-very-high-fraction · alarm-interpretation · season-autumn-varroa",
        "disclaimer": "This report provides early warning and decision support; it does not replace physical hive inspection.",
    },
}


def draw_page_one(c, t, lang):
    header(c, lang, 1)
    label(c, "WEEKLY REPORT" if lang == "en" else "HAFTALIK RAPOR", M, H - 58)
    c.setFillColor(INK); c.setFont("DisplayBold", 23); c.drawString(M, H - 88, t["title"])
    c.setFillColor(MUTED); c.setFont("Body", 8); c.drawString(M, H - 106, t["period"] + "  ·  " + t["meta"])
    pill(c, W - M - 72, H - 99, t["early"].upper(), AMBER_PALE, AMBER_DARK, 72)

    rounded(c, M, H - 226, W - 2*M, 92, RED_PALE, HexColor("#F0B7B4"), 12)
    c.setFillColor(RED); c.circle(M + 31, H - 180, 18, fill=1, stroke=0)
    c.setFillColor(PAPER); c.setFont("BodyBold", 18); c.drawCentredString(M + 31, H - 187, "!")
    c.setFillColor(RED); c.setFont("DisplayBold", 17); c.drawString(M + 62, H - 174, t["urgent"])
    wrap(c, t["urgent_sub"], M + 62, H - 194, 370, size=8.5, color=INK)

    rounded(c, M, H - 355, W - 2*M, 108, PAPER)
    label(c, t["ai"], M + 18, H - 270, AMBER_DARK)
    wrap(c, t["summary"], M + 18, H - 292, W - 2*M - 36, font="Display", size=9.5, leading=14)
    pill(c, M + 18, H - 352, "FOUNDRY LOCAL", CREAM, MUTED, 76)
    pill(c, M + 100, H - 352, "LOCAL RAG", CREAM, MUTED, 66)
    pill(c, M + 172, H - 352, "3 RECORDS", CREAM, MUTED, 64)

    label(c, t["actions"], M, H - 385)
    for i, (text, color, fill) in enumerate(((t["a1"], RED, RED_PALE), (t["a2"], AMBER_DARK, AMBER_PALE)), 1):
        y = H - 450 - (i-1)*61
        rounded(c, M, y, 300, 49, fill, color, 9)
        c.setFillColor(color); c.circle(M + 22, y + 24.5, 12, fill=1, stroke=0)
        c.setFillColor(PAPER); c.setFont("BodyBold", 8); c.drawCentredString(M + 22, y + 21.5, str(i))
        wrap(c, text, M + 44, y + 29, 238, font="BodyBold", size=8.4, leading=11)

    x = M + 316; y = H - 511
    rounded(c, x, y, W - M - x, 110, PAPER)
    label(c, t["model"], x + 16, y + 89)
    c.setFont("Body", 7.5); c.setFillColor(MUTED); c.drawString(x + 16, y + 68, t["priority"])
    pill(c, x + 83, y + 59, t["immediate"], RED_PALE, RED, 72)
    c.setFillColor(INK); c.setFont("BodyBold", 8); c.drawString(x + 16, y + 43, t["pattern"])
    c.setFillColor(RED); c.drawString(x + 16, y + 27, t["inspection"])
    c.setFillColor(MUTED); c.setFont("Body", 6.8); c.drawString(x + 16, y + 11, t["cross"])

    label(c, "MEASUREMENTS" if lang == "en" else "ÖLÇÜMLER", M, H - 544)
    card_w = (W - 2*M - 18) / 4
    for i, (name, value) in enumerate(zip(t["metrics"], t["metric_values"])):
        x = M + i*(card_w + 6)
        rounded(c, x, H - 632, card_w, 70, PAPER)
        c.setFillColor(MUTED); c.setFont("BodyBold", 6.3); c.drawCentredString(x + card_w/2, H - 582, name)
        c.setFillColor([INK, AMBER_DARK, RED, RED][i]); c.setFont("DisplayBold", 18); c.drawCentredString(x + card_w/2, H - 614, value)

    rounded(c, M, H - 713, W - 2*M, 54, AMBER_PALE, AMBER_PALE)
    c.setFillColor(AMBER_DARK); c.setFont("BodyBold", 7.5); c.drawString(M + 16, H - 681, "SAFETY NOTE" if lang == "en" else "GÜVENLİK NOTU")
    wrap(c, t["disclaimer"], M + 16, H - 698, W - 2*M - 32, size=8)
    footer(c, t["disclaimer"])


def draw_chart(c, t, lang):
    rounded(c, M, H - 318, W - 2*M, 205, PAPER)
    c.setFillColor(INK); c.setFont("DisplayBold", 15); c.drawString(M + 16, H - 141, t["trend"])
    c.setFillColor(MUTED); c.setFont("Body", 7.5); c.drawString(M + 16, H - 158, t["trend_sub"])
    left, bottom, cw, ch = M + 50, H - 278, W - 2*M - 76, 94
    for pct in (0, 25, 50, 75, 100):
        yy = bottom + ch*pct/100
        c.setStrokeColor(LINE); c.line(left, yy, left+cw, yy)
        c.setFillColor(MUTED); c.setFont("Body", 6); c.drawRightString(left-7, yy-2, f"{pct}%")
    vals = [("H3",100,AMBER), ("H2",68,GREEN), ("H1",8,RED)]
    xs = [left + 45, left + cw/2, left + cw-45]
    for (name,val,color), xx in zip(vals,xs):
        c.setStrokeColor(color); c.setLineWidth(3); c.line(xx, bottom, xx, bottom + ch*val/100)
        c.setFillColor(color); c.circle(xx, bottom + ch*val/100, 4, fill=1, stroke=0)
        c.setFont("BodyBold", 7); c.drawCentredString(xx, bottom-13, name)
        c.drawCentredString(xx, bottom + ch*val/100 + 8, f"{val}%")
    rounded(c, M + 16, H - 306, W - 2*M - 32, 35, AMBER_PALE, AMBER_PALE, 6)
    wrap(c, t["interpret"], M + 27, H - 287, W - 2*M - 54, size=7.2, leading=10)


def draw_page_two(c, t, lang):
    header(c, lang, 2)
    label(c, "EVIDENCE" if lang == "en" else "KANITLAR", M, H - 58)
    c.setFillColor(INK); c.setFont("DisplayBold", 22); c.drawString(M, H - 87, t["page2"])
    c.setFillColor(MUTED); c.setFont("Body", 8); c.drawString(M, H - 104, t["period"] + "  ·  " + t["meta"])
    draw_chart(c, t, lang)

    y = H - 344
    c.setFillColor(INK); c.setFont("DisplayBold", 14); c.drawString(M, y, t["distribution"])
    items = [("NORMAL", 1, GREEN), ("WATCH", 1, AMBER), ("ALARM", 1, RED)]
    for i, (name,count,color) in enumerate(items):
        x = M + i*112
        rounded(c, x, y-48, 102, 34, PAPER)
        c.setFillColor(color); c.circle(x+14, y-31, 4, fill=1, stroke=0)
        c.setFillColor(INK); c.setFont("BodyBold", 7); c.drawString(x+24, y-28, name)
        c.setFillColor(MUTED); c.setFont("Body", 7); c.drawRightString(x+90, y-28, "1 · 33%")
    rounded(c, M + 350, y-56, W-M-(M+350), 42, AMBER_PALE, AMBER_PALE)
    c.setFillColor(AMBER_DARK); c.setFont("BodyBold", 7); c.drawString(M+364, y-29, t["field"])
    c.setFillColor(MUTED)
    wrap(c, t["field_text"], M+364, y-41, W-M-(M+364)-12, size=6.0, leading=7, max_lines=2)

    y2 = H - 438
    c.setFillColor(INK); c.setFont("DisplayBold", 14); c.drawString(M, y2, t["attention"])
    table_y = y2 - 77
    widths = [82, 126, 70, 76, 88]
    x = M
    c.setFillColor(HexColor("#EFE7DA")); c.rect(M, table_y+50, sum(widths), 24, fill=1, stroke=0)
    for name,w in zip(t["columns"],widths):
        c.setFillColor(MUTED); c.setFont("BodyBold", 6.2); c.drawString(x+7, table_y+59, name); x += w
    for r,row in enumerate(t["rows"]):
        yy = table_y + 25 - r*25; x=M
        c.setFillColor(PAPER); c.rect(M, yy, sum(widths), 25, fill=1, stroke=0)
        for idx,(value,w) in enumerate(zip(row,widths)):
            c.setFillColor(RED if idx==2 and r==0 else (AMBER_DARK if idx==2 else INK))
            c.setFont("BodyBold" if idx in (2,4) else "Body", 6.8)
            c.drawString(x+7, yy+8, value); x += w
        c.setStrokeColor(LINE); c.line(M, yy, M+sum(widths), yy)

    gy = H - 566
    rounded(c, M, gy-139, W-2*M, 132, PAPER)
    label(c, t["guidance"], M+16, gy-28)
    for i, text in enumerate((t["g1"], t["g2"], t["g3"]),1):
        yy = gy - 51 - (i-1)*27
        c.setFillColor(AMBER); c.circle(M+24, yy+3, 8, fill=1, stroke=0)
        c.setFillColor(PAPER); c.setFont("BodyBold", 6.5); c.drawCentredString(M+24, yy+1, str(i))
        wrap(c, text, M+39, yy+7, W-2*M-57, size=7.2, leading=9, max_lines=2)
    c.setFillColor(MUTED); c.setFont("Body", 5.8); c.drawString(M+16, gy-128, t["sources"])

    rounded(c, M, 55, W-2*M, 46, RED_PALE, RED_PALE)
    c.setFillColor(RED); c.setFont("BodyBold", 7.5); c.drawString(M+14, 82, "IMPORTANT" if lang=="en" else "ÖNEMLİ")
    wrap(c, t["disclaimer"], M+14, 67, W-2*M-28, size=7.5)
    footer(c, t["disclaimer"])


def build(lang: str, filename: str):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / filename
    c = canvas.Canvas(str(path), pagesize=A4, pageCompression=1)
    c.setTitle(COPY[lang]["title"])
    c.setAuthor("Waggle")
    draw_page_one(c, COPY[lang], lang)
    c.showPage()
    draw_page_two(c, COPY[lang], lang)
    c.save()
    return path


if __name__ == "__main__":
    register_fonts()
    print(build("tr", "Waggle-haftalik-rapor-TR-redesign.pdf"))
    print(build("en", "Waggle-weekly-report-EN-redesign.pdf"))
