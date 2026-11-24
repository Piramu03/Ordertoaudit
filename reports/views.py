from datetime import date, timedelta
from decimal import Decimal
from collections import Counter
from urllib.parse import urlencode

from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from accounts.permissions import role_required
from inventory.models import Item
from masters.models import BOM
from production.models import ProductionRun
from sales.models import Order

from . import exporters
from .builders import REGISTRY, day_bounds, outstanding, sales_register


def parse_range(request):
    today = timezone.localdate()

    def get(name, default):
        try:
            return date.fromisoformat(request.GET.get(name, ""))
        except ValueError:
            return default

    start, end = get("from", today.replace(day=1)), get("to", today)
    if end < start:
        start, end = end, start
    return start, end


@role_required("admin", "auditor", "owner")
def index(request):
    start, end = parse_range(request)
    groups = {}
    for key, spec in REGISTRY.items():
        groups.setdefault(spec["group"], []).append((key, spec["label"]))
    return render(request, "reports/index.html", {
        "groups": list(groups.items()), "start": start, "end": end,
        "qs": urlencode({"from": start.isoformat(), "to": end.isoformat()}),
    })


@role_required("admin", "auditor", "owner")
def report_view(request, key):
    spec = REGISTRY.get(key)
    if not spec:
        raise Http404
    start, end = parse_range(request)
    report = spec["build"](start, end, request.GET)
    period = f"Period: {start:%d-%m-%Y} to {end:%d-%m-%Y}"
    name = f"{key}_{start.isoformat()}_{end.isoformat()}"

    fmt = request.GET.get("format", "")
    if fmt == "csv":
        return exporters.to_csv(report, name)
    if fmt == "xlsx":
        return exporters.to_xlsx(report, name, period)
    if fmt == "pdf":
        return exporters.to_pdf(report, name, period)

    params = {"from": start.isoformat(), "to": end.isoformat()}
    if request.GET.get("item"):
        params["item"] = request.GET["item"]
    show = lambda r: [(exporters.text(c), exporters.is_num(c)) for c in r]
    return render(request, "reports/report.html", {
        "key": key, "report": report, "period": period, "start": start, "end": end,
        "rows": [show(r) for r in report.rows],
        "totals": show(report.totals) if report.totals else None,
        "qs": urlencode(params),
        "items": Item.objects.order_by("name") if key == "stock_ledger" else None,
        "item_id": request.GET.get("item", ""),
    })

@role_required("owner", "admin", "auditor")
def dashboard(request):
    today = timezone.localdate()
    a, b = day_bounds(today, today)

    todays = list(Order.objects.filter(created_at__gte=a, created_at__lt=b)
                  .select_related("customer").prefetch_related("lines"))
    month = sales_register(today.replace(day=1), today, {})
    ageing = outstanding(today, today, {})

    stock = [(label, [(i, i.balance()) for i in Item.objects.filter(kind=kind).order_by("name")])
             for kind, label in Item.Kind.choices]

    alerts = []
    since = today - timedelta(days=30)
    for run in (ProductionRun.objects.filter(status="posted", date__gte=since)
                .select_related("product").prefetch_related("lines__item").order_by("-date", "-id")):
        bad = [l for l in run.lines.all() if l.flagged]
        if run.yield_flagged or bad:
            alerts.append((run, bad))

    costs = []
    for bom in BOM.objects.select_related("product"):
        run = (ProductionRun.objects.filter(product=bom.product, status="posted")
               .order_by("-date", "-id").first())
        if run:
            cpp, price = run.cost_per_packet, bom.product.selling_price
            margin = margin_pct = None
            if price:
                margin = price - cpp
                margin_pct = (margin / price * 100).quantize(Decimal("0.1"))
            costs.append({"run": run, "cpp": cpp, "price": price,
                          "margin": margin, "margin_pct": margin_pct})

    return render(request, "reports/dashboard.html", {
        "orders_today": todays,
        "orders_today_value": sum((o.amount for o in todays), Decimal("0")),
        "status_counts": dict(Counter(o.get_status_display() for o in todays)),
        "pending": Order.objects.filter(status="submitted").count(),
        "month_taxable": month.totals[6], "month_total": month.totals[10],
        "dues_total": ageing.totals[5],
        "dues_overdue": sum(ageing.totals[2:5], Decimal("0")),
        "top_dues": sorted(ageing.rows, key=lambda r: r[5], reverse=True)[:5],
        "stock": stock, "alerts": alerts, "costs": costs, "today": today,
    })