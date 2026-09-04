"""The PDF a beekeeper downloads and carries to the apiary.

The document is organised around hives, not around sections. A period covering three
hives in three different states cannot be summarised by one averaged percentage — the
average describes a hive that does not exist — so the first page names the hive that
needs opening, shows each hive next to its own measurement, and states the chain the
decision came down: the ONNX profile that measured the sound, the local guidance that
was retrieved, the language model that phrased it and the model that cross-checked it.
Evidence follows on its own page.
"""

from __future__ import annotations

import math
from xml.sax.saxutils import escape
from collections import Counter
from datetime import timedelta
from io import BytesIO
from pathlib import Path

try:  # The panel answers 503 rather than 500 when the PDF component is absent.
    from reportlab.platypus import Flowable as _Flowable
except ImportError:  # pragma: no cover - exercised only on installs without reportlab
    _Flowable = object


# --- palette -------------------------------------------------------------------------
# Colour carries one meaning in this document: the state of a hive. The wordmark, the
# headings and the rules are ink, so nothing competes with green / amber / red.
INK = "#16191A"
INK_2 = "#4C5457"
INK_3 = "#858D8F"
PAPER_2 = "#F6F5F2"
RULE = "#E3E2DC"
RULE_2 = "#CFCEC6"
STATE = {
    "NORMAL": ("#1E7A5A", "#E9F4EF"),
    "WATCH": ("#9A6209", "#FAF0DE"),
    "ALARM": ("#AE2A20", "#FAE9E7"),
}
STATE_NAMES = {
    "tr": {"NORMAL": "NORMAL", "WATCH": "İZLEME", "ALARM": "ALARM"},
    "en": {"NORMAL": "NORMAL", "WATCH": "WATCH", "ALARM": "ALARM"},
}


def _register(name: str, candidates: tuple[str, ...]) -> str | None:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for candidate in candidates:
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(name, str(path)))
        except Exception:  # noqa: BLE001 - a broken font file must not lose the report
            continue
        return name
    return None


def _fonts() -> dict[str, str]:
    """Body, display and label faces, falling back until something with Turkish glyphs is left.

    A missing font file must degrade the typography, never the document: every role
    resolves to a built-in face rather than raising.
    """
    mac = "/System/Library/Fonts/Supplemental/"
    linux = "/usr/share/fonts/truetype/dejavu/"
    body = _register("WaggleBody", (mac + "Arial Unicode.ttf", linux + "DejaVuSans.ttf", mac + "Arial.ttf"))
    bold = _register("WaggleBodyBold", (linux + "DejaVuSans-Bold.ttf", mac + "Arial Bold.ttf"))
    display = _register("WaggleDisplay", (mac + "Georgia.ttf", linux + "DejaVuSerif.ttf"))
    display_bold = _register("WaggleDisplayBold", (mac + "Georgia Bold.ttf", linux + "DejaVuSerif-Bold.ttf"))
    mono = _register("WaggleMono", (mac + "Courier New.ttf", linux + "DejaVuSansMono.ttf"))
    mono_bold = _register("WaggleMonoBold", (mac + "Courier New Bold.ttf", linux + "DejaVuSansMono-Bold.ttf"))
    body = body or "Helvetica"
    bold = bold or ("Helvetica-Bold" if body == "Helvetica" else body)
    display = display or "Times-Roman"
    display_bold = display_bold or ("Times-Bold" if display == "Times-Roman" else display)
    return {
        "body": body,
        "bold": bold,
        "display": display,
        "display_bold": display_bold,
        "mono": mono or body,
        "mono_bold": mono_bold or bold,
    }


def _font_name() -> str:
    """The body face, kept under its original name for callers outside this module."""
    return _fonts()["body"]


def fmt_pct(value: float, language: str) -> str:
    """A ratio written the way the language writes it: %59 in Turkish, 59% in English.

    The formatter used to be language-blind, so the English report printed Turkish
    percentages throughout.
    """
    return f"%{value * 100:.0f}" if language == "tr" else f"{value * 100:.0f}%"


def measurement_label(events, language: str) -> str:
    """The acoustic models behind the period's measurements.

    The chain a report rests on starts at the ONNX profile that decided the events, not at
    the language model that phrased them. Naming only the latter makes the document read
    as prose about nothing measured.
    """
    models = sorted({event.model for event in events if getattr(event, "model", None)})
    if not models:
        return "Kayıt yok" if language == "tr" else "Not recorded"
    return f'{", ".join(models)} · ONNX Runtime'


def notable_record_rows(events, language: str, hive_names: dict[str, str]):
    """The header, rows and column widths, in millimetres, of the record table.

    Two records at the same anomalous-window ratio are not the same measurement, and a
    printed table showing only the ratio said they were: a shallow deviation running
    through a whole recording looked exactly like a deep one. The depth is a column of its
    own, and it is dropped entirely — rather than filled with dashes — for a period
    recorded before the acoustic model reported it.
    """
    measured = any(event.anomaly_severity is not None for event in events)
    header = (["Zaman", "Kovan", "Durum", "Aykırı pencere", "Sapma şiddeti", "Kontrol eden"] if language == "tr"
              else ["Time", "Hive", "Status", "Anomalous window", "Severity", "Inspected by"])
    names = STATE_NAMES["tr" if language == "tr" else "en"]
    rows = [header] + [
        [
            event.timestamp.strftime("%d.%m %H:%M"),
            hive_names.get(event.hive_id, event.hive_id),
            names.get(event.status, event.status),
            fmt_pct(float(event.anomaly_fraction), language),
            "—" if event.anomaly_severity is None else fmt_pct(float(event.anomaly_severity), language),
            event.acknowledged_by or "—",
        ]
        for event in events
    ]
    if measured:
        return rows, [26, 42, 22, 26, 24, 28]
    # The hive name gets the width back, which is where it is needed most.
    return [row[:4] + row[5:] for row in rows], [26, 54, 22, 30, 36]


# WMO interpretation codes, in the bands a beekeeper reads rather than one label per code.
WEATHER_BANDS = (
    (0, 0, "açık", "clear"),
    (1, 3, "az bulutlu", "partly cloudy"),
    (45, 48, "sisli", "fog"),
    (51, 57, "çiseleme", "drizzle"),
    (61, 67, "yağmur", "rain"),
    (71, 77, "kar", "snow"),
    (80, 82, "sağanak", "showers"),
    (85, 86, "kar sağanağı", "snow showers"),
    (95, 99, "gök gürültülü", "thunderstorm"),
)


def weather_label(code, language: str) -> str:
    if code is None:
        return "—"
    for low, high, turkish, english in WEATHER_BANDS:
        if low <= int(code) <= high:
            return turkish if language == "tr" else english
    return "—"


