from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts import audit
from inventory.models import StockLedger
from production.services import StockError
from .models import (
    CreditNote, CreditNoteSequence, Invoice, InvoiceItem, InvoiceSequence,
    Order, OrderItem, Payment,
)
TWO = Decimal("0.01")
ZERO = Decimal("0")


def q2(x):
    return x.quantize(TWO, rounding=ROUND_HALF_UP)


class ShortageError(Exception):
    """Order needs more finished goods than are in stock."""
    def __init__(self, shortages):
        self.shortages = shortages
        text = ", ".join(
            f"{s['item'].name}: need {s['required']}, have {s['available']}, short {s['shortage']}"
            for s in shortages
        )
        super().__init__(text)


def financial_year(d):
    """Indian financial year runs April to March: 18 Nov 2026 -> '2026-27'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


@transaction.atomic
def place_order(*, customer, salesman, lines, remarks=""):
    """lines = [(item, qty), ...]; price comes from the item's selling price."""
    order = Order.objects.create(customer=customer, salesman=salesman, remarks=remarks)
    for item, qty in lines:
        if item.selling_price is None:
            raise ValueError(f"{item.name} has no selling price")
        OrderItem.objects.create(
            order=order, item=item, qty=Decimal(qty), rate=item.selling_price
        )
    return order


def stock_check(order):
    """What the admin sees before approving: required vs available vs shortage."""
    rows = []
    for line in order.lines.select_related("item"):
        available = line.item.balance()
        rows.append({
            "item": line.item,
            "required": line.qty,
            "available": available,
            "shortage": max(line.qty - available, ZERO),
        })
    return rows


@transaction.atomic
def approve_order(order, user, allow_shortage=False):
    if order.status != Order.Status.SUBMITTED:
        raise ValueError("Only submitted orders can be approved")
    short = [r for r in stock_check(order) if r["shortage"] > 0]
    if short and not allow_shortage:
        raise ShortageError(short)
    order.status = Order.Status.APPROVED
    order.approved_by = user
    order.save()
    audit.log(user, "order_approved", order, f"Approved (shortage override: {allow_shortage})")
    return order


@transaction.atomic
def reject_order(order, user, reason=""):
    if order.status != Order.Status.SUBMITTED:
        raise ValueError("Only submitted orders can be rejected")
    order.status = Order.Status.REJECTED
    order.remarks = reason or order.remarks
    order.save()
    audit.log(user, "order_rejected", order, reason)
    return order


@transaction.atomic
def create_invoice(order, user, on_date=None):
    if order.status != Order.Status.APPROVED:
        raise ValueError("Only approved orders can be invoiced")

    on_date = on_date or timezone.localdate()
    fy = financial_year(on_date)
    seq, _ = InvoiceSequence.objects.select_for_update().get_or_create(financial_year=fy)
    seq.last_no += 1
    seq.save()

    customer = order.customer
    intra_state = customer.state_code == settings.FACTORY_STATE_CODE

    invoice = Invoice.objects.create(
        number=f"INV/{fy}/{seq.last_no:04d}", financial_year=fy, order=order,
        customer=customer, date=on_date, place_of_supply=customer.state_code,
        created_by=user,
    )

    taxable_sum = cgst_sum = sgst_sum = igst_sum = ZERO
    for line in order.lines.select_related("item"):
        taxable = q2(line.qty * line.rate)
        tax = q2(taxable * line.item.gst_rate / 100)
        if intra_state:
            cgst = q2(tax / 2)
            sgst = tax - cgst          # keeps cgst + sgst exactly equal to tax
            igst = ZERO
        else:
            cgst = sgst = ZERO
            igst = tax
        InvoiceItem.objects.create(
            invoice=invoice, item=line.item, hsn_code=line.item.hsn_code,
            qty=line.qty, rate=line.rate, taxable_value=taxable,
            gst_rate=line.item.gst_rate, cgst=cgst, sgst=sgst, igst=igst,
        )
        taxable_sum += taxable
        cgst_sum += cgst
        sgst_sum += sgst
        igst_sum += igst

    invoice.taxable_value = taxable_sum
    invoice.cgst, invoice.sgst, invoice.igst = cgst_sum, sgst_sum, igst_sum
    invoice.total = taxable_sum + cgst_sum + sgst_sum + igst_sum
    invoice.save()

    order.status = Order.Status.INVOICED
    order.save()
    audit.log(user, "invoice_created", invoice, f"{invoice.number} total {invoice.total}")
    return invoice


