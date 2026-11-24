from decimal import Decimal as D

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from inventory.models import Item, StockLedger
from masters.models import BOM, BOMItem, Customer, Supplier

PASSWORD = "Test@1234"  # dummy demo password


class Command(BaseCommand):
    help = "Load the benchmark master data and opening stock"

    @transaction.atomic
    def handle(self, *args, **options):
        # --- users for each role ---
        users = {}
        for username, role, staff in [
            ("admin1", "admin", True),
            ("salesman_a", "salesman", False),
            ("salesman_b", "salesman", False),
            ("production1", "production", False),
            ("auditor1", "auditor", False),
            ("owner1", "owner", False),
        ]:
            u, created = User.objects.get_or_create(
                username=username, defaults={"role": role, "is_staff": staff}
            )
            if created:
                u.set_password(PASSWORD)
                u.save()
            users[username] = u
        admin = users["admin1"]

        # --- items: (name, kind, unit, opening qty, rate, selling price) ---
        rows = [
            ("Flour", "raw", "kg", "100", "42", None),
            ("Cooking oil", "raw", "litre", "30", "140", None),
            ("Salt and spice mix", "raw", "kg", "5", "200", None),
            ("200 g pouch", "packaging", "piece", "500", "2.50", None),
            ("Carton (20 packets)", "packaging", "piece", "30", "15", None),
            ("Murukku 200 g", "finished", "packet", "50", None, "50.00"),
        ]
        items = {}
        for name, kind, unit, qty, rate, price in rows:
            item, _ = Item.objects.get_or_create(
                name=name,
                defaults={
                    "kind": kind,
                    "base_unit": unit,
                    "hsn_code": "19059090" if kind == "finished" else "",
                    "gst_rate": D("5.00"),
                    "selling_price": D(price) if price else None,
                },
            )
            items[name] = item
            if not item.ledger.filter(move_type="opening").exists():
                StockLedger.objects.create(
                    item=item, qty=D(qty), move_type="opening",
                    source_type="Opening", source_id=0,
                    unit_cost=D(rate) if rate else None, created_by=admin,
                )

        # --- BOM ---
        bom, _ = BOM.objects.get_or_create(
            product=items["Murukku 200 g"],
            defaults={"batch_yield": 200, "tolerance_pct": D("3.00")},
        )
        for name, qty in [
            ("Flour", "40"), ("Cooking oil", "10"), ("Salt and spice mix", "1.2"),
            ("200 g pouch", "200"), ("Carton (20 packets)", "10"),
        ]:
            BOMItem.objects.get_or_create(
                bom=bom, item=items[name], defaults={"qty_per_batch": D(qty)}
            )

        # --- customers and supplier ---
        Customer.objects.get_or_create(
            name="Retailer A", defaults={
                "kind": "retailer", "state": "Tamil Nadu", "state_code": "33",
                "gstin": "33AAAAA0000A1Z5", "salesman": users["salesman_a"]})
        Customer.objects.get_or_create(
            name="Distributor B", defaults={
                "kind": "distributor", "state": "Karnataka", "state_code": "29",
                "gstin": "29BBBBB0000B1Z5", "salesman": users["salesman_b"]})
        Supplier.objects.get_or_create(name="Flour Supplier")

        self.stdout.write(self.style.SUCCESS("Benchmark data loaded."))