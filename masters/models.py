from decimal import Decimal

from django.conf import settings
from django.db import models

from inventory.models import Item


class Customer(models.Model):
    class Kind(models.TextChoices):
        RETAILER = "retailer", "Retailer"
        DISTRIBUTOR = "distributor", "Distributor"

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    gstin = models.CharField(max_length=15, blank=True)
    state = models.CharField(max_length=50)
    state_code = models.CharField(max_length=2)  # 33 = Tamil Nadu, 29 = Karnataka
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=15, blank=True)
    salesman = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="customers",
    )

    def __str__(self):
        return self.name


class Supplier(models.Model):
    name = models.CharField(max_length=120)
    gstin = models.CharField(max_length=15, blank=True)
    phone = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return self.name


class BOM(models.Model):
    product = models.OneToOneField(
        Item, on_delete=models.PROTECT, related_name="bom",
        limit_choices_to={"kind": "finished"},
    )
    batch_yield = models.PositiveIntegerField()  # expected packets per batch
    tolerance_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("3.00"))

    def __str__(self):
        return f"BOM: {self.product}"


class BOMItem(models.Model):
    bom = models.ForeignKey(BOM, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(
        Item, on_delete=models.PROTECT,
        limit_choices_to={"kind__in": ["raw", "packaging"]},
    )
    qty_per_batch = models.DecimalField(max_digits=12, decimal_places=3)

    class Meta:
        unique_together = ("bom", "item")

    def __str__(self):
        return f"{self.item} x {self.qty_per_batch}"