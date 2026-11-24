from decimal import Decimal

from django.shortcuts import get_object_or_404, render

from accounts.permissions import role_required
from .models import Item


@role_required("production", "admin", "owner", "auditor")
def stock_summary(request):
    groups = []
    for kind, label in Item.Kind.choices:
        items = Item.objects.filter(kind=kind).order_by("name")
        groups.append((label, [(i, i.balance()) for i in items]))
    return render(request, "inventory/stock_summary.html", {"groups": groups})


@role_required("production", "admin", "owner", "auditor")
def stock_ledger(request, pk):
    item = get_object_or_404(Item, pk=pk)
    running = Decimal("0")
    rows = []
    for r in item.ledger.select_related("created_by"):
        running += r.qty
        rows.append((r, running))
    return render(request, "inventory/stock_ledger.html", {
        "item": item, "rows": rows, "closing": running,
    })