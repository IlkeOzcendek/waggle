from __future__ import annotations

from collections import Counter
from io import BytesIO
from pathlib import Path


def _font_name() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
    )
    for path in candidates:
        if path.exists():
            pdfmetrics.registerFont(TTFont("WaggleUnicode", str(path)))
            return "WaggleUnicode"
    return "Helvetica"


def build_report_pdf(report, events, hive_names: dict[str, str]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output = BytesIO()
    font = _font_name()
    styles = getSampleStyleSheet()
    title = ParagraphStyle("WaggleTitle", parent=styles["Title"], fontName=font, fontSize=22, leading=28, textColor=colors.HexColor("#202733"), spaceAfter=10)
    heading = ParagraphStyle("WaggleHeading", parent=styles["Heading2"], fontName=font, fontSize=14, leading=18, textColor=colors.HexColor("#9A410C"), spaceBefore=14, spaceAfter=8)
    body = ParagraphStyle("WaggleBody", parent=styles["BodyText"], fontName=font, fontSize=9.5, leading=15, textColor=colors.HexColor("#414A57"))
    small = ParagraphStyle("WaggleSmall", parent=body, fontSize=7.5, leading=11, textColor=colors.HexColor("#716A62"))
    interpretation = ParagraphStyle("WaggleInterpretation", parent=body, fontSize=8.5, leading=13, leftIndent=8, rightIndent=8, borderColor=colors.HexColor("#D89338"), borderWidth=0, borderLeftWidth=2, borderPadding=7, backColor=colors.HexColor("#FFF6E8"), spaceBefore=5, spaceAfter=9)
    labels = {"event": "Olay raporu", "daily": "Günlük rapor", "weekly": "Haftalık rapor"} if report.language == "tr" else {"event": "Event report", "daily": "Daily report", "weekly": "Weekly report"}
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=19*mm, leftMargin=19*mm, topMargin=18*mm, bottomMargin=18*mm, title=f"Waggle {labels[report.report_type]}")
    story = [Paragraph("WAGGLE · EDGE AI HIVE MONITORING", small), Paragraph(labels[report.report_type], title)]
    period = f"{report.period_start:%d.%m.%Y %H:%M} – {report.period_end:%d.%m.%Y %H:%M}"
    hives = ", ".join(f"{hive_names.get(hive_id, hive_id)} ({hive_id})" for hive_id in report.hive_ids)
    generator_labels = {
        "deterministic-demo": "Waggle Yerel Rapor Motoru" if report.language == "tr" else "Waggle Local Report Engine",
        "safe-fallback": "Deterministik yedek motor (yapay zekâ modeline ulaşılamadı)" if report.language == "tr" else "Deterministic fallback engine (AI model was unreachable)",
    }
    # Model-backed generators carry the alias, so they are matched by prefix the same
    # way the panel does, otherwise the PDF would print the raw machine string.
    if report.generator in generator_labels:
        generator = generator_labels[report.generator]
    elif "agent" in report.generator.lower():
        generator = "Agent Framework + Foundry Local"
    elif "foundry" in report.generator.lower():
        generator = "Foundry Local · Phi"
    else:
        generator = report.generator
    story += [Table([["Dönem", period], ["Kovanlar", hives], ["Üretici", generator]], colWidths=[31*mm, 122*mm], style=TableStyle([("FONTNAME",(0,0),(-1,-1),font),("FONTSIZE",(0,0),(-1,-1),8),("TEXTCOLOR",(0,0),(0,-1),colors.HexColor("#9A6732")),("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#FFF8EC")),("BOX",(0,0),(-1,-1),.5,colors.HexColor("#E7D7BE")),("INNERGRID",(0,0),(-1,-1),.25,colors.HexColor("#E7D7BE")),("VALIGN",(0,0),(-1,-1),"TOP"),("PADDING",(0,0),(-1,-1),7)])), Paragraph("Genel değerlendirme" if report.language == "tr" else "Overall assessment", heading), Paragraph(report.summary, body)]
    story.append(Paragraph("Önerilen adımlar" if report.language == "tr" else "Recommended actions", heading))
    for index, action in enumerate(report.recommendations, 1):
        story.append(Paragraph(f"<b>{index}.</b> {action}", body)); story.append(Spacer(1, 2*mm))
    counts = Counter(event.status for event in events)
    inspections = Counter(event.inspection_result for event in events if event.acknowledged_at)
    ordered_events = sorted(events, key=lambda event: event.timestamp)
    values = [max(0.0, min(1.0, float(event.anomaly_fraction))) for event in ordered_events]
    average = sum(values) / len(values) if values else 0.0
    peak = max(values) if values else 0.0
    alarm_rate = counts["ALARM"] / len(events) if events else 0.0
    metric_labels = ("Toplam kayıt", "Ortalama aykırılık", "En yüksek değer", "Alarm oranı") if report.language == "tr" else ("Total records", "Average anomaly", "Peak value", "Alarm rate")
    metric_values = (str(len(events)), f"%{average*100:.0f}", f"%{peak*100:.0f}", f"%{alarm_rate*100:.0f}")
    metrics = Table([metric_labels, metric_values], colWidths=[38.25*mm]*4, style=TableStyle([("FONTNAME",(0,0),(-1,-1),font),("FONTSIZE",(0,0),(-1,0),7),("FONTSIZE",(0,1),(-1,1),15),("TEXTCOLOR",(0,0),(-1,0),colors.HexColor("#756D64")),("TEXTCOLOR",(0,1),(-1,1),colors.HexColor("#9A410C")),("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#FFFDF9")),("BOX",(0,0),(-1,-1),.5,colors.HexColor("#DDD5C9")),("INNERGRID",(0,0),(-1,-1),.25,colors.HexColor("#E9E1D6")),("ALIGN",(0,0),(-1,-1),"CENTER"),("PADDING",(0,0),(-1,-1),7)]))
    story += [Paragraph("Ölçüm özeti" if report.language == "tr" else "Measurement summary", heading), metrics]

    if ordered_events:
        chart = Drawing(440, 190)
        left, bottom, width, height = 42, 28, 382, 120
        palette = ("#C75F0C", "#28786B", "#BB3430", "#7764A5", "#5E7893")
        grouped = []
        for hive_id in dict.fromkeys(event.hive_id for event in ordered_events):
            grouped.append((hive_id, [event for event in ordered_events if event.hive_id == hive_id], palette[len(grouped) % len(palette)]))
        legend_x = left
        for hive_id, _, color_value in grouped:
            label = f"{hive_names.get(hive_id, hive_id)} ({hive_id})" if hive_id in hive_names else hive_id
            chart.add(Line(legend_x, 174, legend_x+12, 174, strokeColor=colors.HexColor(color_value), strokeWidth=2.4))
            chart.add(String(legend_x+16, 171, label, fontName=font, fontSize=6.5, fillColor=colors.HexColor("#4D5662")))
            legend_x += min(150, 28 + len(label)*4.2)
        for level in (0, .25, .5, .75, 1):
            y = bottom + level * height
            chart.add(Line(left, y, left+width, y, strokeColor=colors.HexColor("#E9E1D6"), strokeWidth=.6))
            chart.add(String(left-7, y-3, f"{level*100:.0f}%", fontName=font, fontSize=6.5, fillColor=colors.HexColor("#746C63"), textAnchor="end"))
        first_time = ordered_events[0].timestamp.timestamp()
        last_time = ordered_events[-1].timestamp.timestamp()
        for _, hive_events, color_value in grouped:
            points = [(left + (event.timestamp.timestamp()-first_time)/max(last_time-first_time, 1)*width, bottom + max(0,min(1,float(event.anomaly_fraction)))*height) for event in hive_events]
            if len(points) == 1:
                points.append((left+width, points[0][1]))
            chart.add(PolyLine(points, strokeColor=colors.HexColor(color_value), strokeWidth=2.2))
            for x, y in points[:len(hive_events)]:
                chart.add(Circle(x, y, 2.5, fillColor=colors.white, strokeColor=colors.HexColor(color_value), strokeWidth=1.3))
        chart.add(String(left, 10, ordered_events[0].timestamp.strftime("%d.%m"), fontName=font, fontSize=6.5, fillColor=colors.HexColor("#746C63")))
        chart.add(String(left+width, 10, ordered_events[-1].timestamp.strftime("%d.%m"), fontName=font, fontSize=6.5, fillColor=colors.HexColor("#746C63"), textAnchor="end"))
        deltas = [float(hive_events[-1].anomaly_fraction)-float(hive_events[0].anomaly_fraction) for _, hive_events, _ in grouped if len(hive_events)>1]
        rising, falling = sum(delta >= .08 for delta in deltas), sum(delta <= -.08 for delta in deltas)
        peak_event = max(ordered_events, key=lambda event: event.anomaly_fraction)
        peak_hive = hive_names.get(peak_event.hive_id, peak_event.hive_id)
        # "0 rose and 0 fell" is noise; say plainly that nothing moved.
        if report.language == "tr":
            direction = "Dönem boyunca belirgin bir yön değişimi görülmedi." if not rising and not falling else f"{rising} kovanda belirgin artış, {falling} kovanda belirgin azalış görüldü."
            trend_text = f"Yorum: {direction} En yüksek değer {peak_hive} için %{peak*100:.0f}, tüm kayıtların ortalaması %{average*100:.0f} oldu."
        else:
            direction = "No material change of direction was observed during the period." if not rising and not falling else f"{rising} hive(s) increased and {falling} hive(s) decreased materially."
            trend_text = f"Interpretation: {direction} The highest value was in {peak_hive} ({peak*100:.0f}%); the overall average was {average*100:.0f}%."
        story += [Paragraph("Akustik eğilim" if report.language == "tr" else "Acoustic trend", heading), Paragraph("Aykırı ses oranının zaman içindeki değişimi" if report.language == "tr" else "Anomalous audio ratio over time", body), chart, Paragraph(trend_text, interpretation)]

    bars = Drawing(440, 108)
    status_colors = {"NORMAL": "#24A978", "WATCH": "#DDA129", "ALARM": "#CA3731"}
    for index, status in enumerate(("NORMAL", "WATCH", "ALARM")):
        y = 79-index*31
        percentage = counts[status]/len(events) if events else 0
        bars.add(String(5, y+3, status, fontName=font, fontSize=7.5, fillColor=colors.HexColor("#4D5662")))
        bars.add(Rect(67, y, 305, 12, rx=6, ry=6, fillColor=colors.HexColor("#EEE8DE"), strokeColor=None))
        if percentage:
            bars.add(Rect(67, y, 305*percentage, 12, rx=6, ry=6, fillColor=colors.HexColor(status_colors[status]), strokeColor=None))
        bars.add(String(430, y+3, f"{counts[status]} · %{percentage*100:.0f}", fontName=font, fontSize=7.5, fillColor=colors.HexColor("#4D5662"), textAnchor="end"))
    dominant = max(("NORMAL", "WATCH", "ALARM"), key=lambda status: counts[status]) if events else "—"
    leaders = [status for status in ("NORMAL", "WATCH", "ALARM") if counts[status] == counts[dominant]] if events else []
    if len(leaders) > 1:
        status_text = f"Yorum: En yüksek sayıdaki karar grupları eşit dağıldı. {len(events)} kaydın {counts['ALARM']} tanesi ALARM oldu (%{alarm_rate*100:.0f})." if report.language == "tr" else f"Interpretation: the leading decision groups were evenly distributed. {counts['ALARM']} of {len(events)} records were ALARM ({alarm_rate*100:.0f}%)."
    else:
        status_text = f"Yorum: En sık verilen karar {dominant} oldu. {len(events)} kaydın {counts['ALARM']} tanesi ALARM olarak sınıflandırıldı (%{alarm_rate*100:.0f})." if report.language == "tr" else f"Interpretation: {dominant} was the most frequent decision. {counts['ALARM']} of {len(events)} records were classified as ALARM ({alarm_rate*100:.0f}%)."
    distribution_block = KeepTogether([Paragraph("Olay dağılımı" if report.language == "tr" else "Event distribution", heading), Paragraph("Kayıtların durumlara göre dağılımı" if report.language == "tr" else "Distribution of records by status", body), bars, Paragraph(status_text, interpretation)])
    # The status counts already appear in the distribution block above, so this table
    # carries only what it is named after: the outcome of physical inspections.
    inspection_labels = ("Sorun doğrulandı", "Sorun görülmedi", "Belirsiz") if report.language == "tr" else ("Issue confirmed", "No issue found", "Inconclusive")
    inspection_row = [inspections["issue_confirmed"], inspections["no_issue_found"], inspections["uncertain"]]
    story += [distribution_block, Paragraph("Saha kontrol sonuçları" if report.language == "tr" else "Field inspection outcomes", heading)]
    if any(inspection_row):
        story.append(Table([list(inspection_labels), inspection_row], colWidths=[51*mm]*3, style=TableStyle([("FONTNAME",(0,0),(-1,-1),font),("FONTSIZE",(0,0),(-1,0),7.5),("FONTSIZE",(0,1),(-1,1),13),("TEXTCOLOR",(0,0),(-1,0),colors.HexColor("#756D64")),("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#F7F3EB")),("BOX",(0,0),(-1,-1),.5,colors.HexColor("#DDD5C9")),("INNERGRID",(0,0),(-1,-1),.25,colors.HexColor("#DDD5C9")),("ALIGN",(0,0),(-1,-1),"CENTER"),("PADDING",(0,0),(-1,-1),7)])))
    else:
        story.append(Paragraph(
            "Bu dönemde fiziksel olarak kontrol edilen alarm bulunmuyor." if report.language == "tr"
            else "No alarm was physically inspected during this period.",
            small,
        ))
    # Only the records that ask for a decision are worth printing. Listing every NORMAL
    # window turned the report into a data dump that buried its own conclusions.
    notable = [event for event in ordered_events if event.status in ("ALARM", "WATCH")]
    notable.sort(key=lambda event: (event.status != "ALARM", -float(event.anomaly_fraction), event.timestamp))
    shown = notable[:15]
    if shown:
        story += [Paragraph("Dikkat isteyen kayıtlar" if report.language == "tr" else "Records needing attention", heading)]
        rows = [["Zaman", "Kovan", "Durum", "Aykırı pencere"] if report.language == "tr" else ["Time", "Hive", "Status", "Anomalous window"]]
        rows += [[event.timestamp.strftime("%d.%m %H:%M"), hive_names.get(event.hive_id, event.hive_id), event.status, f"%{event.anomaly_fraction*100:.0f}"] for event in shown]
        story.append(Table(rows, repeatRows=1, colWidths=[34*mm,58*mm,28*mm,32*mm], style=TableStyle([("FONTNAME",(0,0),(-1,-1),font),("FONTSIZE",(0,0),(-1,-1),7.5),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#EDE5D8")),("GRID",(0,0),(-1,-1),.25,colors.HexColor("#DDD5C9")),("PADDING",(0,0),(-1,-1),5)])))
        omitted = len(notable) - len(shown)
        note = (
            f"{len(events)} kaydın {len(notable)} tanesi izleme veya alarm durumundaydı"
            + (f"; en yüksek {len(shown)} tanesi listelendi. " if omitted > 0 else ". ")
            + "Kayıtların tamamı için Dışa Aktar bölümünü kullanın."
            if report.language == "tr" else
            f"{len(notable)} of {len(events)} records were watch or alarm"
            + (f"; the {len(shown)} highest are listed. " if omitted > 0 else ". ")
            + "Use the Export section for the complete set."
        )
        story.append(Paragraph(note, small))
    elif events:
        story.append(Paragraph(
            "Dönem boyunca izleme veya alarm durumunda kayıt bulunmadı." if report.language == "tr"
            else "No watch or alarm records occurred during the period.",
            small,
        ))
    if report.grounding_sources:
        story += [Paragraph("RAG kaynakları" if report.language == "tr" else "RAG sources", heading), Paragraph(" · ".join(report.grounding_sources), small)]
    story += [Spacer(1, 6*mm), Paragraph("Bu rapor erken uyarı ve karar desteği sağlar; fiziksel kovan incelemesinin yerini almaz." if report.language == "tr" else "This report provides early warning and decision support; it does not replace physical hive inspection.", small)]
    doc.build(story)
    return output.getvalue()