def recording_conditions(events, language: str):
    """The weather the period's decisions were measured in, when it was recorded at all.

    Weather is stamped onto an event only while the operator has online weather on, and it
    is never back-filled, so most periods carry none and this returns None for them. The
    thresholds come from the retriever rather than being restated here: a page that flagged
    a recording the model did not would be two systems disagreeing in print.
    """
    try:
        from brain.local_rag import PRECIPITATION_CODE, WIND_NOISE_KMH
    except Exception:  # noqa: BLE001 - without the shared thresholds no judgement is offered
        return None

    deciding = [event for event in events if event.status in ("WATCH", "ALARM")]
    measured = [event for event in deciding
                if event.wind_kmh is not None or event.weather_code is not None]
    if not measured:
        return None

    def adverse(event) -> bool:
        windy = event.wind_kmh is not None and float(event.wind_kmh) >= WIND_NOISE_KMH
        wet = event.weather_code is not None and int(event.weather_code) >= PRECIPITATION_CODE
        return windy or wet

    flagged = [event for event in measured if adverse(event)]
    winds = [float(event.wind_kmh) for event in flagged if event.wind_kmh is not None]
    return {
        "records": measured,
        "flagged": flagged,
        "adverse": bool(flagged),
        "peak_wind": max(winds, default=0.0),
        "threshold": WIND_NOISE_KMH,
        "language": language,
    }


def _generator_label(report) -> str:
    """The language model behind the prose, under the name the panel shows."""
    fixed = {
        "deterministic-demo": "Waggle Yerel Rapor Motoru" if report.language == "tr" else "Waggle Local Report Engine",
        "safe-fallback": ("Deterministik yedek motor (yapay zekâ modeline ulaşılamadı)" if report.language == "tr"
                          else "Deterministic fallback engine (AI model was unreachable)"),
    }
    if report.generator in fixed:
        return fixed[report.generator]
    lowered = report.generator.lower()
    if "agent" in lowered:
        return "Agent Framework + Foundry Local"
    if "foundry" in lowered:
        return "Foundry Local · Phi"
    return report.generator


def hive_readings(report, events, hive_names: dict[str, str]) -> list[dict]:
    """One entry per hive in the report, each carrying its own latest measurement.

    Averaging the anomalous-window ratio across hives describes a hive nobody owns: a
    period holding 100%, 68% and 9% is not a period at 59%. Every number a reader acts on
    belongs to a named hive.
    """
    readings = []
    for hive_id in report.hive_ids:
        own = sorted((event for event in events if event.hive_id == hive_id), key=lambda event: event.timestamp)
        latest = own[-1] if own else None
        readings.append({
            "hive_id": hive_id,
            "name": hive_names.get(hive_id, hive_id),
            "status": latest.status if latest else None,
            "fraction": float(latest.anomaly_fraction) if latest else None,
            "consecutive": int(latest.consecutive_anomalies) if latest else 0,
            "records": len(own),
            "events": own,
        })
    return readings


def _reading_note(entry: dict, language: str) -> str:
    turkish = language == "tr"
    if entry["status"] is None:
        return "Bu dönemde kayıt alınmadı." if turkish else "No recording was taken in this period."
    if entry["status"] == "ALARM":
        return (f"Kalıcı akustik değişim. {entry['consecutive']} pencere kesintisiz aykırı." if turkish
                else f"Persistent acoustic change. {entry['consecutive']} consecutive anomalous windows.")
    if entry["status"] == "WATCH":
        return ("Gelişen bir değişim var, henüz süreklilik göstermiyor. 48 saat izleyin." if turkish
                else "A developing change that is not yet sustained. Watch it for 48 hours.")
    return ("Öğrenilmiş akustik profilin içinde. Eylem gerekmiyor." if turkish
            else "Within the learned acoustic profile. No action needed.")


def verdict(report, readings: list[dict]) -> dict:
    """The one sentence the report exists to deliver, and the deadline attached to it.

    The hive that needs opening used to appear first in a table on the second page. A
    reader holding the document at the apiary should not have to find it.
    """
    turkish = report.language == "tr"
    alarms = [entry for entry in readings if entry["status"] == "ALARM"]
    watches = [entry for entry in readings if entry["status"] == "WATCH"]
    if alarms:
        worst = max(alarms, key=lambda entry: entry["fraction"] or 0)
        headline = (f"{worst['name']} 24 saat içinde kontrol edilmeli." if turkish
                    else f"{worst['name']} needs a physical inspection within 24 hours.")
        reason = (
            f"Kaydın aykırı pencere oranı {fmt_pct(worst['fraction'] or 0, report.language)}; "
            f"{worst['consecutive']} pencere kesintisiz olağan profilin dışında kaldı."
            if turkish else
            f"The anomalous-window ratio was {fmt_pct(worst['fraction'] or 0, report.language)}, with "
            f"{worst['consecutive']} consecutive windows outside the learned profile."
        )
        if report.assessment is not None and report.assessment.queen_loss_compatible:
            reason += (" Bu örüntü kraliçe kaybıyla uyumlu olabilir; kesin tanı değildir, kararı fiziksel kontrol verir."
                       if turkish else
                       " The pattern may be compatible with queen loss; it is not a diagnosis, the inspection decides.")
        return {"headline": headline, "reason": reason, "state": "ALARM", "due": timedelta(hours=24)}
    if watches:
        if len(watches) == 1:
            headline = (f"{watches[0]['name']} 48 saat boyunca izlenmeli." if turkish
                        else f"{watches[0]['name']} should be watched for the next 48 hours.")
        else:
            headline = (f"{len(watches)} kovan izlemede; 48 saat boyunca takip edilmeli." if turkish
                        else f"{len(watches)} hives are on watch and should be followed for 48 hours.")
        reason = ("Alarm eşiği aşılmadı. Bir sonraki kayıt yönü gösterecek; oran yükselirse fiziksel kontrole geçin."
                  if turkish else
                  "No alarm threshold was crossed. The next recording shows the direction; if the ratio climbs, inspect.")
        return {"headline": headline, "reason": reason, "state": "WATCH", "due": timedelta(hours=48)}
    if any(entry["status"] for entry in readings):
        headline = ("Bu dönemde acil eylem gerekmiyor." if turkish
                    else "No immediate action is required for this period.")
        reason = ("Raporlanan kovanların tamamı öğrenilmiş akustik profilinin içinde kaldı. Olağan bakım takvimine devam edin."
                  if turkish else
                  "Every reported hive stayed within its learned acoustic profile. Continue the ordinary inspection schedule.")
        return {"headline": headline, "reason": reason, "state": "NORMAL", "due": None}
    headline = ("Bu dönemde değerlendirilecek kayıt bulunmuyor." if turkish
                else "There are no records to assess for this period.")
    reason = ("Kovanlardan ses kaydı gelmedi. Cihaz bağlantısını ve kayıt klasörünü kontrol edin."
              if turkish else
              "No audio arrived from the hives. Check the device connection and the recording folder.")
    return {"headline": headline, "reason": reason, "state": None, "due": None}


