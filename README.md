# Order-to-Audit System: Sri Murugan Snacks (prototype)

A working prototype that takes a small snack factory from a **salesman's order** to the **monthly auditor's report**. Every transaction is entered once, at its source, and flows into stock, production, costing and accounts.

Built by **Piramu** for the NIT Tiruchirappalli (Centre for Digital Infrastructure) winter internship shortlisting task.

## Submission links

| Item | Link |
|---|---|
| Repository | [paste GitHub URL] |
| Demo video (max 8 min) | [paste unlisted YouTube/Drive URL] |
| Live demo | [paste hosted URL, or "run locally, see below"] |
| Design note | [`DESIGN.md`](DESIGN.md) |

## How the system fits together

```
SALES LOOP       Salesman order -> Admin verifies (stock check) -> GST invoice -> Dispatch (stock down) -> Payments / outstanding
                                                                                      |
                                                                          FINISHED-GOODS STOCK
                                                                                      |
PRODUCTION LOOP  Purchase -> Raw stock -> Issued per BOM -> Production run -> Output (stock up) -> Variance + cost per packet

Both loops feed the reports: sales register, GST, stock ledger, production variance, cost per packet, outstanding.
```

## Run it

### Option 1: Docker (one command)

```bash
docker compose up --build
```

Open http://127.0.0.1:8000/. The database is migrated and the section 5 benchmark data is loaded automatically.

### Option 2: Locally

Requirements: Python 3.11+, MySQL 8.

```bash
python -m venv venv
venv\Scripts\activate            # Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
```

1. Create an empty database: `CREATE DATABASE order_to_audit CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`
2. Copy `.env.example` to `.env` and fill in your MySQL password (and port if it is not 3306).
3. Then:

```bash
python manage.py migrate
python manage.py seed_benchmark
python manage.py runserver
```

To reset to a clean benchmark state: `python manage.py flush` then `python manage.py seed_benchmark`.

To open it on a phone on the same Wi-Fi: `python manage.py runserver 0.0.0.0:8000`, then visit `http://<your-pc-ip>:8000`.

### Tests

```bash
python manage.py test
```

The tests cover stock balances, BOM variance, GST maths, invoice numbering, credit notes, run reversal, unit conversion, report totals and role access.

## Test logins

All demo accounts use the password `Test@1234`. They are created by the seed command and contain no real data.

| Role | Username | Lands on |
|---|---|---|
| Salesman A (Retailer A) | `salesman_a` | New order (mobile layout) |
| Salesman B (Distributor B) | `salesman_b` | New order |
| Factory admin | `admin1` | Orders, invoices, dispatch, payments |
| Production supervisor | `production1` | Production runs, purchases, stock |
| Accountant / auditor (read-only) | `auditor1` | Reports, invoices, audit log |
| Owner | `owner1` | Dashboard |

## Stack and why

**Django + MySQL, server-rendered mobile-friendly pages.** Django provides authentication, role checks, migrations and database transactions out of the box, which matters most for a ledger-based stock design where a failed step must never leave half-saved stock. Server-rendered pages keep the system a single deployable unit and the layout is responsive for the salesman's phone. Reports and PDFs use `reportlab` and `openpyxl`.

## Features against the section 6 tiers

**Must have (all built)**
- Login with 5 roles (salesman, admin, production, auditor, owner); a wrong role gets 403
- Product, customer, raw-material, supplier and BOM masters (Django admin)
- Mobile order entry and admin approval (edit quantity and price, approve or reject)
- GST invoice as PDF (GSTIN, HSN, CGST/SGST or IGST by place of supply, numbering by financial year)
- Production run that updates raw-material and finished-goods stock automatically
- Planned vs actual consumption and yield, with variance shown
- Stock summary and stock ledger
- Sales register and stock report, exportable to Excel/CSV

**Should have (all built)**
- Purchases and supplier records; payments, outstanding and ageing
- Cost per packet with overheads; GST summary (GSTR-1 / GSTR-3B shape) and HSN summary
- Variance alerts beyond the BOM tolerance; owner dashboard

**Also built**
- Credit notes (invoice cancellation with its own number series), production run reversal, and an audit log
- Unit conversion helper (kg/g, litre/ml, piece/packet, cartons of packets)
- 12 reports, each exportable to Excel, CSV and PDF with a date range
- WhatsApp share link for invoices (signed link, expires in 30 days)

**Not built (stretch)**: offline order sync, batch and expiry tracking, low-stock alerts, production planning from orders, GPS check-in, Tally export, e-invoice / e-way bill, Tamil interface.

## Benchmark results (section 5)

Reproduced through the screens and by automated tests, starting from `python manage.py seed_benchmark`.

| Check | Expected | Result |
|---|---|---|
| Flour closing balance | 120 kg | 120 kg |
| Oil closing balance | 19.5 L | 19.5 L |
| Pouches closing balance | 306 | 306 |
| Finished goods after run | 238 | 238 |
| Finished goods after Retailer A dispatch | 88 | 88 |
| Yield variance | 188 vs 200, -6%, flagged | -6.00%, flagged |
| Oil consumption variance | +5%, flagged | +5.00%, flagged |
| Retailer A invoice | 7,500 + 187.50 + 187.50 = 7,875 | 7,875.00 (CGST + SGST), `INV/2026-27/0001` |
| Retailer A outstanding | 3,875 | 3,875.00 |
| Distributor B order | Shortage of 32; IGST if invoiced | Shortage of 32 shown and approval blocked. If invoiced (for example 88 packets), IGST 5% applies with no CGST/SGST |
| Cost per packet | Own figure | **Rs. 31.14** |

