from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from inventory.models import Item, StockLedger
from production.models import ProductionRun, ProductionRunItem, Purchase
from sales.models import CreditNote, Invoice, InvoiceItem, Payment

ZERO = Decimal("0")
TWO = Decimal("0.01")
UQC = {"packet": "PAC", "kg": "KGS", "litre": "LTR", "piece": "PCS"}


@dataclass
class Report:
    title: str
    headers: list
    rows: list
    totals: list = None
    note: str = ""


# ---------- helpers ----------
def m(x):
    """Money, 2 decimals, half-up."""
    return Decimal(x).quantize(TWO, rounding=ROUND_HALF_UP)


def q(x):
    """Quantity without trailing zeros."""
    return Decimal(x).normalize()


def sgn(x, s):
    return x if s > 0 else -x


def day_bounds(start, end):
    """Aware datetimes covering start..end inclusive (avoids MySQL timezone-table problems)."""
    tz = timezone.get_current_timezone()
    a = timezone.make_aware(datetime.combine(start, time.min), tz)
    b = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz)
    return a, b


def _sum(qs):
    return qs.aggregate(t=Sum("qty"))["t"] or ZERO


def _d(d):
    return d.strftime("%d-%m-%Y")


# ---------- sales ----------
def sales_register(start, end, p):
    entries = []
    for inv in Invoice.objects.filter(date__range=(start, end)).select_related("customer"):
        entries.append((inv.date, inv.number, "Invoice", inv.customer, inv.place_of_supply, 1, inv))
    for cn in CreditNote.objects.filter(date__range=(start, end)).select_related("invoice__customer"):
        inv = cn.invoice
        entries.append((cn.date, cn.number, "Credit note", inv.customer, inv.place_of_supply, -1, cn))
    entries.sort(key=lambda e: (e[0], e[1]))

    rows, tot = [], [ZERO] * 5
    for d, no, typ, cust, pos, s, doc in entries:
        vals = [m(sgn(x, s)) for x in (doc.taxable_value, doc.cgst, doc.sgst, doc.igst, doc.total)]
        rows.append([_d(d), no, typ, cust.name, cust.gstin or "Unregistered", pos, *vals])
        tot = [a + b for a, b in zip(tot, vals)]
    return Report(
        "Sales register",
        ["Date", "Document no.", "Type", "Customer", "GSTIN", "Place of supply",
         "Taxable value", "CGST", "SGST", "IGST", "Total"],
        rows, ["Net total", "", "", "", "", "", *tot],
        "Credit notes are shown as negative rows, so a cancelled invoice nets to zero.",
    )


def customer_sales(start, end, p):
    data = {}
    for inv in Invoice.objects.filter(date__range=(start, end)).select_related("customer"):
        d = data.setdefault(inv.customer_id, [inv.customer.name, 0, 0, ZERO, ZERO])
        d[1] += 1
        d[3] += inv.taxable_value
        d[4] += inv.total
    for cn in CreditNote.objects.filter(date__range=(start, end)).select_related("invoice__customer"):
        c = cn.invoice.customer
        d = data.setdefault(c.pk, [c.name, 0, 0, ZERO, ZERO])
        d[2] += 1
        d[3] -= cn.taxable_value
        d[4] -= cn.total
    out = sorted(data.values(), key=lambda d: d[4], reverse=True)
    rows = [[n, i, c, m(t), m(g)] for n, i, c, t, g in out]
    totals = ["Total", sum(r[1] for r in rows), sum(r[2] for r in rows),
              sum((r[3] for r in rows), ZERO), sum((r[4] for r in rows), ZERO)]
    return Report("Customer-wise sales",
                  ["Customer", "Invoices", "Credit notes", "Net taxable value", "Net total (with tax)"],
                  rows, totals)


