from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.db.models import Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import role_required
from inventory.models import Item
from masters.models import Customer
from production.services import StockError
from accounts import audit
from . import services
from .models import Invoice, Order
from .pdf import build_invoice_pdf

SHARE_SALT = "invoice-share"


# ---------------- Salesman (mobile) ----------------
@role_required("salesman")
def new_order(request):
    customers = Customer.objects.filter(salesman=request.user).order_by("name")
    items = Item.objects.filter(kind="finished", selling_price__isnull=False).order_by("name")

    if request.method == "POST":
        customer = customers.filter(pk=request.POST.get("customer") or 0).first()
        lines = []
        for item in items:
            raw = request.POST.get(f"qty_{item.id}", "").strip()
            if not raw:
                continue
            try:
                qty = Decimal(raw)
            except InvalidOperation:
                qty = Decimal("0")
            if qty > 0:
                lines.append((item, qty))

        if not customer:
            messages.error(request, "Please select a customer.")
        elif not lines:
            messages.error(request, "Enter a quantity for at least one product.")
        else:
            order = services.place_order(customer=customer, salesman=request.user, lines=lines)
            messages.success(request, f"Order ORD-{order.pk} submitted to the factory.")
            return redirect("sales:my_orders")

    return render(request, "sales/new_order.html", {"customers": customers, "items": items})


@role_required("salesman")
def my_orders(request):
    orders = (Order.objects.filter(salesman=request.user)
              .select_related("customer").prefetch_related("lines__item")
              .order_by("-created_at")[:50])
    sales = (Invoice.objects.filter(order__salesman=request.user, status="posted")
             .values("customer__name").annotate(total=Sum("total")).order_by("-total"))
    return render(request, "sales/my_orders.html", {"orders": orders, "sales": sales})


# ---------------- Admin (desktop) ----------------
@role_required("admin")
def admin_orders(request):
    status = request.GET.get("status", "")
    orders = Order.objects.select_related("customer", "salesman").order_by("-created_at")
    if status:
        orders = orders.filter(status=status)
    return render(request, "sales/admin_orders.html", {
        "orders": orders[:100], "status": status, "statuses": Order.Status.choices,
    })


def _save_lines(request, order):
    """Admin may edit quantity and price while the order is 'submitted'. Changes are audited."""
    if order.status != Order.Status.SUBMITTED:
        raise ValueError("Only submitted orders can be edited")
    changes = []
    with transaction.atomic():
        for line in order.lines.select_related("item"):
            try:
                qty = Decimal(request.POST.get(f"qty_{line.id}", line.qty))
                rate = Decimal(request.POST.get(f"rate_{line.id}", line.rate))
            except InvalidOperation:
                raise ValueError("Enter valid numbers for quantity and rate")
            if qty < 0 or rate < 0:
                raise ValueError("Quantity and rate cannot be negative")
            if qty == 0:
                changes.append(f"{line.item.name}: removed (was {line.qty} @ {line.rate})")
                line.delete()
            elif qty != line.qty or rate != line.rate:
                changes.append(f"{line.item.name}: qty {line.qty} -> {qty}, rate {line.rate} -> {rate}")
                line.qty, line.rate = qty, rate
                line.save()
        if not order.lines.exists():
            raise ValueError("An order must have at least one item. Reject it instead.")
        if changes:
            audit.log(request.user, "order_edited", order, "; ".join(changes))

@role_required("admin")
def order_detail(request, pk):
    order = get_object_or_404(Order.objects.select_related("customer", "salesman"), pk=pk)

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "save":
                _save_lines(request, order)
                messages.success(request, "Order updated.")
            elif action == "approve":
                _save_lines(request, order)       # keep any edits the admin typed
                services.approve_order(order, request.user)
                messages.success(request, "Order approved.")
            elif action == "reject":
                services.reject_order(order, request.user, request.POST.get("reason", ""))
                messages.success(request, "Order rejected.")
            elif action == "invoice":
                invoice = services.create_invoice(order, request.user)
                messages.success(request, f"Invoice {invoice.number} created.")
                return redirect("sales:invoice_detail", pk=invoice.pk)
        except services.ShortageError as e:
            messages.error(request, f"Cannot approve. {e}")
        except ValueError as e:
            messages.error(request, str(e))
        return redirect("sales:order_detail", pk=order.pk)

    checks = {c["item"].id: c for c in services.stock_check(order)}
    rows = [(l, checks[l.item_id]) for l in order.lines.select_related("item")]
    return render(request, "sales/order_detail.html", {
        "order": order, "rows": rows,
        "has_shortage": any(c["shortage"] > 0 for _, c in rows),
        "invoice": getattr(order, "invoice", None),
    })


@role_required("admin", "auditor", "owner")
def invoice_list(request):
    invoices = (Invoice.objects.select_related("customer")
                .order_by("-date", "-id")[:100])
    return render(request, "sales/invoice_list.html", {"invoices": invoices})


@role_required("admin")
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice.objects.select_related("customer", "order"), pk=pk)

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "dispatch":
                services.dispatch_invoice(invoice, request.user)
                messages.success(request, "Dispatched. Finished-goods stock updated.")
            elif action == "payment":
                services.record_payment(
                    invoice, request.POST.get("amount") or 0, timezone.localdate(),
                    request.user, mode=request.POST.get("mode", "cash"),
                    reference=request.POST.get("reference", ""),
                )
                messages.success(request, "Payment recorded.")

            elif action == "cancel":
                cn = services.cancel_invoice(invoice, request.user, request.POST.get("reason", ""))
                messages.success(request, f"Invoice cancelled. Credit note {cn.number} created.")
        except StockError as e:
            messages.error(request, str(e))
        except InvalidOperation:
            messages.error(request, "Enter a valid amount.")
        except ValueError as e:
            messages.error(request, str(e))
        return redirect("sales:invoice_detail", pk=invoice.pk)

    token = signing.dumps(invoice.pk, salt=SHARE_SALT)
    link = request.build_absolute_uri(reverse("sales:invoice_shared_pdf", args=[token]))
    text = (f"Invoice {invoice.number} from {settings.FACTORY_NAME}, "
            f"total Rs. {invoice.total}. Download: {link}")
    return render(request, "sales/invoice_detail.html", {
        "invoice": invoice, "lines": invoice.lines.select_related("item"),
        "payments": invoice.payments.all(),
        "share_url": "https://wa.me/?text=" + quote(text),
    })


def _pdf_response(invoice):
    resp = HttpResponse(build_invoice_pdf(invoice), content_type="application/pdf")
    name = invoice.number.replace("/", "-")
    resp["Content-Disposition"] = f'inline; filename="{name}.pdf"'
    return resp


@role_required("admin", "auditor", "owner")
def invoice_pdf(request, pk):
    return _pdf_response(get_object_or_404(Invoice, pk=pk))


def invoice_shared_pdf(request, token):
    """Customer link from WhatsApp/email: signed token, no login, expires in 30 days."""
    try:
        pk = signing.loads(token, salt=SHARE_SALT, max_age=60 * 60 * 24 * 30)
    except signing.BadSignature:
        raise Http404
    return _pdf_response(get_object_or_404(Invoice, pk=pk))