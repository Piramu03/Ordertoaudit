from io import BytesIO
from xml.sax.saxutils import escape

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def money(x):
    return f"{x:,.2f}"


def plain(d):
    return format(d.normalize(), "f")


def build_invoice_pdf(invoice):
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title=invoice.number,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
    )
    ss = getSampleStyleSheet()
    normal = ss["Normal"]
    cust = invoice.customer
    intra = invoice.place_of_supply == settings.FACTORY_STATE_CODE

    title = "TAX INVOICE" + (" - CANCELLED" if invoice.status == "cancelled" else "")
    els = [
        Paragraph(f"<b>{escape(settings.FACTORY_NAME)}</b>", ss["Title"]),
        Paragraph(
            f"GSTIN: {settings.FACTORY_GSTIN} &nbsp;|&nbsp; State code: {settings.FACTORY_STATE_CODE}",
            normal),
        Spacer(1, 5 * mm),
        Paragraph(title, ss["Heading2"]),
    ]

    info = Table([
        ["Invoice no:", invoice.number, "Date:", invoice.date.strftime("%d-%m-%Y")],
        ["Place of supply:", f"{cust.state} ({invoice.place_of_supply})",
         "Order:", f"ORD-{invoice.order_id}"],
    ], colWidths=[32 * mm, 60 * mm, 20 * mm, 60 * mm])
    els += [info, Spacer(1, 4 * mm)]

    els.append(Paragraph(
        f"<b>Bill to:</b> {escape(cust.name)}<br/>"
        f"{escape(cust.address or '')}<br/>"
        f"GSTIN: {cust.gstin or 'Unregistered'}", normal))
    els.append(Spacer(1, 5 * mm))

    if intra:
        head = ["#", "Item", "HSN", "Qty", "Rate", "Taxable", "CGST", "SGST"]
        widths = [8, 50, 22, 16, 20, 24, 20, 20]
    else:
        head = ["#", "Item", "HSN", "Qty", "Rate", "Taxable", "IGST"]
        widths = [8, 56, 24, 18, 22, 26, 26]
    rows = [head]
    for n, l in enumerate(invoice.lines.select_related("item"), 1):
        row = [n, f"{l.item.name} (GST {plain(l.gst_rate)}%)", l.hsn_code,
               plain(l.qty), money(l.rate), money(l.taxable_value)]
        row += [money(l.cgst), money(l.sgst)] if intra else [money(l.igst)]
        rows.append(row)

    items = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1)
    items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    els += [items, Spacer(1, 4 * mm)]

    tot = [["Taxable value", money(invoice.taxable_value)]]
    if intra:
        tot += [["CGST", money(invoice.cgst)], ["SGST", money(invoice.sgst)]]
    else:
        tot += [["IGST", money(invoice.igst)]]
    tot.append(["Invoice total (Rs.)", money(invoice.total)])
    totals = Table(tot, colWidths=[45 * mm, 35 * mm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
    ]))
    els += [totals, Spacer(1, 8 * mm),
            Paragraph("Amounts in Indian Rupees. This is a computer generated invoice.",
                      normal)]

    doc.build(els)
    return buf.getvalue()