def decision_chain(report, events) -> list[tuple[str, str]]:
    """The named steps between a microphone and this page.

    A report that says only "Foundry Local" claims prose with nothing measured behind it.
    A step whose value was never recorded is left out rather than printed empty.
    """
    turkish = report.language == "tr"
    steps = []
    models = sorted({event.model for event in events if getattr(event, "model", None)})
    if models:
        steps.append(("Ölçüm · ONNX" if turkish else "Measurement · ONNX", ", ".join(models)))
    if report.grounding_sources:
        count = len(report.grounding_sources)
        steps.append(("Yerel kılavuz · RAG" if turkish else "Local guidance · RAG",
                      f"{count} kaynak" if turkish else f"{count} sources"))
    steps.append(("Yorum · dil modeli" if turkish else "Interpretation · language model", _generator_label(report)))
    assessment = report.assessment
    if assessment is not None and assessment.cross_check_model:
        agreed = ("aynı kararda" if turkish else "same decision") if assessment.cross_check_agreed else (
            "farklı karar, temkinli olan seçildi" if turkish else "disagreed; the cautious reading kept")
        steps.append(("Çapraz doğrulama" if turkish else "Cross-check", f"{assessment.cross_check_model} · {agreed}"))
    return steps


# --- drawing helpers -----------------------------------------------------------------