**Spice mix, cartons and pouches:** spice 5 - 1.2 = 3.8 kg; cartons 30 - 9 = 21; pouches 500 - 194 = 306 (188 good + 6 damaged, stored as 188 issued and 6 wastage so scrap stays visible in the ledger).

**Cost per packet method:** raw materials and packaging are valued at the **weighted-average purchase rate** of all receipts to date. Flour = (100 x 42 + 60 x 45) / 160 = Rs. 43.125/kg. For the run:

| Item | Amount (Rs.) |
|---|---|
| Flour 40 kg x 43.125 | 1,725.00 |
| Oil 10.5 L x 140 | 1,470.00 |
| Spice mix 1.2 kg x 200 | 240.00 |
| Pouches 194 x 2.50 | 485.00 |
| Cartons 9 x 15 | 135.00 |
| **Materials** | **4,055.00** |
| Labour | 1,200.00 |
| Gas / power | 600.00 |
| **Total run cost** | **5,855.00** |

Cost per packet = 5,855 / **188 good packets** = **Rs. 31.14** (divided by actual good output, not the 200 expected, so the cost of wastage is absorbed by the good packets). Margin against the Rs. 50 price is Rs. 18.86 (37.7%).

**Why this method:** weighted average is stable and easy to explain to an auditor. FIFO would use the cheaper Rs. 42 opening flour first and give about Rs. 30.90 per packet; the difference comes only from the valuation method. **Overhead rule:** labour and gas/power are entered per run and charged fully to that run's product (one product in the benchmark).

## Design in brief

Full details with the data model are in [`DESIGN.md`](DESIGN.md).

- **Stock is a ledger.** A balance is always the sum of `StockLedger` rows (opening, purchase, production issue, wastage, production output, dispatch, sales return, reversal, adjustment). Nothing overwrites a balance. Each row stores its source document type and id, so every movement is traceable.
- **Money and quantities use `Decimal`**, never floats. GST is rounded half-up to the paisa per line, and SGST is computed as tax minus CGST so the two always add up exactly.
- **Business logic lives in `services.py` files** and runs inside database transactions, so a failed step leaves no partial stock.
- **Posted documents are immutable.** An invoice is cancelled with a credit note, a wrong production run is reversed with opposite ledger rows, and nothing is deleted. Order edits, approvals, dispatches, payments, overhead changes, cancellations and reversals are written to the audit log with user and time.
- **Variance rules** come from the BOM (tolerance 3%): material is flagged when used above the plan, and yield is flagged when output falls short, both beyond the tolerance.
- **Stock checks happen twice:** at approval (shows required, available and shortage) and again at dispatch, so stock can never go negative.
- **Units** are converted in a single module (`inventory/units.py`); mixing kinds (kg to litre) raises an error.

## Project layout

```
config/       settings and URLs
accounts/     custom user with roles, permissions decorator, audit log
masters/      customers, suppliers, BOM
inventory/    items, stock ledger, stock pages, unit conversion, seed command
production/   purchases, production runs, variance and costing logic
sales/        orders, GST invoices, dispatch, payments, credit notes, invoice PDF
reports/      12 reports, exporters (CSV/Excel/PDF), owner dashboard
templates/    HTML pages
```

## Assumptions

- The factory is in Tamil Nadu (state code 33); GST is 5% on all products; variance tolerance is 3%.
- Stock moves out at dispatch, not at order or invoice.
- Returned goods are restocked as good stock.
- Ageing is counted from the invoice date because no credit terms are modelled.
- Output is entered by the supervisor (it is a physical count); expected output and planned materials are calculated from the BOM.
- All names, GSTINs and prices are invented demo data. The invoice PDF prints "Rs." because the standard PDF font has no rupee symbol.

## Known gaps

- No partial dispatch or partial returns. A credit note cancels the whole invoice and is blocked while payments exist.
- Purchase GST and input tax credit are not modelled.
- Each purchase holds one item. The unit helper is used on the purchase form; the BOM and run form use each item's own unit.
- No batch or expiry tracking and no offline sync.
- Customer-specific prices are not built; prices come from the item's selling price.
- Runs on Django's development server. A production deployment would add gunicorn and static file handling.

## Trying the benchmark by hand

1. `production1`: **Purchase** 60 kg flour at 45.
2. `production1`: **New run**, set oil used to 10.5, pouches used 194 (6 wasted), cartons 9, good output 188. Then add labour 1,200 and gas/power 600.
3. `salesman_a`: order 150 packets for Retailer A. `admin1`: approve, create the invoice, record dispatch.
4. `salesman_b`: order 120 packets for Distributor B. `admin1`: open it and see the shortage of 32.
5. `admin1`: record a 4,000 payment on Retailer A's invoice.
6. `auditor1`: open **Reports** and export any report to Excel, CSV or PDF.
