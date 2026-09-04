from pathlib import Path
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pdf"
W, H = A4
M = 44

INK = HexColor("#1D2730")
SLATE = HexColor("#63717D")
PAPER = HexColor("#FBF8F1")
WHITE = HexColor("#FFFFFF")
SAND = HexColor("#EEE3D2")
AMBER = HexColor("#D88308")
AMBER_D = HexColor("#8F5100")
AMBER_P = HexColor("#FFF0D2")
RED = HexColor("#C92E35")
RED_D = HexColor("#8E1F25")
RED_P = HexColor("#FDEBEC")
GREEN = HexColor("#278267")
GREEN_P = HexColor("#EAF5F0")


def fonts():
    base = Path("/System/Library/Fonts/Supplemental")
    pdfmetrics.registerFont(TTFont("Sans", str(base / "Arial.ttf")))
    pdfmetrics.registerFont(TTFont("SansB", str(base / "Arial Bold.ttf")))
    pdfmetrics.registerFont(TTFont("Serif", str(base / "Georgia.ttf")))
    pdfmetrics.registerFont(TTFont("SerifB", str(base / "Georgia Bold.ttf")))


def box(c, x, y, w, h, fill=WHITE, stroke=None, r=10, sw=.7):
    c.setFillColor(fill); c.setStrokeColor(stroke or fill); c.setLineWidth(sw)
    c.roundRect(x, y, w, h, r, fill=1, stroke=1)


def text(c, value, x, y, font="Sans", size=9, color=INK):
    c.setFont(font, size); c.setFillColor(color); c.drawString(x, y, value)


def wrap(c, value, x, y, width, font="Sans", size=9, leading=13, color=INK, max_lines=None):
    lines, current = [], ""
    for word in value.split():
        trial = (current + " " + word).strip()
        if pdfmetrics.stringWidth(trial, font, size) <= width:
            current = trial
        else:
            if current: lines.append(current)
            current = word
    if current: lines.append(current)
    if max_lines: lines = lines[:max_lines]
    for line in lines:
        text(c, line, x, y, font, size, color); y -= leading
    return y


def eyebrow(c, value, x, y, color=AMBER):
    text(c, value.upper(), x, y, "SansB", 7.5, color)


def base(c, page, section, lang, dark=False):
    c.setFillColor(INK if dark else PAPER); c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(AMBER); c.rect(0, H-7, W, 7, fill=1, stroke=0)
    text(c, "WAGGLE", M, H-30, "SansB", 8, WHITE if dark else INK)
    text(c, section.upper(), M+55, H-30, "Sans", 6.5, SAND if dark else SLATE)
    c.setFont("Sans", 6.5); c.setFillColor(SAND if dark else SLATE)
    c.drawRightString(W-M, H-30, f"{page} / 3")


def footer(c, lang, dark=False):
    color = SAND if dark else SLATE
    c.setStrokeColor(HexColor("#46515A") if dark else SAND); c.line(M, 28, W-M, 28)
    text(c, "WAGGLE · 04.09.2026 · " + ("YEREL İŞLEME" if lang=="tr" else "LOCAL PROCESSING"), M, 16, "Sans", 6.2, color)
    c.setFont("Sans", 6.2); c.setFillColor(color)
    c.drawRightString(W-M, 16, "ERKEN UYARI · KARAR DESTEĞİ" if lang=="tr" else "EARLY WARNING · DECISION SUPPORT")


