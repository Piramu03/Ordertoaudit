from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum

from inventory.models import Item
from masters.models import Customer


class Order(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        INVOICED = "invoiced", "Invoiced"
        DISPATCHED = "dispatched", "Dispatched"
        CANCELLED = "cancelled", "Cancelled"

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    salesman = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUBMITTED)
    remarks = models.CharField(max_length=200, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="approved_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
        
    @property
    def amount(self):
        return sum((l.qty * l.rate for l in self.lines.all()), Decimal("0"))

    def __str__(self):
        return f"ORD-{self.pk} {self.customer}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    qty = models.DecimalField(max_digits=10, decimal_places=3)
    rate = models.DecimalField(max_digits=10, decimal_places=2)


class InvoiceSequence(models.Model):
    """One counter per financial year, so numbers never repeat or skip."""
    financial_year = models.CharField(max_length=10, unique=True)
    last_no = models.PositiveIntegerField(default=0)


class Invoice(models.Model):
    class Status(models.TextChoices):
        POSTED = "posted", "Posted"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=30, unique=True)
    financial_year = models.CharField(max_length=10)
    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="invoice")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    date = models.DateField()
    place_of_supply = models.CharField(max_length=2)   # state code
    taxable_value = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    cgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    sgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    igst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.POSTED)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    @property
    def paid(self):
        return self.payments.aggregate(t=Sum("amount"))["t"] or Decimal("0")

    @property
    def outstanding(self):
        if self.status == self.Status.CANCELLED:
            return Decimal("0")
        return self.total - self.paid

    def __str__(self):
        return self.number


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    hsn_code = models.CharField(max_length=8, blank=True)
    qty = models.DecimalField(max_digits=10, decimal_places=3)
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    taxable_value = models.DecimalField(max_digits=12, decimal_places=2)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2)
    cgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    sgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    igst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))


class Payment(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    mode = models.CharField(max_length=20, default="cash")
    reference = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

class CreditNoteSequence(models.Model):
    financial_year = models.CharField(max_length=10, unique=True)
    last_no = models.PositiveIntegerField(default=0)


class CreditNote(models.Model):
    number = models.CharField(max_length=30, unique=True)
    financial_year = models.CharField(max_length=10)
    invoice = models.OneToOneField(Invoice, on_delete=models.PROTECT, related_name="credit_note")
    date = models.DateField()
    reason = models.CharField(max_length=200)
    taxable_value = models.DecimalField(max_digits=12, decimal_places=2)
    cgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    sgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    igst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    def __str__(self):
        return self.number