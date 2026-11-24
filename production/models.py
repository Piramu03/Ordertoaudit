from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import models

from inventory.models import Item
from masters.models import Supplier


class Purchase(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    item = models.ForeignKey(
        Item, on_delete=models.PROTECT,
        limit_choices_to={"kind__in": ["raw", "packaging"]},
    )
    qty = models.DecimalField(max_digits=12, decimal_places=3)
    rate = models.DecimalField(max_digits=12, decimal_places=2)
    invoice_no = models.CharField(max_length=30, blank=True)
    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    @property
    def amount(self):
        return self.qty * self.rate

    def __str__(self):
        return f"PUR-{self.pk} {self.item} {self.qty}"


class ProductionRun(models.Model):
    product = models.ForeignKey(Item, on_delete=models.PROTECT)
    batches = models.DecimalField(max_digits=8, decimal_places=3, default=Decimal("1"))
    date = models.DateField()
    expected_output = models.PositiveIntegerField()
    actual_output = models.PositiveIntegerField()
    yield_variance_pct = models.DecimalField(max_digits=7, decimal_places=2)
    yield_flagged = models.BooleanField(default=False)
    labour_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    power_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Status(models.TextChoices):
        POSTED = "posted", "Posted"
        REVERSED = "reversed", "Reversed"

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.POSTED)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reverse_reason = models.CharField(max_length=200, blank=True)

    @property
    def material_cost(self):
        return sum((l.actual_qty * l.unit_cost for l in self.lines.all()), Decimal("0"))

    @property
    def total_cost(self):
        return self.material_cost + self.labour_cost + self.power_cost

    @property
    def cost_per_packet(self):
        if not self.actual_output:
            return Decimal("0")
        return (self.total_cost / self.actual_output).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def __str__(self):
        return f"RUN-{self.pk} {self.product}"


class ProductionRunItem(models.Model):
    run = models.ForeignKey(ProductionRun, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    planned_qty = models.DecimalField(max_digits=14, decimal_places=3)
    actual_qty = models.DecimalField(max_digits=14, decimal_places=3)    # total consumed
    wastage_qty = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    variance_pct = models.DecimalField(max_digits=7, decimal_places=2)
    flagged = models.BooleanField(default=False)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4)

    @property
    def cost(self):
        return self.actual_qty * self.unit_cost

    def __str__(self):
        return f"{self.run} / {self.item}"