DATA = {
 "tr": {
  "cover":"Haftalık kovan\ndeğerlendirmesi", "period":"28 Ağustos - 4 Eylül 2026", "scope":"3 KOVAN  /  3 AKUSTİK KAYIT",
  "lead":"Ses örüntüsü, Çayır Kovanı için beklememeyi söylüyor.",
  "detail":"Kalıcı akustik değişim algılandı. Bu bulgu kraliçe kaybıyla uyumlu olabilir; kesin tanı değildir ve fiziksel incelemeyle doğrulanmalıdır.",
  "cta":"24 SAAT İÇİNDE KONTROL", "action":"Çayır Kovanını açın; kraliçenin varlığını ve koloninin genel durumunu doğrulayın.",
  "note":"Waggle sağlık tanısı koymaz. Bu rapor erken uyarı ve karar desteği sağlar.",
  "overview":"Kovanların bu haftaki görünümü", "overview_sub":"Önce risk, sonra kanıt: her kovan için tek bakışta karar özeti.",
  "hives":[("H3","Çayır Kovanı","ALARM","%100","Kalıcı değişim","Fiziksel kontrol bekliyor"),("H2","Orman Kovanı","İZLEME","%68","Gelişen değişim","Yeni ses kaydı alın"),("H1","Bahçe Kovanı","NORMAL","%8","Normal profil","Rutin takibe devam")],
  "reading":"Nasıl okunmalı?", "reading_text":"Bu dönem tek günlük bir anlık görünüm içeriyor. Değerler kovanları karşılaştırır; zaman içindeki yönü göstermek için yeni kayıtlara ihtiyaç vardır.",
  "ai":"Yapay zekâ değerlendirmesi", "ai_text":"Ana karar fiziksel kontroldür. qwen2.5-1.5b çapraz kontrolü aynı sonuca ulaştı. Yerel RAG, uzun ve kesintisiz değişimin geçici gürültüden ayrılması gerektiğini vurguluyor.",
  "evidence":"Kanıt ve saha planı", "evidence_sub":"Model kararının arkasındaki ölçüm, bağlam ve izlenebilirlik.",
  "signal":"Aykırı ses oranı", "distribution":"Olay dağılımı", "field":"Saha doğrulaması", "field_text":"Bu dönemde fiziksel olarak doğrulanmış alarm yok.",
  "steps":[("1","Bugün","Çayır Kovanını fiziksel olarak inceleyin."),("2","Kontrolde","Kraliçeyi, yavru düzenini ve koloni davranışını doğrulayın."),("3","Sonrasında","Orman Kovanından karşılaştırılabilir yeni kayıt alın.")],
  "guide":"Yerel kılavuzun işaret ettiği bağlam", "g1":"Uzun ve kesintisiz değişim geçici gürültüden farklıdır.", "g2":"Kayıt bütünüyle farklıysa mikrofon yeri ile koloni durumunu birlikte kontrol edin.", "g3":"Sonbahar varroa yükü sesi etkileyebilir; sayım ve tedaviyi kış öncesi planlayın.",
  "sources":"RAG: alarm-sustained-run · alarm-very-high-fraction · alarm-interpretation · season-autumn-varroa"
 },
 "en": {
  "cover":"Weekly hive\nassessment", "period":"28 August - 4 September 2026", "scope":"3 HIVES  /  3 ACOUSTIC RECORDS",
  "lead":"The sound pattern says not to wait on Meadow Hive.",
  "detail":"A persistent acoustic change was detected. It may be compatible with queen loss; it is not a diagnosis and must be confirmed by physical inspection.",
  "cta":"INSPECT WITHIN 24 HOURS", "action":"Open Meadow Hive; verify queen presence and the colony's overall condition.",
  "note":"Waggle does not diagnose hive health. This report provides early warning and decision support.",
  "overview":"This week's hive picture", "overview_sub":"Risk first, evidence next: a single-glance decision summary for each hive.",
  "hives":[("H3","Meadow Hive","ALARM","100%","Persistent change","Physical inspection pending"),("H2","Forest Hive","WATCH","68%","Developing change","Record new audio"),("H1","Garden Hive","NORMAL","8%","Normal profile","Continue routine monitoring")],
  "reading":"How to read this", "reading_text":"This period contains a single-day snapshot. Values compare hives; new recordings are required to establish direction over time.",
  "ai":"AI assessment", "ai_text":"The primary decision is physical inspection. A qwen2.5-1.5b cross-check reached the same result. Local RAG emphasises separating long, uninterrupted change from passing noise.",
  "evidence":"Evidence and field plan", "evidence_sub":"Measurement, context, and traceability behind the model decision.",
  "signal":"Anomalous audio ratio", "distribution":"Event distribution", "field":"Field validation", "field_text":"No alarm was physically validated during this period.",
  "steps":[("1","Today","Physically inspect Meadow Hive."),("2","During inspection","Verify the queen, brood pattern, and colony behaviour."),("3","Afterwards","Capture a comparable new recording from Forest Hive.")],
  "guide":"Context highlighted by local guidance", "g1":"A long, uninterrupted change differs from passing noise.", "g2":"If the whole recording differs, check microphone placement and colony condition together.", "g3":"Autumn varroa load may alter sound; plan counting and treatment before wintering.",
  "sources":"RAG: alarm-sustained-run · alarm-very-high-fraction · alarm-interpretation · season-autumn-varroa"
 }
}