def _upper(text: str, language: str) -> str:
    """Uppercase a label the way its language does it."""
    if language == "tr":
        text = text.replace("i", "İ")
    return text.upper()


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    """Break a string into lines that fit, so a fixed-height box never clips a sentence."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if not current or stringWidth(trial, font, size) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _hexagon(canvas, cx: float, cy: float, radius: float) -> None:
    path = canvas.beginPath()
    for index in range(6):
        angle = math.radians(60 * index)
        x, y = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
        if index == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.close()
    canvas.drawPath(path, stroke=1, fill=0)


def _spaced(canvas, x: float, y: float, text: str, font: str, size: float, color: str, tracking: float) -> None:
    """Letter-spaced text. Tracking lives on the text object, not on the canvas."""
    from reportlab.lib.colors import HexColor

    canvas.saveState()
    text_object = canvas.beginText(x, y)
    text_object.setFont(font, size)
    text_object.setFillColor(HexColor(color))
    text_object.setCharSpace(tracking)
    text_object.textOut(text)
    canvas.drawText(text_object)
    canvas.restoreState()


def _label(canvas, x: float, y: float, text: str, fonts: dict, size: float = 6.2, color: str = INK_3) -> None:
    """A tracked small-caps label. The caller uppercases, because only it knows the language."""
    _spaced(canvas, x, y, text, fonts["mono"], size, color, 1.5)


def _pill(canvas, x: float, y: float, text: str, fonts: dict, fill: str, ink: str) -> float:
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase.pdfmetrics import stringWidth

    size = 6.4
    width = stringWidth(text, fonts["mono_bold"], size) + 12
    canvas.setFillColor(HexColor(fill))
    canvas.roundRect(x, y, width, 12.5, 1.5, stroke=0, fill=1)
    _spaced(canvas, x + 6, y + 4.2, text, fonts["mono_bold"], size, ink, 1.2)
    return width


class _Card(_Flowable):
    """Base for the drawn blocks, all of which own their full width and declare their height."""

    def __init__(self, width: float, height: float, fonts: dict):
        super().__init__()
        self.width = width
        self.height = height
        self.fonts = fonts

    def wrap(self, available_width, available_height):
        self.width = available_width
        return self.width, self.height


class HiveStrip(_Card):
    """Every hive in the period, side by side, each with its own measurement.

    This replaces the four aggregate tiles. The tiles printed one averaged percentage for
    the whole apiary, which is the one number in the document that describes no hive.
    """

    ROW_HEIGHT = 106

    def __init__(self, width: float, fonts: dict, readings: list[dict], language: str):
        self.readings = readings
        self.language = language
        self.columns = min(3, max(1, len(readings)))
        rows = math.ceil(len(readings) / self.columns) if readings else 1
        super().__init__(width, rows * self.ROW_HEIGHT, fonts)

    def draw(self):
        from reportlab.lib.colors import HexColor

        canvas = self.canv
        fonts = self.fonts
        names = STATE_NAMES["tr" if self.language == "tr" else "en"]
        column_width = self.width / self.columns
        for index, entry in enumerate(self.readings):
            row, column = divmod(index, self.columns)
            x = column * column_width
            top = self.height - row * self.ROW_HEIGHT
            bottom = top - self.ROW_HEIGHT
            state = entry["status"]
            ink, tint = STATE.get(state, (INK_3, PAPER_2))
            if state == "ALARM":
                canvas.setFillColor(HexColor(tint))
                canvas.rect(x, bottom, column_width, self.ROW_HEIGHT, stroke=0, fill=1)
            canvas.setStrokeColor(HexColor(INK))
            canvas.setLineWidth(0.9)
            canvas.line(x, top, x + column_width, top)
            canvas.setStrokeColor(HexColor(RULE))
            canvas.setLineWidth(0.5)
            canvas.line(x, bottom, x + column_width, bottom)
            if column:
                canvas.line(x, bottom, x, top)

            inner = x + 12
            usable = column_width - 24
            canvas.setFont(fonts["display_bold"], 11.5)
            canvas.setFillColor(HexColor(INK))
            canvas.drawString(inner, top - 20, entry["name"][:26])
            _label(canvas, inner, top - 31, entry["hive_id"], fonts, 6, INK_3)

            if state:
                _pill(canvas, inner, top - 50, names.get(state, state), fonts, tint if state != "ALARM" else ink,
                      ink if state != "ALARM" else "#FFFFFF")

            fraction = entry["fraction"]
            if fraction is not None:
                bar_y = top - 66
                canvas.setFillColor(HexColor(RULE_2))
                canvas.rect(inner, bar_y, usable, 4, stroke=0, fill=1)
                canvas.setFillColor(HexColor(ink))
                canvas.rect(inner, bar_y, max(1.2, usable * max(0.0, min(1.0, fraction))), 4, stroke=0, fill=1)
                from reportlab.pdfbase.pdfmetrics import stringWidth

                figure = fmt_pct(fraction, self.language)
                canvas.setFont(fonts["mono_bold"], 13)
                canvas.setFillColor(HexColor(INK))
                canvas.drawString(inner, bar_y - 17, figure)
                _label(canvas, inner + stringWidth(figure, fonts["mono_bold"], 13) + 9, bar_y - 16,
                       _upper("aykırı pencere" if self.language == "tr" else "anomalous window", self.language),
                       fonts, 5.6, INK_3)

            canvas.setFont(fonts["body"], 7.6)
            canvas.setFillColor(HexColor(INK_2))
            note_y = top - 92
            for line in _wrap(_reading_note(entry, self.language), fonts["body"], 7.6, usable)[:3]:
                canvas.drawString(inner, note_y, line)
                note_y -= 9.6


class ChainStrip(_Card):
    """The measurement, the retrieved guidance, the model and its cross-check, in order.

    Named steps make the document auditable: a reader can see what was measured and what
    was only inferred, instead of taking a paragraph of prose on trust.
    """

    def __init__(self, width: float, fonts: dict, steps: list[tuple[str, str]], language: str):
        self.steps = steps
        self.language = language
        super().__init__(width, 54, fonts)

    def draw(self):
        from reportlab.lib.colors import HexColor

        canvas = self.canv
        fonts = self.fonts
        count = max(1, len(self.steps))
        column = self.width / count
        canvas.setStrokeColor(HexColor(RULE))
        canvas.setLineWidth(0.5)
        canvas.rect(0, 0, self.width, self.height, stroke=1, fill=0)
        for index, (label, value) in enumerate(self.steps):
            x = index * column
            if index:
                canvas.setStrokeColor(HexColor(RULE))
                canvas.line(x, 6, x, self.height - 6)
                canvas.setStrokeColor(HexColor(INK_3))
                canvas.setLineWidth(0.7)
                canvas.line(x - 3.5, self.height / 2 + 3, x, self.height / 2)
                canvas.line(x - 3.5, self.height / 2 - 3, x, self.height / 2)
                canvas.setLineWidth(0.5)
            _label(canvas, x + 11, self.height - 17, _upper(label, self.language), fonts, 5.8, INK_3)
            canvas.setFont(fonts["body"], 7.8)
            canvas.setFillColor(HexColor(INK))
            text_y = self.height - 30
            for line in _wrap(value, fonts["body"], 7.8, column - 22)[:2]:
                canvas.drawString(x + 11, text_y, line)
                text_y -= 9.6


class Checklist(_Card):
    """The recommended steps as something you can tick in the field, with the time each has."""

    def __init__(self, width: float, fonts: dict, items: list[tuple[str, str]], language: str):
        self.items = items
        self.language = language
        self.line_heights: list[float] = []
        fonts_ready = fonts
        for text, _ in items:
            lines = len(_wrap(text, fonts_ready["bold"], 8.6, width - 118))
            self.line_heights.append(max(26.0, 14 + lines * 11.5))
        super().__init__(width, sum(self.line_heights) + 4, fonts)

    def draw(self):
        from reportlab.lib.colors import HexColor

        canvas = self.canv
        fonts = self.fonts
        y = self.height
        canvas.setStrokeColor(HexColor(RULE))
        canvas.setLineWidth(0.5)
        canvas.line(0, y, self.width, y)
        for (text, due), height in zip(self.items, self.line_heights):
            y -= height
            canvas.setStrokeColor(HexColor(RULE_2))
            canvas.setLineWidth(0.8)
            canvas.rect(2, y + height - 19, 9, 9, stroke=1, fill=0)
            canvas.setFont(fonts["bold"], 8.6)
            canvas.setFillColor(HexColor(INK))
            text_y = y + height - 18
            for line in _wrap(text, fonts["bold"], 8.6, self.width - 118):
                canvas.drawString(20, text_y, line)
                text_y -= 11.5
            if due:
                _label(canvas, self.width - 92, y + height - 18, _upper(due, self.language), fonts, 6, INK_3)
            canvas.setStrokeColor(HexColor(RULE))
            canvas.setLineWidth(0.5)
            canvas.line(0, y, self.width, y)


class RecordCalendar(_Card):
    """Where the period's recordings actually landed, one lane per hive.

    A line chart drawn through a single point per hive produced three flat lines and an
    interpretation claiming no change of direction — which is what "no data" looks like,
    not what it means. Sparse periods get a calendar and a plain sentence instead.
    """

    LANE = 30

    def __init__(self, width: float, fonts: dict, readings: list[dict], start, end, language: str):
        self.readings = readings
        self.start = start
        self.end = end
        self.language = language
        self.days = max(1, min(14, (end.date() - start.date()).days + 1))
        super().__init__(width, len(readings) * self.LANE + 26, fonts)

    def draw(self):
        from reportlab.lib.colors import HexColor

        canvas = self.canv
        fonts = self.fonts
        name_width = 108
        value_width = 42
        track_x = name_width
        track_width = self.width - name_width - value_width
        cell = track_width / self.days
        y = self.height - 4
        canvas.setStrokeColor(HexColor(RULE))
        canvas.setLineWidth(0.5)
        canvas.line(0, y, self.width, y)
        for entry in self.readings:
            y -= self.LANE
            canvas.setFont(fonts["bold"], 8.4)
            canvas.setFillColor(HexColor(INK))
            canvas.drawString(0, y + 15, entry["name"][:22])
            _label(canvas, 0, y + 5, entry["hive_id"], fonts, 5.8, INK_3)

            occupied = {min(self.days - 1, max(0, (event.timestamp.date() - self.start.date()).days)): event
                        for event in entry["events"]}
            for day in range(self.days):
                left = track_x + day * cell
                if day not in occupied:
                    canvas.setFillColor(HexColor(PAPER_2))
                    canvas.rect(left + 1, y + 4, cell - 2, 18, stroke=0, fill=1)
                canvas.setStrokeColor(HexColor(RULE))
                canvas.setLineWidth(0.4)
                canvas.rect(left, y + 4, cell, 18, stroke=1, fill=0)
                event = occupied.get(day)
                if event is not None:
                    ink, tint = STATE.get(event.status, (INK_3, PAPER_2))
                    if event.status == "ALARM":
                        canvas.setFillColor(HexColor(tint))
                        canvas.circle(left + cell / 2, y + 13, 6.4, stroke=0, fill=1)
                    canvas.setFillColor(HexColor(ink))
                    canvas.circle(left + cell / 2, y + 13, 3.6, stroke=0, fill=1)

            if entry["fraction"] is not None:
                canvas.setFont(fonts["mono"], 8.6)
                canvas.setFillColor(HexColor(INK))
                canvas.drawRightString(self.width, y + 10, fmt_pct(entry["fraction"], self.language))
            canvas.setStrokeColor(HexColor(RULE))
            canvas.setLineWidth(0.5)
            canvas.line(0, y, self.width, y)

        for day in range(self.days):
            if self.days > 8 and day % 2:
                continue
            stamp = (self.start + timedelta(days=day)).strftime("%d.%m")
            canvas.setFont(fonts["mono"], 5.8)
            canvas.setFillColor(HexColor(INK_3))
            canvas.drawCentredString(track_x + day * cell + cell / 2, y - 12, stamp)


class TrendLines(_Card):
    """The anomalous-window ratio over time, drawn only once a hive has enough points to have one."""

    def __init__(self, width: float, fonts: dict, readings: list[dict], start, end, language: str):
        self.readings = [entry for entry in readings if entry["records"]]
        self.start = start
        self.end = end
        self.language = language
        super().__init__(width, 190, fonts)

    def draw(self):
        from reportlab.lib.colors import HexColor

        canvas = self.canv
        fonts = self.fonts
        left, bottom = 30, 44
        plot_width = self.width - left - 8
        plot_height = self.height - bottom - 34
        span = max(1.0, (self.end - self.start).total_seconds())
        for level in (0, 0.25, 0.5, 0.75, 1):
            y = bottom + level * plot_height
            canvas.setStrokeColor(HexColor(RULE if level else INK_3))
            canvas.setLineWidth(0.4)
            canvas.line(left, y, left + plot_width, y)
            canvas.setFont(fonts["mono"], 5.8)
            canvas.setFillColor(HexColor(INK_3))
            canvas.drawRightString(left - 5, y - 2, fmt_pct(level, self.language))
        legend_x = left
        for entry in self.readings:
            ink, _ = STATE.get(entry["status"], (INK_3, PAPER_2))
            points = []
            for event in entry["events"]:
                offset = (event.timestamp - self.start).total_seconds() / span
                x = left + max(0.0, min(1.0, offset)) * plot_width
                y = bottom + max(0.0, min(1.0, float(event.anomaly_fraction))) * plot_height
                points.append((x, y))
            canvas.setStrokeColor(HexColor(ink))
            canvas.setLineWidth(1.6)
            for start_point, end_point in zip(points, points[1:]):
                canvas.line(start_point[0], start_point[1], end_point[0], end_point[1])
            for x, y in points:
                canvas.setFillColor(HexColor("#FFFFFF"))
                canvas.circle(x, y, 2.6, stroke=1, fill=1)
            # Two hives in the same state share a colour, so each line is named where it ends.
            if points:
                _label(canvas, min(points[-1][0] + 6, left + plot_width - 16), points[-1][1] - 2,
                       entry["hive_id"], fonts, 5.6, ink)
            canvas.setFillColor(HexColor(ink))
            canvas.rect(legend_x, self.height - 14, 10, 3, stroke=0, fill=1)
            canvas.setFont(fonts["body"], 7)
            canvas.setFillColor(HexColor(INK_2))
            canvas.drawString(legend_x + 14, self.height - 15, entry["name"][:22])
            legend_x += 120
        canvas.setFont(fonts["mono"], 5.8)
        canvas.setFillColor(HexColor(INK_3))
        canvas.drawString(left, bottom - 14, self.start.strftime("%d.%m"))
        canvas.drawRightString(left + plot_width, bottom - 14, self.end.strftime("%d.%m"))


def build_report_pdf(report, events, hive_names: dict[str, str]) -> bytes:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdfcanvas
    from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    fonts = _fonts()
    turkish = report.language == "tr"
    output = BytesIO()

    type_labels = ({"event": "Olay raporu", "daily": "Günlük rapor", "weekly": "Haftalık rapor"} if turkish
                   else {"event": "Event report", "daily": "Daily report", "weekly": "Weekly report"})
    report_label = type_labels[report.report_type]
    period = f"{report.period_start:%d.%m.%Y} – {report.period_end:%d.%m.%Y}"

    ordered = sorted(events, key=lambda event: event.timestamp)
    readings = hive_readings(report, ordered, hive_names)
    decision = verdict(report, readings)
    conditions = recording_conditions(ordered, report.language)
    if conditions and conditions["adverse"]:
        detail = []
        if conditions["peak_wind"]:
            detail.append(f"rüzgâr {conditions['peak_wind']:.0f} km/s" if turkish
                          else f"wind at {conditions['peak_wind']:.0f} km/h")
        if any(event.weather_code is not None and int(event.weather_code) >= 51
               for event in conditions["flagged"]):
            detail.append("yağış" if turkish else "precipitation")
        # The caveat lowers confidence in the measurement without lowering the priority of
        # the inspection: a windy recording is a reason to measure again, never a reason to
        # leave a hive shut.
        decision["reason"] += (
            f" Ölçüm koşulu uyarısı: bu kararı veren kayıt {' ve '.join(detail)} ölçülen bir anda alındı. "
            "Rüzgâr ve yağmur mikrofona kendi sesini bindirir, oran olduğundan yüksek çıkmış olabilir. "
            "Bu, kontrolü ertelemek için bir sebep değildir; ölçümü sakin havada da tekrarlayın."
            if turkish else
            f" Measurement caveat: the deciding record was taken with {' and '.join(detail)}. "
            "Wind and rain lay their own sound over the microphone, so the ratio may read high. "
            "This is not a reason to delay the inspection; repeat the recording in calm weather as well."
        )
    counts = Counter(event.status for event in ordered)

    left_margin = right_margin = 20 * mm
    frame_width = A4[0] - left_margin - right_margin

    class NumberedCanvas(pdfcanvas.Canvas):
        """Page furniture drawn on every sheet, with the page count known before it is printed."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self._furniture(total)
                super().showPage()
            super().save()

        def _furniture(self, total: int):
            top = A4[1] - 17 * mm
            self.setStrokeColor(HexColor(INK))
            self.setLineWidth(1.1)
            _hexagon(self, left_margin + 6, top + 1.5, 7.4)
            self.setLineWidth(0.6)
            _hexagon(self, left_margin + 6, top + 1.5, 3.4)
            from reportlab.pdfbase.pdfmetrics import stringWidth

            _spaced(self, left_margin + 20, top - 3, "WAGGLE", fonts["display_bold"], 13, INK, 1.6)
            wordmark = stringWidth("WAGGLE", fonts["display_bold"], 13) + 6 * 1.6
            _label(self, left_margin + 28 + wordmark, top - 2.5,
                   _upper("Edge AI kovan izleme" if turkish else "Edge AI hive monitoring", report.language),
                   fonts, 5.8, INK_3)
            self.setFont(fonts["body"], 7.4)
            self.setFillColor(HexColor(INK_2))
            self.drawRightString(A4[0] - right_margin, top + 3, f"{report_label} · {period}")
            self.setFont(fonts["mono"], 6.6)
            self.setFillColor(HexColor(INK_3))
            self.drawRightString(A4[0] - right_margin, top - 7,
                                 f"{'Sayfa' if turkish else 'Page'} {self._pageNumber} / {total}")
            self.setStrokeColor(HexColor(INK))
            self.setLineWidth(0.9)
            self.line(left_margin, top - 15, A4[0] - right_margin, top - 15)

            base = 14 * mm
            self.setStrokeColor(HexColor(RULE))
            self.setLineWidth(0.5)
            self.line(left_margin, base + 12, A4[0] - right_margin, base + 12)
            self.setFont(fonts["body"], 6.6)
            self.setFillColor(HexColor(INK_3))
            self.drawString(left_margin, base,
                            "Yerel işleme · ses kaydı cihazdan çıkmadı" if turkish
                            else "Local processing · no audio left the device")
            self.drawRightString(A4[0] - right_margin, base,
                                 f"{'Üretim' if turkish else 'Generated'}: {report.created_at:%d.%m.%Y %H:%M}"
                                 if getattr(report, "created_at", None) else "Waggle")

    document = SimpleDocTemplate(
        output, pagesize=A4,
        leftMargin=left_margin, rightMargin=right_margin,
        topMargin=30 * mm, bottomMargin=22 * mm,
        title=f"Waggle {report_label}", author="Waggle",
    )

    headline = ParagraphStyle("Headline", fontName=fonts["display"], fontSize=19, leading=25.5,
                              textColor=HexColor(INK), spaceAfter=0)
    section = ParagraphStyle("Section", fontName=fonts["display_bold"], fontSize=13, leading=18,
                             textColor=HexColor(INK), spaceBefore=0, spaceAfter=3)
    eyebrow = ParagraphStyle("Eyebrow", fontName=fonts["mono"], fontSize=6.4, leading=10,
                             textColor=HexColor(INK_3), spaceAfter=4)
    body = ParagraphStyle("Body", fontName=fonts["body"], fontSize=9.2, leading=15.5,
                          textColor=HexColor(INK_2), spaceAfter=0)
    lead = ParagraphStyle("Lead", parent=body, fontName=fonts["display"], fontSize=11, leading=18,
                          textColor=HexColor(INK))
    caption = ParagraphStyle("Caption", parent=body, fontSize=7.8, leading=12.5, textColor=HexColor(INK_3))
    note = ParagraphStyle("Note", parent=body, fontSize=8.4, leading=14, backColor=HexColor(PAPER_2),
                          borderColor=HexColor(INK_3), borderWidth=0, borderPadding=9,
                          leftIndent=3, spaceBefore=4)

    def heading(text: str, eyebrow_text: str | None = None) -> list:
        parts = []
        if eyebrow_text:
            parts.append(Paragraph(escape(_upper(eyebrow_text, report.language)), eyebrow))
        parts.append(Paragraph(text, section))
        return parts

    story: list = []

    # --- the verdict --------------------------------------------------------------
    state_ink, state_tint = STATE.get(decision["state"] or "", (INK_3, PAPER_2))
    verdict_cell = [
        Paragraph(escape(decision["headline"]), headline),
        Spacer(1, 4),
        Paragraph(escape(decision["reason"]), body),
    ]
    if decision["due"] is not None:
        deadline = report.period_end + decision["due"]
        verdict_cell += [
            Spacer(1, 7),
            Paragraph(
                f"<font face='{fonts['mono_bold']}' size='6.6' color='{state_ink}'>"
                f"{'SON TARİH' if turkish else 'DUE BY'} · {deadline:%d.%m.%Y %H:%M}</font>",
                caption,
            ),
        ]
    story.append(Table(
        [[ "", verdict_cell ]], colWidths=[3.2, frame_width - 3.2],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), HexColor(state_ink)),
            ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 0),
            ("LEFTPADDING", (1, 0), (1, 0), 14), ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]),
    ))
    story.append(Spacer(1, 26))

    # --- hive by hive -------------------------------------------------------------
    story += heading("Kovanlar" if turkish else "Hives",
                     "dönemin son ölçümü" if turkish else "latest measurement of the period")
    story.append(Spacer(1, 8))
    story.append(HiveStrip(frame_width, fonts, readings, report.language))
    story.append(Spacer(1, 24))

    # --- what to do ----------------------------------------------------------------
    if report.recommendations:
        due_labels = {
            "ALARM": ("24 saat", "24 hours"),
            "WATCH": ("48 saat", "48 hours"),
        }
        default_due = due_labels.get(decision["state"] or "", ("", ""))
        due_text = default_due[0] if turkish else default_due[1]
        items = [(text, due_text if index == 0 else "") for index, text in enumerate(report.recommendations)]
        story += heading("Yapılacaklar" if turkish else "What to do",
                         "sahada işaretlenmek üzere" if turkish else "to tick off in the field")
        story.append(Spacer(1, 8))
        story.append(Checklist(frame_width, fonts, items, report.language))
        story.append(Spacer(1, 24))

    # --- model decision and counts --------------------------------------------------
    priorities = ({"routine": "Rutin", "watch": "İzleme", "immediate": "Acil"} if turkish
                  else {"routine": "Routine", "watch": "Watch", "immediate": "Immediate"})
    patterns = {
        "within_baseline": "Normal aralıkta" if turkish else "Within baseline",
        "developing_acoustic_change": "Gelişen akustik değişim" if turkish else "Developing acoustic change",
        "persistent_acoustic_change": "Kalıcı akustik değişim" if turkish else "Persistent acoustic change",
    }
    action_names = {
        "continue_monitoring": "İzlemeye devam" if turkish else "Keep monitoring",
        "record_again": "Kaydı tekrarla" if turkish else "Record again",
        "inspect_hive": "Kovanı fiziksel kontrol et" if turkish else "Inspect the hive",
        "check_queen": "Kraliçeyi doğrula" if turkish else "Verify the queen",
    }
    # Rows the verdict and the checklist already carry — the queen-loss caveat, the
    # recommended action codes — are not repeated here; the colophon holds what the
    # sentences above do not say.
    colophon = [[("Toplam kayıt" if turkish else "Total records"), str(len(ordered))]]
    if ordered:
        colophon.append([("Alarm" if turkish else "Alarm"), f"{counts['ALARM']} / {len(ordered)}"])
        colophon.append([("İzleme" if turkish else "Watch"), f"{counts['WATCH']} / {len(ordered)}"])
    assessment = report.assessment
    if assessment is not None:
        colophon.append([("Öncelik" if turkish else "Priority"),
                         priorities.get(assessment.priority, assessment.priority)])
        colophon.append([("Örüntü" if turkish else "Pattern"),
                         patterns.get(assessment.pattern, assessment.pattern)])
        colophon.append([("Fiziksel kontrol" if turkish else "Physical inspection"),
                         ("Gerekli" if turkish else "Required") if assessment.inspection_required
                         else ("Şu an gerekmiyor" if turkish else "Not required now")])

    summary_cell = [Paragraph("DÖNEM DEĞERLENDİRMESİ" if turkish else "PERIOD ASSESSMENT", eyebrow),
                    Spacer(1, 2), Paragraph(escape(report.summary), lead)]
    colophon_key = ParagraphStyle("ColophonKey", parent=body, fontSize=7.6, leading=11.5,
                                  textColor=HexColor(INK_3))
    colophon_value = ParagraphStyle("ColophonValue", parent=body, fontName=fonts["bold"], fontSize=7.6,
                                    leading=11.5, textColor=HexColor(INK), alignment=2)
    colophon_width = frame_width * 0.40 - 14
    # Both cells are paragraphs so a long label wraps instead of running under its value.
    colophon_table = Table(
        [[Paragraph(escape(key), colophon_key), Paragraph(escape(value), colophon_value)]
         for key, value in colophon],
        colWidths=[colophon_width * 0.52, colophon_width * 0.48],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, HexColor(RULE)),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, -1), 8),
            ("RIGHTPADDING", (1, 0), (1, -1), 0),
        ]),
    )
    story.append(Table(
        [[summary_cell, colophon_table]], colWidths=[frame_width * 0.60, frame_width * 0.40],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 26),
            ("LEFTPADDING", (1, 0), (1, 0), 14), ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ("LINEBEFORE", (1, 0), (1, 0), 0.5, HexColor(RULE)),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]),
    ))

    # --- evidence -------------------------------------------------------------------
    story.append(PageBreak())

    steps = decision_chain(report, ordered)
    if steps:
        story += heading("Karar zinciri" if turkish else "Decision chain",
                         "ölçümden yoruma" if turkish else "from measurement to interpretation")
        story.append(Spacer(1, 8))
        story.append(ChainStrip(frame_width, fonts, steps, report.language))
        story.append(Spacer(1, 26))

    if ordered:
        trended = [entry for entry in readings if entry["records"] >= 5]
        if trended:
            story += heading("Akustik eğilim" if turkish else "Acoustic trend",
                             "ölçüm takvimi" if turkish else "measurement timeline")
            story.append(Paragraph(
                "Aykırı ses oranının dönem içindeki değişimi" if turkish
                else "The anomalous-audio ratio across the period", caption))
            story.append(Spacer(1, 10))
            story.append(TrendLines(frame_width, fonts, readings, report.period_start, report.period_end,
                                    report.language))
        else:
            story += heading("Ölçüm takvimi" if turkish else "Measurement timeline",
                             "kayıtlar dönemin neresine düştü" if turkish else "where the records landed")
            story.append(Paragraph(
                "Her satır bir kovan · her nokta bir akustik kayıt · taralı günlerde ölçüm yok" if turkish
                else "One lane per hive · one dot per acoustic record · shaded days hold no measurement",
                caption))
            story.append(Spacer(1, 12))
            story.append(RecordCalendar(frame_width, fonts, readings, report.period_start, report.period_end,
                                        report.language))
            most = max((entry["records"] for entry in readings), default=0)
            story.append(Spacer(1, 6))
            story.append(Paragraph(
                (f"<b>Eğilim çizilmedi.</b> Bu dönemde bir kovan için en çok {most} kayıt alındı; "
                 "zaman içindeki yön bu kadar ölçümle hesaplanamaz. Eğilim çizgisi kovan başına en az "
                 "beş kayıtta açılır. Bu dönemin sonucu bir yön değil, bir andır."
                 if turkish else
                 f"<b>No trend was drawn.</b> The busiest hive holds {most} record(s) in this period, which is "
                 "not enough to compute a direction over time. The trend line opens at five records per hive. "
                 "What this period reports is a moment, not a direction."),
                note))
        story.append(Spacer(1, 26))

    # --- every record ----------------------------------------------------------------
    if ordered:
        shown = sorted(ordered, key=lambda event: event.timestamp, reverse=True)[:40]
        rows, widths = notable_record_rows(shown, report.language, hive_names)
        scale = frame_width / (sum(widths) * mm)
        table_style = [
            ("FONTNAME", (0, 0), (-1, 0), fonts["mono"]), ("FONTNAME", (0, 1), (-1, -1), fonts["body"]),
            ("FONTSIZE", (0, 0), (-1, 0), 6.2), ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (-1, 0), HexColor(INK_3)), ("TEXTCOLOR", (0, 1), (-1, -1), HexColor(INK)),
            ("LINEBELOW", (0, 0), (-1, 0), 0.9, HexColor(INK)),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, HexColor(RULE)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (0, -1), 4), ("RIGHTPADDING", (-1, 0), (-1, -1), 4),
        ]
        for index, event in enumerate(shown, start=1):
            ink, tint = STATE.get(event.status, (INK_3, PAPER_2))
            table_style.append(("TEXTCOLOR", (2, index), (2, index), HexColor(ink)))
            table_style.append(("FONTNAME", (2, index), (2, index), fonts["mono_bold"]))
            if event.status == "ALARM":
                table_style.append(("BACKGROUND", (0, index), (-1, index), HexColor(tint)))
                table_style.append(("FONTNAME", (1, index), (1, index), fonts["bold"]))
        story += heading("Kayıtlar" if turkish else "Records",
                         "dönemin tamamı" if turkish else "the complete period")
        story.append(Spacer(1, 8))
        story.append(Table(rows, repeatRows=1, colWidths=[width * mm * scale for width in widths],
                           style=TableStyle(table_style)))
        omitted = len(ordered) - len(shown)
        severity_note = (
            " Sapma şiddeti, sesin normal aralığın ne kadar dışına çıktığını gösterir; aykırı pencere oranı ise "
            "kaydın ne kadarının dışarıda kaldığını."
            if turkish else
            " Severity is how far the sound moved outside its normal range; the anomalous-window ratio is how much "
            "of the recording fell outside it."
        ) if len(widths) == 6 else ""
        tail = (
            (f"Dönemin en yeni {len(shown)} kaydı listelendi; {omitted} kayıt daha var. " if omitted else "")
            + "Kayıtların tamamı için panelin Dışa Aktar bölümünü kullanın." + severity_note
            if turkish else
            (f"The {len(shown)} most recent records are listed; {omitted} more exist. " if omitted else "")
            + "Use the panel's Export section for the complete set." + severity_note
        )
        story.append(Spacer(1, 7))
        story.append(Paragraph(tail, caption))
        story.append(Spacer(1, 26))

    # --- how far the measurements can be trusted, and what the field found ---------------
    story.append(PageBreak())

    # Printed only when weather was actually stamped on a decision-bearing record. With
    # online weather off nothing is recorded, and an empty section claiming "no data" is
    # worse than no section: it implies the question was asked.
    if conditions:
        block = heading("Ölçüm koşulları" if turkish else "Measurement conditions",
                        "karar veren kayıtlar alınırken hava" if turkish
                        else "the weather while the deciding records were taken")
        block.append(Spacer(1, 8))
        header = (["Zaman", "Kovan", "Durum", "Rüzgâr", "Hava"] if turkish
                  else ["Time", "Hive", "Status", "Wind", "Sky"])
        names = STATE_NAMES["tr" if turkish else "en"]
        rows = [header]
        for event in conditions["records"]:
            rows.append([
                event.timestamp.strftime("%d.%m %H:%M"),
                hive_names.get(event.hive_id, event.hive_id),
                names.get(event.status, event.status),
                "—" if event.wind_kmh is None else f"{float(event.wind_kmh):.0f} km/{'s' if turkish else 'h'}",
                weather_label(event.weather_code, report.language),
            ])
        widths = [26, 48, 24, 26, 44]
        scale = frame_width / (sum(widths) * mm)
        condition_style = [
            ("FONTNAME", (0, 0), (-1, 0), fonts["mono"]), ("FONTNAME", (0, 1), (-1, -1), fonts["body"]),
            ("FONTSIZE", (0, 0), (-1, 0), 6.2), ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (-1, 0), HexColor(INK_3)), ("TEXTCOLOR", (0, 1), (-1, -1), HexColor(INK)),
            ("LINEBELOW", (0, 0), (-1, 0), 0.9, HexColor(INK)),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, HexColor(RULE)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (0, -1), 4), ("RIGHTPADDING", (-1, 0), (-1, -1), 4),
        ]
        for index, event in enumerate(conditions["records"], start=1):
            ink, tint = STATE.get(event.status, (INK_3, PAPER_2))
            condition_style.append(("TEXTCOLOR", (2, index), (2, index), HexColor(ink)))
            condition_style.append(("FONTNAME", (2, index), (2, index), fonts["mono_bold"]))
            if event in conditions["flagged"]:
                condition_style.append(("BACKGROUND", (0, index), (-1, index), HexColor(STATE["WATCH"][1])))
                condition_style.append(("FONTNAME", (3, index), (4, index), fonts["bold"]))
        block.append(Table(rows, repeatRows=1, colWidths=[width * mm * scale for width in widths],
                           style=TableStyle(condition_style)))
        block.append(Spacer(1, 6))
        limit = conditions["threshold"]
        if conditions["adverse"]:
            block.append(Paragraph(
                (f"<b>Ölçüm koşulu şüpheli.</b> İşaretli kayıtlar {limit:.0f} km/s üzerinde rüzgârda veya yağış "
                 "altında alındı. Bu koşullarda mikrofon kendi gürültüsünü kaydeder ve aykırılık oranı koloninin "
                 "sesinden bağımsız olarak yükselebilir. Kararı çöpe atmayın; sakin bir havada ikinci bir ölçüm alın."
                 if turkish else
                 f"<b>Measurement conditions are questionable.</b> The marked records were taken above {limit:.0f} km/h "
                 "of wind or under precipitation. In those conditions the microphone records its own noise and the "
                 "anomaly ratio can rise independently of the colony. Do not discard the decision; take a second "
                 "measurement in calm weather."),
                note))
        else:
            block.append(Paragraph(
                (f"Karar veren kayıtların tamamı {limit:.0f} km/s altındaki rüzgârda ve yağışsız havada alındı; "
                 "ölçüm koşulu, oranı açıklayan bir etken değil."
                 if turkish else
                 f"Every deciding record was taken below {limit:.0f} km/h of wind and without precipitation; "
                 "the conditions do not explain the ratio."),
                caption))
        story.append(KeepTogether(block))
        story.append(Spacer(1, 26))

    # --- field inspections -------------------------------------------------------------
    inspections = Counter(event.inspection_result for event in ordered if event.acknowledged_at)
    inspection_labels = (("Sorun doğrulandı", "Sorun görülmedi", "Belirsiz") if turkish
                         else ("Issue confirmed", "No issue found", "Inconclusive"))
    inspection_row = [inspections["issue_confirmed"], inspections["no_issue_found"], inspections["uncertain"]]
    story += heading("Saha kontrol sonuçları" if turkish else "Field inspection outcomes",
                     "modelin bir sonraki eşiğini besler" if turkish else "this feeds the model's next threshold")
    story.append(Spacer(1, 8))
    if any(inspection_row):
        story.append(Table(
            [list(inspection_labels), [str(value) for value in inspection_row]],
            colWidths=[frame_width / 3] * 3,
            style=TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), fonts["body"]), ("FONTNAME", (0, 1), (-1, 1), fonts["mono_bold"]),
                ("FONTSIZE", (0, 0), (-1, 0), 7.4), ("FONTSIZE", (0, 1), (-1, 1), 15),
                ("TEXTCOLOR", (0, 0), (-1, 0), HexColor(INK_3)), ("TEXTCOLOR", (0, 1), (-1, 1), HexColor(INK)),
                ("LINEABOVE", (0, 0), (-1, 0), 0.9, HexColor(INK)),
                ("LINEBELOW", (0, 1), (-1, 1), 0.5, HexColor(RULE)),
                ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]),
        ))
    else:
        story.append(Paragraph(
            "Bu dönemde fiziksel olarak kontrol edilen alarm bulunmuyor. Kontrolden sonra panelden "
            "“kontrol edildi” işaretlemesi bu bölümü doldurur." if turkish
            else "No alarm was physically inspected during this period. Marking an inspection in the panel "
                 "fills this section in.",
            body))
    story.append(Spacer(1, 26))

    # --- the guidance the decision rests on ----------------------------------------------
    if report.grounding_sources:
        try:
            from brain.local_rag import guidance_title, load_knowledge

            notes = {entry["id"]: (guidance_title(entry, report.language), entry[report.language])
                     for entry in load_knowledge()}
        except Exception:  # noqa: BLE001 - a missing guidance file must not lose the report
            notes = {}
        cards = []
        for source in report.grounding_sources:
            # The note's own name leads. The id is the citation a reader follows back into
            # the base, so it stays — under the text, at the size a reference is read at.
            title, text = notes.get(source, (source, "—"))
            card = [
                Paragraph(f"<font face='{fonts['bold']}' size='9' color='{INK}'>{escape(title)}</font>", body),
                Spacer(1, 4),
                Paragraph(escape(text), body),
            ]
            # The same slug twice tells a reader nothing the first one did not, so the
            # citation is printed only where the note has a name of its own.
            if title != source:
                card += [Spacer(1, 5),
                         Paragraph(f"<font face='{fonts['mono']}' size='6.6' color='{INK_3}'>{escape(source)}</font>", caption)]
            cards.append(card)
        # Two columns of flowing text: the guidance used to sit in fixed-height cells that
        # cut sentences off mid-word.
        pairs = [cards[index:index + 2] for index in range(0, len(cards), 2)]
        grid = [pair if len(pair) == 2 else [pair[0], ""] for pair in pairs]
        story += heading("Kararın dayandığı yerel kılavuz" if turkish else "Local guidance the decision rests on",
                         "cihazdaki bilgi tabanı · rag" if turkish else "on-device knowledge base · rag")
        story.append(Spacer(1, 8))
        story.append(Table(
            grid, colWidths=[frame_width / 2 - 12, frame_width / 2 - 12],
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEABOVE", (0, 0), (-1, -1), 0.4, HexColor(RULE)),
                ("TOPPADDING", (0, 0), (-1, -1), 11), ("BOTTOMPADDING", (0, 0), (-1, -1), 13),
                ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (0, 0), (0, -1), 24),
                ("LEFTPADDING", (1, 0), (1, -1), 24), ("RIGHTPADDING", (1, 0), (1, -1), 0),
            ]),
        ))
        story.append(Spacer(1, 20))

    story.append(Paragraph(
        "Bu rapor erken uyarı ve karar desteği sağlar; fiziksel kovan incelemesinin yerini almaz."
        if turkish else
        "This report provides early warning and decision support; it does not replace physical hive inspection.",
        caption))

    document.build(story, canvasmaker=NumberedCanvas)
    return output.getvalue()
