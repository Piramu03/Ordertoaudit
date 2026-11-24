from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.permissions import role_required
from inventory.models import Item
from masters.models import BOM, Supplier
from inventory import units

from . import services
from .models import ProductionRun, Purchase
from .services import StockError
from accounts import audit


def dec(value, field):
    """Parse a non-negative decimal from a form field, with a friendly error."""
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f"Enter a valid number for {field}")
    if not d.is_finite() or d < 0:
        raise ValueError(f"Enter a valid, non-negative number for {field}")
    return d


@role_required("production", "admin")
def purchase_new(request):
    suppliers = Supplier.objects.order_by("name")
    items = Item.objects.filter(kind__in=["raw", "packaging"]).order_by("name")

    if request.method == "POST":
        try:
            supplier = suppliers.filter(pk=request.POST.get("supplier") or 0).first()
            item = items.filter(pk=request.POST.get("item") or 0).first()
            if not supplier or not item:
                raise ValueError("Select a supplier and an item")
            qty = dec(request.POST.get("qty"), "quantity")
            rate = dec(request.POST.get("rate"), "rate")
            if qty == 0:
                raise ValueError("Quantity must be more than zero")
            unit = request.POST.get("unit") or item.base_unit
            qty_base = units.to_base(qty, unit, item.base_unit)   # the only place units are converted
            if qty_base == 0:
                raise ValueError("Quantity is too small")
            p = services.record_purchase(
                supplier=supplier, item=item, qty=qty_base, rate=rate,
                date=timezone.localdate(), user=request.user,
                invoice_no=request.POST.get("invoice_no", "").strip(),
            )
            extra = ""
            if units.normalize(unit) != units.normalize(item.base_unit):
                extra = f" (entered as {qty} {unit})"
            messages.success(request, f"PUR-{p.pk} saved. {item.name} +{qty_base} {item.base_unit}{extra}.")
            return redirect("production:purchase_new")
        except ValueError as e:          # UnitError is a ValueError
            messages.error(request, str(e))

    recent = Purchase.objects.select_related("supplier", "item").order_by("-id")[:10]
    return render(request, "production/purchase_new.html", {
        "suppliers": suppliers, "items": items, "recent": recent,
        "unit_choices": units.UNIT_CHOICES,
    })

@role_required("production", "admin")
def run_new(request):
    boms = BOM.objects.select_related("product").order_by("product__name")
    wanted = request.POST.get("product") or request.GET.get("product") or 0
    bom = boms.filter(product_id=wanted).first() or boms.first()
    if not bom:
        messages.error(request, "No BOM is set up yet. Add one in the admin.")
        return redirect("home")
    lines = list(bom.items.select_related("item"))

    if request.method == "POST":
        try:
            batches = dec(request.POST.get("batches"), "batches")
            if batches == 0:
                raise ValueError("Batches must be more than zero")
            try:
                output = int(request.POST.get("actual_output", "").strip())
            except ValueError:
                raise ValueError("Actual output must be a whole number")
            if output < 0:
                raise ValueError("Actual output cannot be negative")

            usage = {}
            for l in lines:
                actual = dec(request.POST.get(f"actual_{l.item_id}"), f"{l.item.name} used")
                waste = dec(request.POST.get(f"waste_{l.item_id}") or "0", f"{l.item.name} wastage")
                if waste > actual:
                    raise ValueError(f"{l.item.name}: wastage cannot be more than quantity used")
                usage[l.item_id] = (actual, waste)

            run = services.save_production_run(
                product=bom.product, actual_output=output, usage=usage,
                date=timezone.localdate(), user=request.user, batches=batches,
                labour_cost=dec(request.POST.get("labour") or "0", "labour"),
                power_cost=dec(request.POST.get("power") or "0", "gas/power"),
            )
            messages.success(request, f"RUN-{run.pk} saved. Stock updated.")
            return redirect("production:run_detail", pk=run.pk)
        except (ValueError, StockError) as e:
            messages.error(request, str(e))

    return render(request, "production/run_new.html", {
        "boms": boms, "bom": bom, "lines": lines,
    })


@role_required("production", "admin", "owner", "auditor")
def run_list(request):
    runs = ProductionRun.objects.select_related("product").order_by("-date", "-id")[:100]
    return render(request, "production/run_list.html", {"runs": runs})


@role_required("production", "admin", "owner", "auditor")
def run_detail(request, pk):
    run = get_object_or_404(ProductionRun.objects.select_related("product"), pk=pk)
    price = run.product.selling_price
    cpp = run.cost_per_packet
    margin = margin_pct = None
    if price:
        margin = price - cpp
        margin_pct = (margin / price * 100).quantize(Decimal("0.1"))
    return render(request, "production/run_detail.html", {
        "run": run, "lines": run.lines.select_related("item"),
        "price": price, "cpp": cpp, "margin": margin, "margin_pct": margin_pct,
    })


@role_required("production", "admin")
def run_costs(request, pk):
    """Add labour and gas/power after the run (benchmark step 8)."""
    run = get_object_or_404(ProductionRun, pk=pk)
    if run.status != ProductionRun.Status.POSTED:
        messages.error(request, "A reversed run cannot be edited.")
    elif request.method == "POST":
        try:
            old = f"labour {run.labour_cost}, power {run.power_cost}"
            run.labour_cost = dec(request.POST.get("labour") or "0", "labour")
            run.power_cost = dec(request.POST.get("power") or "0", "gas/power")
            run.save()
            audit.log(request.user, "run_costs_edited", run,
                      f"{old} -> labour {run.labour_cost}, power {run.power_cost}")
            messages.success(request, "Overheads saved.")
        except ValueError as e:
            messages.error(request, str(e))
    return redirect("production:run_detail", pk=run.pk)


@role_required("production", "admin")
def run_reverse(request, pk):
    run = get_object_or_404(ProductionRun, pk=pk)
    if request.method == "POST":
        try:
            services.reverse_production_run(run, request.user, request.POST.get("reason", ""))
            messages.success(request, f"RUN-{run.pk} reversed. Stock restored.")
        except (ValueError, StockError) as e:
            messages.error(request, str(e))
    return redirect("production:run_detail", pk=run.pk)