def cover(c, d, lang):
    base(c, 1, "weekly intelligence" if lang=="en" else "haftalık değerlendirme", lang, True)
    eyebrow(c, "EARLY WARNING REPORT" if lang=="en" else "ERKEN UYARI RAPORU", M, H-92, AMBER)
    y = H-134
    for line in d["cover"].split("\n"):
        text(c, line, M, y, "SerifB", 30, WHITE); y -= 37
    text(c, d["period"], M, y-4, "Sans", 9, SAND)
    text(c, d["scope"], M, y-24, "SansB", 7, AMBER)

    c.setFillColor(RED); c.circle(W-M-47, H-139, 39, fill=1, stroke=0)
    text(c, "!", W-M-53, H-153, "SansB", 30, WHITE)
    c.setFillColor(AMBER); c.rect(M, H-386, 4, 133, fill=1, stroke=0)
    wrap(c, d["lead"], M+20, H-278, 425, "SerifB", 21, 28, WHITE)
    wrap(c, d["detail"], M+20, H-349, 430, "Sans", 9.2, 14, SAND)

    box(c, M, H-548, W-2*M, 112, RED_D, RED_D, 14)
    eyebrow(c, d["cta"], M+22, H-466, WHITE)
    wrap(c, d["action"], M+22, H-494, W-2*M-44, "SerifB", 15, 21, WHITE)
    box(c, M, H-640, 151, 62, HexColor("#27343D"), HexColor("#3C4850"), 10)
    box(c, M+163, H-640, 151, 62, HexColor("#27343D"), HexColor("#3C4850"), 10)
    box(c, M+326, H-640, W-M-(M+326), 62, HexColor("#27343D"), HexColor("#3C4850"), 10)
    labels = ("ORTALAMA AYKIRILIK", "EN YÜKSEK SİNYAL", "ALARM ORANI") if lang=="tr" else ("MEAN ANOMALY", "PEAK SIGNAL", "ALARM RATE")
    for x, val, lab, col in [(M,"%59" if lang=="tr" else "59%",labels[0],AMBER),(M+163,"%100" if lang=="tr" else "100%",labels[1],RED),(M+326,"%33" if lang=="tr" else "33%",labels[2],RED)]:
        text(c,val,x+14,H-607,"SerifB",18,col); text(c,lab,x+14,H-626,"SansB",6,SAND)
    wrap(c, d["note"], M, 86, W-2*M, "Sans", 8, 12, SAND)
    footer(c, lang, True)


def hive_row(c, d, y, item):
    code, name, status, value, finding, follow = item
    col = RED if status=="ALARM" else AMBER if status in ("WATCH","İZLEME") else GREEN
    pale = RED_P if col==RED else AMBER_P if col==AMBER else GREEN_P
    box(c, M, y, W-2*M, 106, WHITE, SAND, 12)
    c.setFillColor(col); c.roundRect(M, y, 7, 106, 4, fill=1, stroke=0)
    text(c, code, M+24, y+70, "SerifB", 22, col)
    text(c, name, M+76, y+76, "SerifB", 15, INK)
    box(c, M+76, y+47, 68, 20, pale, pale, 10); c.setFont("SansB",6.5); c.setFillColor(col); c.drawCentredString(M+110,y+54,status)
    text(c, finding, M+76, y+26, "Sans", 8, SLATE)
    text(c, value, W-M-122, y+59, "SerifB", 24, col)
    text(c, follow, W-M-122, y+30, "SansB", 7.2, INK)


def overview(c, d, lang):
    base(c, 2, "hive overview" if lang=="en" else "kovan görünümü", lang)
    eyebrow(c, "STATUS BOARD" if lang=="en" else "DURUM PANOSU", M, H-72)
    text(c, d["overview"], M, H-105, "SerifB", 24)
    wrap(c, d["overview_sub"], M, H-126, 430, "Sans", 8, 12, SLATE)
    for y,item in zip((H-278,H-398,H-518), d["hives"]): hive_row(c,d,y,item)

    box(c, M, H-642, 222, 91, AMBER_P, AMBER_P, 11)
    eyebrow(c, d["reading"], M+16, H-578, AMBER_D)
    wrap(c,d["reading_text"],M+16,H-599,190,"Sans",7.6,11,INK)
    box(c, M+236, H-642, W-M-(M+236), 91, WHITE, SAND, 11)
    eyebrow(c,d["ai"],M+252,H-578)
    wrap(c,d["ai_text"],M+252,H-599,W-M-(M+252)-16,"Sans",7.3,10.5,INK)
    box(c, M, 70, W-2*M, 54, INK, INK, 10)
    text(c, "FOUNDRY LOCAL", M+16, 99, "SansB", 7, WHITE)
    text(c, "LOCAL RAG", M+120, 99, "SansB", 7, AMBER)
    text(c, "QWEN CROSS-CHECK", M+206, 99, "SansB", 7, WHITE)
    text(c, "3 RECORDS", M+355, 99, "SansB", 7, SAND)
    footer(c,lang)