def product_sales(start, end, p):
    data = {}
    for l in InvoiceItem.objects.filter(invoice__date__range=(start, end)).select_related("item"):
        d = data.setdefault(l.item_id, [l.item, ZERO, ZERO, ZERO])
        d[1] += l.qty
        d[3] += l.taxable_value
    for l in InvoiceItem.objects.filter(invoice__credit_note__date__range=(start, end)).select_related("item"):
        d = data.setdefault(l.item_id, [l.item, ZERO, ZERO, ZERO])
        d[2] += l.qty
        d[3] -= l.taxable_value
    rows = [[i.name, i.hsn_code, i.base_unit, q(s), q(r), q(s - r), m(t)]
            for i, s, r, t in sorted(data.values(), key=lambda d: d[0].name)]
    totals = ["Total", "", "", "", "", "", sum((r[6] for r in rows), ZERO)]
    return Report("Product-wise sales",
                  ["Product", "HSN", "Unit", "Qty sold", "Qty returned", "Net qty", "Net taxable value"],
                  rows, totals)


# ---------- GST ----------
def _gst_lines(start, end):
    qs = InvoiceItem.objects.select_related("invoice__customer", "item")
    for l in qs.filter(invoice__date__range=(start, end)):
        yield "Invoices", 1, l
    for l in qs.filter(invoice__credit_note__date__range=(start, end)):
        yield "Credit notes", -1, l


def gst_summary(start, end, p):
    agg = defaultdict(lambda: [ZERO] * 4)          # taxable, igst, cgst, sgst
    for doc, s, l in _gst_lines(start, end):
        inv = l.invoice
        key = (doc,
               "B2B" if inv.customer.gstin else "B2C",
               "Intra-state" if inv.place_of_supply == settings.FACTORY_STATE_CODE else "Inter-state",
               l.gst_rate)
        a = agg[key]
        for i, v in enumerate((l.taxable_value, l.igst, l.cgst, l.sgst)):
            a[i] += sgn(v, s)

    rows, tot = [], [ZERO] * 4
    for key in sorted(agg, key=lambda k: (k[0] != "Invoices", k[1], k[2], k[3])):
        t, ig, cg, sg = agg[key]
        rows.append([key[0], key[1], key[2], q(key[3]), m(t), m(ig), m(cg), m(sg), m(ig + cg + sg)])
        tot = [a + b for a, b in zip(tot, (t, ig, cg, sg))]
    return Report(
        "GST summary of outward supplies",
        ["Document", "Customer type", "Supply", "GST rate %", "Taxable value",
         "IGST", "CGST", "SGST", "Total tax"],
        rows, ["Net outward supplies", "", "", "", m(tot[0]), m(tot[1]), m(tot[2]), m(tot[3]),
               m(tot[1] + tot[2] + tot[3])],
        "Invoice rows map to GSTR-1 (B2B table 4, B2C table 7), credit notes to table 9B. "
        "The net total row maps to GSTR-3B table 3.1(a).",
    )


def gst_hsn(start, end, p):
    agg = defaultdict(lambda: [ZERO] * 5)          # qty, taxable, igst, cgst, sgst
    for doc, s, l in _gst_lines(start, end):
        key = (l.hsn_code, l.item.name, l.item.base_unit, l.gst_rate)
        a = agg[key]
        for i, v in enumerate((l.qty, l.taxable_value, l.igst, l.cgst, l.sgst)):
            a[i] += sgn(v, s)
    rows = []
    for (hsn, name, unit, rate), (qt, t, ig, cg, sg) in sorted(agg.items()):
        rows.append([hsn, name, UQC.get(unit, unit.upper()), q(qt), q(rate),
                     m(t), m(ig), m(cg), m(sg), m(t + ig + cg + sg)])
    totals = ["Total", "", "", "", ""] + [sum((r[i] for r in rows), ZERO) for i in range(5, 10)]
    return Report("HSN summary of outward supplies (GSTR-1 table 12)",
                  ["HSN", "Description", "UQC", "Net qty", "GST rate %", "Taxable value",
                   "IGST", "CGST", "SGST", "Total value"], rows, totals)


