import csv
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def text(v):
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return format(v, "f")
    return str(v)


def is_num(v):
    return isinstance(v, (Decimal, int)) and not isinstance(v, bool)


def to_csv(report, name):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{name}.csv"'
    resp.write("\ufeff")                       # lets Excel read UTF-8 correctly
    w = csv.writer(resp)
    w.writerow(report.headers)
    for r in report.rows:
        w.writerow([text(c) for c in r])
    if report.totals:
        w.writerow([text(c) for c in report.totals])
    return resp


def to_xlsx(report, name, period):
    wb = Workbook()
    ws = wb.active
    ws.title = report.title[:31].replace("/", "-")
    ws.append([report.title])
    ws.append([period])
    ws.append([])
    ws.append(list(report.headers))
    ws["A1"].font = Font(bold=True, size=13)
    for c in ws[4]:
        c.font = Font(bold=True)
    for r in report.rows:
        ws.append(list(r))                     # Decimals are stored as numbers
    if report.totals:
        ws.append(list(report.totals))
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
    for i, h in enumerate(report.headers, 1):
        longest = max([len(text(h))] + [len(text(r[i - 1])) for r in report.rows])
        ws.column_dimensions[get_column_letter(i)].width = min(longest + 2, 40)
    buf = BytesIO()
    wb.save(buf)
    resp = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{name}.xlsx"'
    return resp


def to_pdf(report, name, period):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title=report.title,
                            leftMargin=10 * mm, rightMargin=10 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm)
    ss = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=7, leading=9)
    bold = ParagraphStyle("bold", parent=small, fontName="Helvetica-Bold")
    num = ParagraphStyle("num", parent=small, alignment=2)
    numb = ParagraphStyle("numb", parent=bold, alignment=2)

    def P(v, style):
        return Paragraph(escape(text(v)), style)

    data = [[P(h, bold) for h in report.headers]]
    for r in report.rows:
        data.append([P(c, num if is_num(c) else small) for c in r])
    if report.totals:
        data.append([P(c, numb if is_num(c) else bold) for c in report.totals])

    n = len(report.headers)
    table = Table(data, colWidths=[doc.width / n] * n, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
             ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    if report.totals:
        style.append(("BACKGROUND", (0, -1), (-1, -1), colors.whitesmoke))
    table.setStyle(TableStyle(style))

    els = [Paragraph(f"<b>{escape(report.title)}</b>", ss["Heading2"]),
           Paragraph(escape(period), ss["Normal"]), Spacer(1, 3 * mm)]
    if report.note:
        els += [Paragraph(escape(report.note), small), Spacer(1, 3 * mm)]
    els.append(table if report.rows else Paragraph("No data for this period.", ss["Normal"]))
    doc.build(els)
    resp = HttpResponse(buf.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{name}.pdf"'
    return resp