def evidence(c,d,lang):
    base(c,3,"evidence + action" if lang=="en" else "kanıt + eylem",lang)
    eyebrow(c,"DECISION TRACE" if lang=="en" else "KARAR İZİ",M,H-72)
    text(c,d["evidence"],M,H-105,"SerifB",24)
    text(c,d["evidence_sub"],M,H-126,"Sans",8,SLATE)

    box(c,M,H-337,318,174,WHITE,SAND,12)
    text(c,d["signal"],M+16,H-190,"SerifB",14)
    left,bottom,cw,ch=M+46,H-306,244,83
    for p in (0,25,50,75,100):
        yy=bottom+ch*p/100; c.setStrokeColor(SAND); c.line(left,yy,left+cw,yy)
        c.setFont("Sans",5.5); c.setFillColor(SLATE); c.drawRightString(left-7,yy-2,f"{p}%")
    for (name,val,col),xx in zip((("H3",100,RED),("H2",68,AMBER),("H1",8,GREEN)),(left+42,left+122,left+202)):
        bh=ch*val/100; c.setFillColor(col); c.roundRect(xx-13,bottom,26,bh,5,fill=1,stroke=0)
        c.setFont("SansB",7); c.drawCentredString(xx,bottom+bh+8,f"{val}%")
        c.setFillColor(INK); c.drawCentredString(xx,bottom-14,name)
    box(c,M+332,H-337,W-M-(M+332),174,INK,INK,12)
    eyebrow(c,d["distribution"],M+350,H-191,AMBER)
    distribution = (("NORMAL",GREEN),("İZLEME",AMBER),("ALARM",RED)) if lang=="tr" else (("NORMAL",GREEN),("WATCH",AMBER),("ALARM",RED))
    for i,(lab,col) in enumerate(distribution):
        yy=H-225-i*29; c.setFillColor(col); c.circle(M+355,yy,5,fill=1,stroke=0)
        text(c,lab,M+369,yy-3,"SansB",7,WHITE); c.setFont("SerifB",11); c.setFillColor(WHITE); c.drawRightString(W-M-18,yy-4,"1 / 33%")
    text(c,d["field"],M+350,H-301,"SansB",7,AMBER)
    wrap(c,d["field_text"],M+350,H-316,W-M-(M+350)-16,"Sans",6.2,8,SAND)

    text(c,"FIELD PLAN" if lang=="en" else "SAHA PLANI",M,H-374,"SerifB",15)
    for i,(n,when,action) in enumerate(d["steps"]):
        y=H-445-i*58; c.setStrokeColor(SAND); c.line(M+14,y+1,M+14,y+58)
        c.setFillColor(RED if i==0 else AMBER); c.circle(M+14,y+31,11,fill=1,stroke=0)
        c.setFont("SansB",7); c.setFillColor(WHITE); c.drawCentredString(M+14,y+28,n)
        text(c,when.upper(),M+38,y+40,"SansB",6.5,RED if i==0 else AMBER_D)
        wrap(c,action,M+38,y+21,W-M-(M+38),"SansB",8.3,11,INK)

    box(c,M,82,W-2*M,150,WHITE,SAND,12)
    eyebrow(c,d["guide"],M+16,205)
    for i,key in enumerate(("g1","g2","g3")):
        yy=181-i*31; text(c,str(i+1),M+16,yy,"SerifB",12,AMBER)
        wrap(c,d[key],M+38,yy+1,W-2*M-54,"Sans",7.3,10,INK,max_lines=2)
    text(c,d["sources"],M+16,96,"Sans",5.5,SLATE)
    footer(c,lang)


def build(lang, filename):
    OUT.mkdir(parents=True,exist_ok=True); path=OUT/filename
    c=canvas.Canvas(str(path),pagesize=A4,pageCompression=1)
    c.setTitle(DATA[lang]["cover"].replace("\n"," ")); c.setAuthor("Waggle")
    cover(c,DATA[lang],lang); c.showPage(); overview(c,DATA[lang],lang); c.showPage(); evidence(c,DATA[lang],lang); c.save()
    print(path)


if __name__=="__main__":
    fonts()
    build("tr","Waggle-haftalik-rapor-TR-editorial.pdf")
    build("en","Waggle-weekly-report-EN-editorial.pdf")