# ---------- purchases and collections ----------
def purchase_register(start, end, p):
    rows = []
    for x in Purchase.objects.filter(date__range=(start, end)).select_related("supplier", "item").order_by("date", "id"):
        rows.append([_d(x.date), f"PUR-{x.pk}", x.supplier.name, x.supplier.gstin or "",
                     x.invoice_no, x.item.name, q(x.qty), x.item.base_unit, m(x.rate), m(x.amount)])
    return Report("Purchase register",
                  ["Date", "Purchase no.", "Supplier", "Supplier GSTIN", "Supplier invoice",
                   "Item", "Qty", "Unit", "Rate", "Amount"],
                  rows, ["Total", "", "", "", "", "", "", "", "", sum((r[9] for r in rows), ZERO)],
                  "Purchase GST (input tax credit) is not modelled; rates are treated as the cost of the item.")


def collections(start, end, p):
    rows = []
    for x in Payment.objects.filter(date__range=(start, end)).select_related("invoice__customer").order_by("date", "id"):
        rows.append([_d(x.date), x.invoice.number, x.invoice.customer.name, x.mode, x.reference, m(x.amount)])
    return Report("Payments and collections",
                  ["Date", "Invoice", "Customer", "Mode", "Reference", "Amount"],
                  rows, ["Total", "", "", "", "", sum((r[5] for r in rows), ZERO)])


def outstanding(start, end, p):
    """Receivables as on the 'to' date, aged by invoice date."""
    as_on = end
    data = {}
    for inv in Invoice.objects.filter(status="posted", date__lte=as_on).select_related("customer"):
        paid = inv.payments.filter(date__lte=as_on).aggregate(t=Sum("amount"))["t"] or ZERO
        due = inv.total - paid
        if due <= 0:
            continue
        age = (as_on - inv.date).days
        idx = 0 if age <= 30 else 1 if age <= 60 else 2 if age <= 90 else 3
        d = data.setdefault(inv.customer_id, [inv.customer.name, [ZERO] * 4, 0])
        d[1][idx] += due
        d[2] += 1
    rows = []
    for name, b, n in sorted(data.values(), key=lambda d: d[0]):
        rows.append([name, *[m(x) for x in b], m(sum(b, ZERO)), n])
    totals = ["Total"] + [sum((r[i] for r in rows), ZERO) for i in range(1, 6)] + [sum(r[6] for r in rows)]
    return Report(f"Outstanding receivables as on {_d(as_on)}",
                  ["Customer", "0-30 days", "31-60 days", "61-90 days", "Over 90 days",
                   "Total outstanding", "Open invoices"], rows, totals,
                  "Ageing is counted from the invoice date (no credit terms are modelled). "
                  "The 'to' date is the as-on date.")


# ---------- production ----------
def production(start, end, p):
    runs = list(ProductionRun.objects.filter(date__range=(start, end))
                .select_related("product").order_by("date", "id"))
    rows = []
    for r in runs:
        rows.append([f"RUN-{r.pk}", _d(r.date), r.product.name, r.expected_output, r.actual_output,
                     r.yield_variance_pct, "Yes" if r.yield_flagged else "", m(r.material_cost),
                     m(r.labour_cost), m(r.power_cost), m(r.total_cost), r.cost_per_packet,
                     r.get_status_display()])
    posted = [r for r in runs if r.status == "posted"]
    totals = ["Total (posted runs)", "", "", sum(r.expected_output for r in posted),
              sum(r.actual_output for r in posted), "", "",
              m(sum((r.material_cost for r in posted), ZERO)),
              m(sum((r.labour_cost for r in posted), ZERO)),
              m(sum((r.power_cost for r in posted), ZERO)),
              m(sum((r.total_cost for r in posted), ZERO)), "", ""]
    return Report("Production report",
                  ["Run", "Date", "Product", "Expected", "Actual", "Yield variance %", "Flagged",
                   "Material cost", "Labour", "Gas/power", "Total cost", "Cost per packet", "Status"],
                  rows, totals, "Reversed runs are listed but left out of the totals.")


