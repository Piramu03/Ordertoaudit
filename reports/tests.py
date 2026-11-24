from decimal import Decimal as D
from io import BytesIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone
from openpyxl import load_workbook

from accounts.models import User
from inventory.models import Item
from masters.models import Customer, Supplier
from production.services import record_purchase, save_production_run
from sales.services import (
    approve_order, cancel_invoice, create_invoice, dispatch_invoice,
    place_order, record_payment,
)

from . import builders as B

TODAY = timezone.localdate()


class ReportTests(TestCase):
    def setUp(self):
        call_command("seed_benchmark")
        self.admin = User.objects.get(username="admin1")
        prod = User.objects.get(username="production1")
        self.i = {x.name: x for x in Item.objects.all()}

        record_purchase(supplier=Supplier.objects.first(), item=self.i["Flour"],
                        qty=D("60"), rate=D("45"), date=TODAY, user=prod)
        usage = {
            self.i["Flour"].id: (D("40"), D("0")),
            self.i["Cooking oil"].id: (D("10.5"), D("0")),
            self.i["Salt and spice mix"].id: (D("1.2"), D("0")),
            self.i["200 g pouch"].id: (D("194"), D("6")),
            self.i["Carton (20 packets)"].id: (D("9"), D("0")),
        }
        save_production_run(product=self.i["Murukku 200 g"], actual_output=188, usage=usage,
                            date=TODAY, user=prod, labour_cost=D("1200"), power_cost=D("600"))

        order = place_order(customer=Customer.objects.get(name="Retailer A"),
                            salesman=User.objects.get(username="salesman_a"),
                            lines=[(self.i["Murukku 200 g"], 150)])
        approve_order(order, self.admin)
        self.invoice = create_invoice(order, self.admin, on_date=TODAY)
        dispatch_invoice(self.invoice, self.admin)

    def test_sales_register_nets_credit_note(self):
        rep = B.sales_register(TODAY, TODAY, {})
        self.assertEqual(len(rep.rows), 1)
        self.assertEqual(rep.totals[6], D("7500.00"))
        self.assertEqual(rep.totals[10], D("7875.00"))

        cancel_invoice(self.invoice, self.admin, "Test", on_date=TODAY)
        rep = B.sales_register(TODAY, TODAY, {})
        self.assertEqual(len(rep.rows), 2)
        self.assertEqual(rep.totals[10], D("0.00"))

    def test_gst_reports(self):
        rep = B.gst_summary(TODAY, TODAY, {})
        t = rep.totals                      # taxable, igst, cgst, sgst, tax
        self.assertEqual((t[4], t[5], t[6], t[7]), (D("7500.00"), D("0"), D("187.50"), D("187.50")))
        hsn = B.gst_hsn(TODAY, TODAY, {})
        self.assertEqual(hsn.rows[0][3], D("150"))
        self.assertEqual(hsn.totals[9], D("7875.00"))

    def test_outstanding_and_collections(self):
        record_payment(self.invoice, D("4000"), TODAY, self.admin)
        rep = B.outstanding(TODAY, TODAY, {})
        self.assertEqual(rep.rows[0][0], "Retailer A")
        self.assertEqual(rep.rows[0][1], D("3875.00"))       # 0-30 days bucket
        self.assertEqual(rep.rows[0][5], D("3875.00"))
        self.assertEqual(B.collections(TODAY, TODAY, {}).totals[5], D("4000.00"))

    def test_stock_summary_reconciles(self):
        rows = {r[0]: r for r in B.stock_summary(TODAY, TODAY, {}).rows}
        flour = rows["Flour"]               # item, type, unit, opening, receipts, issues, closing
        self.assertEqual((flour[3], flour[4], flour[5], flour[6]), (D("100"), D("60"), D("40"), D("120")))
        m = rows["Murukku 200 g"]
        self.assertEqual((m[3], m[4], m[5], m[6]), (D("50"), D("188"), D("150"), D("88")))

    def test_production_and_exports(self):
        prod = B.production(TODAY, TODAY, {})
        self.assertEqual(prod.rows[0][11], D("31.14"))

        c = Client()
        self.assertTrue(c.login(username="auditor1", password="Test@1234"))
        csv_r = c.get("/reports/sales_register/?format=csv")
        self.assertEqual(csv_r.status_code, 200)
        self.assertIn(b"INV/", csv_r.content)

        x = c.get("/reports/gst_summary/?format=xlsx")
        ws = load_workbook(BytesIO(x.content)).active
        self.assertEqual(ws["A1"].value, "GST summary of outward supplies")

        pdf = c.get("/reports/stock_summary/?format=pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        for key in B.REGISTRY:              # every report page opens
            self.assertEqual(c.get(f"/reports/{key}/").status_code, 200, key)

        c.logout()
        self.assertTrue(c.login(username="salesman_a", password="Test@1234"))
        self.assertEqual(c.get("/reports/").status_code, 403)
        c.logout()
        self.assertTrue(c.login(username="salesman_a", password="Test@1234"))
        self.assertEqual(c.get("/reports/").status_code, 403)

    def test_dashboard_and_owner_home(self):
        c = Client()
        ...

    