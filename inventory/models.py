from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum


class Item(models.Model):
    class Kind(models.TextChoices):
        RAW = "raw", "Raw material"
        PACKAGING = "packaging", "Packaging"
        FINISHED = "finished", "Finished good"

    name = models.CharField(max_length=100, unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    base_unit = models.CharField(max_length=10)  # kg, litre, piece, packet
    hsn_code = models.CharField(max_length=8, blank=True)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5.00"))
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return self.name

    def balance(self):
        return self.ledger.aggregate(t=Sum("qty"))["t"] or Decimal("0")


class StockLedger(models.Model):
    class MoveType(models.TextChoices):
        OPENING = "opening", "Opening"
        PURCHASE = "purchase", "Purchase"
        PROD_ISSUE = "prod_issue", "Production issue"
        PROD_OUTPUT = "prod_output", "Production output"
        WASTAGE = "wastage", "Wastage"
        DISPATCH = "dispatch", "Dispatch"
        ADJUSTMENT = "adjustment", "Adjustment"
        SALES_RETURN = "sales_return", "Sales return (credit note)"
        REVERSAL = "reversal", "Reversal"

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="ledger")
    qty = models.DecimalField(max_digits=14, decimal_places=3)  # + in, - out
    move_type = models.CharField(max_length=15, choices=MoveType.choices)
    source_type = models.CharField(max_length=30)  # Opening, Purchase, ProductionRun, Invoice
    source_id = models.PositiveIntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    batch_no = models.CharField(max_length=30, blank=True)
    expiry = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.item} {self.qty} ({self.move_type})"