def consumption(start, end, p):
    lines = (ProductionRunItem.objects.filter(run__date__range=(start, end))
             .select_related("run", "item").order_by("run_id", "id"))
    rows = [[f"RUN-{l.run_id}", _d(l.run.date), l.item.name, l.item.base_unit, q(l.planned_qty),
             q(l.actual_qty), q(l.wastage_qty), l.variance_pct, "Yes" if l.flagged else "",
             m(l.cost), l.run.get_status_display()] for l in lines]
    return Report("Planned vs actual consumption",
                  ["Run", "Date", "Material", "Unit", "Planned", "Actual", "Wasted",
                   "Variance %", "Flagged", "Cost", "Status"], rows, None,
                  "Material is flagged when used above the BOM tolerance.")


# ---------- stock ----------
def stock_summary(start, end, p):
    a, b = day_bounds(start, end)
    rows = []
    for item in Item.objects.order_by("kind", "name"):
        L = item.ledger
        in_range = L.filter(created_at__gte=a, created_at__lt=b)
        opening = _sum(L.filter(created_at__lt=a)) + _sum(in_range.filter(move_type="opening"))
        receipts = _sum(in_range.filter(qty__gt=0).exclude(move_type="opening"))
        issues = -_sum(in_range.filter(qty__lt=0))
        rows.append([item.name, item.get_kind_display(), item.base_unit,
                     q(opening), q(receipts), q(issues), q(opening + receipts - issues)])
    return Report("Stock summary",
                  ["Item", "Type", "Unit", "Opening", "Receipts", "Issues / sales", "Closing"],
                  rows, None,
                  "Opening + receipts - issues = closing. Production output, purchases, returns and "
                  "positive adjustments count as receipts; production use, wastage, dispatch and "
                  "negative adjustments count as issues.")


def stock_ledger(start, end, p):
    a, b = day_bounds(start, end)
    qs = (StockLedger.objects.filter(created_at__gte=a, created_at__lt=b)
          .select_related("item", "created_by").order_by("created_at", "id"))
    item = None
    if str(p.get("item", "")).isdigit():
        item = Item.objects.filter(pk=int(p["item"])).first()
        if item:
            qs = qs.filter(item=item)
    rows, tin, tout = [], ZERO, ZERO
    for r in qs:
        i_n = r.qty if r.qty > 0 else ZERO
        o_u = -r.qty if r.qty < 0 else ZERO
        tin += i_n
        tout += o_u
        src = f"{r.source_type} #{r.source_id}" if r.source_id else r.source_type
        rows.append([timezone.localtime(r.created_at).strftime("%d-%m-%Y %H:%M"), r.item.name,
                     r.get_move_type_display(), src, q(i_n) if i_n else "", q(o_u) if o_u else "",
                     r.item.base_unit, r.created_by.username])
    totals = ["Total", "", "", "", q(tin), q(tout), "", ""] if item else None
    return Report("Stock ledger", ["Date", "Item", "Movement", "Source document", "In", "Out", "Unit", "By"],
                  rows, totals, "Every movement links to its source document. Pick one item to see totals.")


REGISTRY = {
    "sales_register": {"label": "Sales register", "group": "Sales and GST", "build": sales_register},
    "customer_sales": {"label": "Customer-wise sales", "group": "Sales and GST", "build": customer_sales},
    "product_sales": {"label": "Product-wise sales", "group": "Sales and GST", "build": product_sales},
    "gst_summary": {"label": "GST summary (GSTR-1 / 3B)", "group": "Sales and GST", "build": gst_summary},
    "gst_hsn": {"label": "HSN summary", "group": "Sales and GST", "build": gst_hsn},
    "collections": {"label": "Payments and collections", "group": "Receivables", "build": collections},
    "outstanding": {"label": "Outstanding with ageing", "group": "Receivables", "build": outstanding},
    "purchase_register": {"label": "Purchase register", "group": "Purchases and production", "build": purchase_register},
    "production": {"label": "Production report", "group": "Purchases and production", "build": production},
    "consumption": {"label": "Planned vs actual consumption", "group": "Purchases and production", "build": consumption},
    "stock_summary": {"label": "Stock summary", "group": "Stock", "build": stock_summary},
    "stock_ledger": {"label": "Stock ledger", "group": "Stock", "build": stock_ledger},
}