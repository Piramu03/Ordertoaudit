from datetime import date
from decimal import Decimal as D
from django.test import Client

from .models import Invoice, Order
from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from inventory.models import Item
from masters.models import Customer, Supplier
from production.services import StockError, record_purchase, save_production_run
from .services import (
    ShortageError, approve_order, create_invoice, dispatch_invoice,
    place_order, record_payment, stock_check, customer_outstanding,
    cancel_invoice,
)
from accounts.models import AuditLog
TODAY = date(2026, 11, 18)


class BenchmarkSalesTests(TestCase):
    def setUp(self):
        call_command("seed_benchmark")
        self.admin = User.objects.get(username="admin1")
        self.prod = User.objects.get(username="production1")
        self.sal_a = User.objects.get(username="salesman_a")
        self.sal_b = User.objects.get(username="salesman_b")
        self.i = {x.name: x for x in Item.objects.all()}
        self.murukku = self.i["Murukku 200 g"]
        self.retailer = Customer.objects.get(name="Retailer A")
        self.distributor = Customer.objects.get(name="Distributor B")

        # production run from the benchmark -> finished goods = 238
        record_purchase(supplier=Supplier.objects.first(), item=self.i["Flour"],
                        qty=D("60"), rate=D("45"), date=TODAY, user=self.prod)
        usage = {
            self.i["Flour"].id: (D("40"), D("0")),
            self.i["Cooking oil"].id: (D("10.5"), D("0")),
            self.i["Salt and spice mix"].id: (D("1.2"), D("0")),
            self.i["200 g pouch"].id: (D("194"), D("6")),
            self.i["Carton (20 packets)"].id: (D("9"), D("0")),
        }
        save_production_run(product=self.murukku, actual_output=188, usage=usage,
                            date=TODAY, user=self.prod,
                            labour_cost=D("1200"), power_cost=D("600"))

    def retailer_invoice(self):
        order = place_order(customer=self.retailer, salesman=self.sal_a,
                            lines=[(self.murukku, 150)])
        approve_order(order, self.admin)
        invoice = create_invoice(order, self.admin, on_date=TODAY)
        dispatch_invoice(invoice, self.admin)
        return invoice

    def test_retailer_a_invoice_dispatch_payment(self):
        self.assertEqual(self.murukku.balance(), D("238"))
        invoice = self.retailer_invoice()

        self.assertEqual(invoice.number, "INV/2026-27/0001")
        self.assertEqual(invoice.taxable_value, D("7500.00"))
        self.assertEqual(invoice.cgst, D("187.50"))
        self.assertEqual(invoice.sgst, D("187.50"))
        self.assertEqual(invoice.igst, D("0"))
        self.assertEqual(invoice.total, D("7875.00"))
        self.assertEqual(self.murukku.balance(), D("88"))

        record_payment(invoice, D("4000"), TODAY, self.admin)
        self.assertEqual(invoice.outstanding, D("3875.00"))
        self.assertEqual(customer_outstanding(self.retailer), D("3875.00"))

    def test_distributor_b_shortage_and_igst(self):
        self.retailer_invoice()                       # stock is now 88
        order = place_order(customer=self.distributor, salesman=self.sal_b,
                            lines=[(self.murukku, 120)])

        check = stock_check(order)[0]
        self.assertEqual(check["available"], D("88"))
        self.assertEqual(check["shortage"], D("32"))

        with self.assertRaises(ShortageError):
            approve_order(order, self.admin)

        # force-approve only to prove the tax logic: Karnataka -> IGST
        approve_order(order, self.admin, allow_shortage=True)
        invoice = create_invoice(order, self.admin, on_date=TODAY)
        self.assertEqual(invoice.igst, D("300.00"))
        self.assertEqual(invoice.cgst, D("0"))
        self.assertEqual(invoice.total, D("6300.00"))

        # dispatch must still be blocked, and stock must not change
        with self.assertRaises(StockError):
            dispatch_invoice(invoice, self.admin)
        self.assertEqual(self.murukku.balance(), D("88"))

    def test_credit_note_restores_stock_and_cancels(self):
        invoice = self.retailer_invoice()                 # dispatched, stock 88
        self.assertEqual(self.murukku.balance(), D("88"))
        cn = cancel_invoice(invoice, self.admin, "Wrong customer", on_date=TODAY)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "cancelled")
        self.assertEqual(cn.number, "CN/2026-27/0001")
        self.assertEqual(cn.total, D("7875.00"))
        self.assertEqual(self.murukku.balance(), D("238"))
        self.assertEqual(customer_outstanding(self.retailer), D("0"))
        self.assertEqual(AuditLog.objects.filter(action="invoice_cancelled").count(), 1)

    def test_cannot_cancel_invoice_with_payment(self):
        invoice = self.retailer_invoice()
        record_payment(invoice, D("4000"), TODAY, self.admin)
        with self.assertRaises(ValueError):
            cancel_invoice(invoice, self.admin, "Mistake", on_date=TODAY)

class ViewFlowTests(TestCase):
    def setUp(self):
        call_command("seed_benchmark")
        self.murukku = Item.objects.get(name="Murukku 200 g")
        self.retailer = Customer.objects.get(name="Retailer A")

    def test_roles_and_order_to_pdf(self):
        c = Client()
        self.assertTrue(c.login(username="salesman_a", password="Test@1234"))
        self.assertEqual(c.get("/sales/orders/").status_code, 403)   # admin-only page

        r = c.post("/sales/orders/new/",
                   {"customer": self.retailer.pk, f"qty_{self.murukku.pk}": "30"})
        self.assertEqual(r.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.amount, D("1500"))

        c.logout()
        self.assertTrue(c.login(username="admin1", password="Test@1234"))
        c.post(f"/sales/orders/{order.pk}/", {"action": "approve"})
        c.post(f"/sales/orders/{order.pk}/", {"action": "invoice"})
        invoice = Invoice.objects.get()
        self.assertEqual(invoice.total, D("1575.00"))

        pdf = c.get(f"/sales/invoices/{invoice.pk}/pdf/")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))