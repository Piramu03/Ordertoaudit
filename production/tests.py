from datetime import date
from decimal import Decimal as D

from django.core.management import call_command
from django.test import Client, TestCase
from .models import ProductionRun

from accounts.models import User
from inventory.models import Item
from masters.models import Supplier
from .services import StockError, record_purchase, reverse_production_run, save_production_run
from inventory.models import StockLedger

class BenchmarkProductionTests(TestCase):
    def setUp(self):
        call_command("seed_benchmark")
        self.user = User.objects.get(username="production1")
        self.i = {x.name: x for x in Item.objects.all()}

        record_purchase(
            supplier=Supplier.objects.first(), item=self.i["Flour"],
            qty=D("60"), rate=D("45"), date=date(2026, 11, 18), user=self.user,
        )
        usage = {
            self.i["Flour"].id: (D("40"), D("0")),
            self.i["Cooking oil"].id: (D("10.5"), D("0")),
            self.i["Salt and spice mix"].id: (D("1.2"), D("0")),
            self.i["200 g pouch"].id: (D("194"), D("6")),   # 188 good + 6 damaged
            self.i["Carton (20 packets)"].id: (D("9"), D("0")),
        }
        self.run_obj = save_production_run(
            product=self.i["Murukku 200 g"], actual_output=188, usage=usage,
            date=date(2026, 11, 18), user=self.user,
            labour_cost=D("1200"), power_cost=D("600"),
        )

    def bal(self, name):
        return self.i[name].balance()

    def test_stock_balances(self):
        self.assertEqual(self.bal("Flour"), D("120"))
        self.assertEqual(self.bal("Cooking oil"), D("19.5"))
        self.assertEqual(self.bal("200 g pouch"), D("306"))
        self.assertEqual(self.bal("Murukku 200 g"), D("238"))

    def test_variances_and_flags(self):
        r = self.run_obj
        self.assertEqual(r.yield_variance_pct, D("-6.00"))
        self.assertTrue(r.yield_flagged)
        lines = {l.item.name: l for l in r.lines.all()}
        self.assertEqual(lines["Cooking oil"].variance_pct, D("5.00"))
        self.assertTrue(lines["Cooking oil"].flagged)
        self.assertFalse(lines["Flour"].flagged)

    def test_cost_per_packet(self):
        self.assertEqual(self.run_obj.material_cost, D("4055"))
        self.assertEqual(self.run_obj.cost_per_packet, D("31.14"))

    def test_reverse_run_restores_stock(self):
        reverse_production_run(self.run_obj, self.user, "Wrong entry")
        self.assertEqual(self.bal("Flour"), D("160"))
        self.assertEqual(self.bal("Cooking oil"), D("30"))
        self.assertEqual(self.bal("200 g pouch"), D("500"))
        self.assertEqual(self.bal("Murukku 200 g"), D("50"))
        self.run_obj.refresh_from_db()
        self.assertEqual(self.run_obj.status, "reversed")
        with self.assertRaises(ValueError):
            reverse_production_run(self.run_obj, self.user, "Again")

    def test_cannot_reverse_when_output_already_sold(self):
        StockLedger.objects.create(
            item=self.i["Murukku 200 g"], qty=D("-100"), move_type="dispatch",
            source_type="Invoice", source_id=1, created_by=self.user)
        with self.assertRaises(StockError):
            reverse_production_run(self.run_obj, self.user, "Wrong entry")
class ProductionViewTests(TestCase):
    def test_purchase_and_run_forms(self):
        call_command("seed_benchmark")
        c = Client()
        self.assertTrue(c.login(username="production1", password="Test@1234"))
        items = {i.name: i for i in Item.objects.all()}

        r = c.post("/production/purchases/new/", {
            "supplier": Supplier.objects.first().pk, "item": items["Flour"].pk,
            "qty": "60", "rate": "45"})
        self.assertEqual(r.status_code, 302)

        data = {"product": items["Murukku 200 g"].pk, "batches": "1",
                "actual_output": "188", "labour": "1200", "power": "600"}
        for name, actual, waste in [
            ("Flour", "40", "0"), ("Cooking oil", "10.5", "0"),
            ("Salt and spice mix", "1.2", "0"), ("200 g pouch", "194", "6"),
            ("Carton (20 packets)", "9", "0"),
        ]:
            data[f"actual_{items[name].pk}"] = actual
            data[f"waste_{items[name].pk}"] = waste
        r = c.post("/production/runs/new/", data)
        self.assertEqual(r.status_code, 302)

        run = ProductionRun.objects.get()
        self.assertEqual(run.cost_per_packet, D("31.14"))
        self.assertEqual(items["Flour"].balance(), D("120"))
        self.assertEqual(c.get(f"/production/runs/{run.pk}/").status_code, 200)
        self.assertEqual(c.get("/stock/").status_code, 200)
        self.assertEqual(c.get(f"/stock/{items['Flour'].pk}/").status_code, 200)
    def test_purchase_in_grams(self):
        call_command("seed_benchmark")
        c = Client()
        self.assertTrue(c.login(username="production1", password="Test@1234"))
        flour = Item.objects.get(name="Flour")
        supplier = Supplier.objects.first().pk

        r = c.post("/production/purchases/new/", {
            "supplier": supplier, "item": flour.pk, "qty": "60000", "unit": "g", "rate": "45"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(flour.balance(), D("160"))        # 100 + 60 kg

        r = c.post("/production/purchases/new/", {          # litres for a kg item is refused
            "supplier": supplier, "item": flour.pk, "qty": "5", "unit": "litre", "rate": "45"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(flour.balance(), D("160"))