@transaction.atomic
def dispatch_invoice(invoice, user):
    if invoice.status != Invoice.Status.POSTED:
        raise ValueError("Cancelled invoice cannot be dispatched")
    if invoice.dispatched_at:
        raise ValueError("Already dispatched")

    for line in invoice.lines.select_related("item"):
        available = line.item.balance()
        if line.qty > available:
            raise StockError(
                f"Not enough {line.item.name}: need {line.qty}, available {available}"
            )
        StockLedger.objects.create(
            item=line.item, qty=-line.qty, move_type="dispatch",
            source_type="Invoice", source_id=invoice.pk, created_by=user,
        )

    invoice.dispatched_at = timezone.now()
    invoice.save()
    invoice.order.status = Order.Status.DISPATCHED
    invoice.order.save()
    audit.log(user, "invoice_dispatched", invoice, invoice.number)
    return invoice


@transaction.atomic
def record_payment(invoice, amount, on_date, user, mode="cash", reference=""):
    amount = Decimal(amount)
    if invoice.status != Invoice.Status.POSTED:
        raise ValueError("Cannot record a payment on a cancelled invoice")
    if amount <= 0:
        raise ValueError("Payment must be positive")
    if amount > invoice.outstanding:
        raise ValueError("Payment is more than the outstanding amount")
    payment = Payment.objects.create(
        invoice=invoice, amount=amount, date=on_date, mode=mode,
        reference=reference, created_by=user,
    )
    audit.log(user, "payment_recorded", invoice, f"Rs. {amount} {mode} {reference}".strip())
    return payment

def customer_outstanding(customer):
    total = ZERO
    for inv in customer.invoice_set.filter(status=Invoice.Status.POSTED):
        total += inv.outstanding
    return total

@transaction.atomic
def cancel_invoice(invoice, user, reason, on_date=None):
    """Cancel a posted invoice with a credit note. Nothing is deleted."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Give a reason for the credit note")
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != Invoice.Status.POSTED:
        raise ValueError("This invoice is already cancelled")
    if invoice.payments.exists():
        raise ValueError("Payments are recorded against this invoice. Refund or adjust them first.")

    on_date = on_date or timezone.localdate()
    fy = financial_year(on_date)
    seq, _ = CreditNoteSequence.objects.select_for_update().get_or_create(financial_year=fy)
    seq.last_no += 1
    seq.save()

    cn = CreditNote.objects.create(
        number=f"CN/{fy}/{seq.last_no:04d}", financial_year=fy, invoice=invoice,
        date=on_date, reason=reason, taxable_value=invoice.taxable_value,
        cgst=invoice.cgst, sgst=invoice.sgst, igst=invoice.igst,
        total=invoice.total, created_by=user,
    )

    if invoice.dispatched_at:          # goods come back into finished-goods stock
        for line in invoice.lines.select_related("item"):
            StockLedger.objects.create(
                item=line.item, qty=line.qty, move_type="sales_return",
                source_type="CreditNote", source_id=cn.pk, created_by=user,
            )

    invoice.status = Invoice.Status.CANCELLED
    invoice.save()
    order = invoice.order
    order.status = Order.Status.CANCELLED
    order.save()
    audit.log(user, "invoice_cancelled", invoice, f"{invoice.number} -> {cn.number}: {reason}")
    return cn