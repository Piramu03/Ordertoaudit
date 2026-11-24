from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from accounts import audit
from inventory.models import StockLedger
from .models import Purchase, ProductionRun, ProductionRunItem
TWO = Decimal("0.01")


class StockError(Exception):
    """Raised when a run needs more material than is in stock."""


def pct(actual, planned):
    """Variance % = (actual - planned) / planned * 100, rounded to 2 places."""
    if planned == 0:
        return Decimal("0")
    return ((actual - planned) / planned * 100).quantize(TWO, rounding=ROUND_HALF_UP)


def weighted_avg_cost(item):
    """Weighted average rate of all receipts (opening + purchases)."""
    rows = list(item.ledger.filter(qty__gt=0, unit_cost__isnull=False))
    total_qty = sum((r.qty for r in rows), Decimal("0"))
    if total_qty == 0:
        return Decimal("0")
    total_value = sum((r.qty * r.unit_cost for r in rows), Decimal("0"))
    return total_value / total_qty


@transaction.atomic
def record_purchase(*, supplier, item, qty, rate, date, user, invoice_no=""):
    purchase = Purchase.objects.create(
        supplier=supplier, item=item, qty=qty, rate=rate,
        date=date, invoice_no=invoice_no, created_by=user,
    )
    StockLedger.objects.create(
        item=item, qty=qty, move_type="purchase",
        source_type="Purchase", source_id=purchase.pk,
        unit_cost=rate, created_by=user,
    )

    audit.log(user, "purchase_created", purchase, f"{item.name} {qty} @ {rate}")
    return purchase


@transaction.atomic
def save_production_run(*, product, actual_output, usage, date, user,
                        batches=Decimal("1"), labour_cost=Decimal("0"),
                        power_cost=Decimal("0")):
    """
    usage = {item_id: (actual_qty_consumed, wastage_qty)}
    Items missing from usage are assumed to use exactly the BOM quantity.
    Everything is saved in one transaction: if anything fails, nothing is saved.
    """
    bom = product.bom
    tol = bom.tolerance_pct
    batches = Decimal(batches)

    expected = int((bom.batch_yield * batches).to_integral_value(ROUND_HALF_UP))
    yield_var = pct(Decimal(actual_output), Decimal(expected))

    run = ProductionRun.objects.create(
        product=product, batches=batches, date=date,
        expected_output=expected, actual_output=actual_output,
        yield_variance_pct=yield_var,
        yield_flagged=(yield_var < -tol),      # shortfall beyond tolerance
        labour_cost=labour_cost, power_cost=power_cost, created_by=user,
    )

    for bi in bom.items.select_related("item"):
        planned = bi.qty_per_batch * batches
        actual, wastage = usage.get(bi.item_id, (planned, Decimal("0")))
        actual, wastage = Decimal(actual), Decimal(wastage)

        available = bi.item.balance()
        if actual > available:
            raise StockError(
                f"Not enough {bi.item.name}: need {actual}, available {available}"
            )

        var = pct(actual, planned)
        ProductionRunItem.objects.create(
            run=run, item=bi.item, planned_qty=planned, actual_qty=actual,
            wastage_qty=wastage, variance_pct=var,
            flagged=(var > tol),               # over-consumption beyond tolerance
            unit_cost=weighted_avg_cost(bi.item),
        )

        good_used = actual - wastage
        if good_used > 0:
            StockLedger.objects.create(
                item=bi.item, qty=-good_used, move_type="prod_issue",
                source_type="ProductionRun", source_id=run.pk, created_by=user,
            )
        if wastage > 0:
            StockLedger.objects.create(
                item=bi.item, qty=-wastage, move_type="wastage",
                source_type="ProductionRun", source_id=run.pk, created_by=user,
            )

    StockLedger.objects.create(
        item=product, qty=Decimal(actual_output), move_type="prod_output",
        source_type="ProductionRun", source_id=run.pk, created_by=user,
    )

    audit.log(user, "run_created", run, f"output {actual_output}, yield variance {yield_var}%")
    return run

@transaction.atomic
def reverse_production_run(run, user, reason):
    """Undo a wrong run with opposite ledger rows. The original rows stay for the audit trail."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Give a reason for the reversal")
    run = ProductionRun.objects.select_for_update().get(pk=run.pk)
    if run.status != ProductionRun.Status.POSTED:
        raise ValueError("This run is already reversed")

    rows = list(StockLedger.objects.filter(
        source_type="ProductionRun", source_id=run.pk,
        move_type__in=["prod_issue", "wastage", "prod_output"],
    ).select_related("item"))

    for r in rows:                     # the packets produced must still be in stock
        if r.move_type == "prod_output" and r.qty > r.item.balance():
            raise StockError(
                f"Cannot reverse: this run made {r.qty} {r.item.name} but only "
                f"{r.item.balance()} are in stock (some were dispatched)."
            )
    for r in rows:
        StockLedger.objects.create(
            item=r.item, qty=-r.qty, move_type="reversal",
            source_type="ProductionRun", source_id=run.pk, created_by=user,
        )

    run.status = ProductionRun.Status.REVERSED
    run.reversed_at = timezone.now()
    run.reverse_reason = reason
    run.save()
    audit.log(user, "run_reversed", run, reason)
    return run