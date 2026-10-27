# Sales Record Management System

A database-backed sales and inventory application built with Flask, MySQL, and responsive HTML/CSS/JavaScript. Sales, line items, stock deductions, and inventory audit entries are committed in one transaction; failed sales roll back completely.

## Features

- Hashed-password login, logout, session protection, and CSRF-protected form submissions.
- Dashboard with today's revenue/orders, product/customer counts, latest invoices, and low-stock alerts.
- Product and customer create, edit, search, and archive workflows.
- Sales with multiple line items, customer or walk-in selection, server-side price calculation, stock locking/validation, invoice view, and browser printing.
- Inventory levels, audited restock and sale movements, and low-stock thresholds.
- Date-filtered sales history, revenue-by-day report, average order value, and top-selling products.
- Profile settings and password updates.
- MySQL schema with foreign keys, indexes, constraints, sample products/customers, and stored procedures for date-range sales and low-stock lookup.

## Requirements

- Python 3.10 or newer
- MySQL Server 8.0+ (MySQL Workbench is used to execute and inspect the database; Workbench is not the database server)

## Setup

1. Create and activate a virtual environment, then install dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

2. Start MySQL Server. In MySQL Workbench, open `sql/sales_management.sql` and execute the full script. It creates the isolated `sales_management_app` database and tables and inserts sample products/customers. The separate database name avoids overwriting an existing `sales_management` database.

3. Configure the local database credentials without sharing or committing your MySQL password. Copy `.env.example` to `.env`, edit `.env`, and set your MySQL password and a fresh random session secret:

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

   `.env` is excluded by `.gitignore`. Do not commit real credentials or a production `SECRET_KEY`. For an HTTPS deployment, change `SESSION_COOKIE_SECURE=0` to `SESSION_COOKIE_SECURE=1`; leave it at `0` for local HTTP development.

4. Start the local application:

   ```powershell
   flask --app app run
   ```

   Open <http://127.0.0.1:5000>. On first launch, select **Create administrator account** on the sign-in screen and create your account. This setup is available only while there are no users, and the password is stored as a secure hash. Keep `FLASK_DEBUG` unset except during local development.

   Flask loads the `.env` file automatically when `python-dotenv` is installed (included in `requirements.txt`). If port 5000 is already in use, start it on another port:

   ```powershell
   flask --app app run --port 5055
   ```

## Database notes

`app.py` uses parameterized MySQL Connector queries. A sale locks each selected product row (`SELECT ... FOR UPDATE`), checks current stock, records its header and detail lines (including a name and price snapshot), decrements stock once, and inserts one inventory audit row per product. These operations share a database transaction and are rolled back together on any validation or database failure. The application backend is the single owner of sale-time stock updates; the SQL script intentionally has no stock trigger, avoiding double deductions.

Stored procedures can be called from Workbench:

```sql
CALL GetSalesByDateRange('2026-01-01', '2026-12-31');
CALL GetLowStockProducts();
```

The application connects as `DB_USER`; use a dedicated least-privilege MySQL account for deployments rather than a root account.

## Tests

Run the focused application tests:

```powershell
python -m unittest discover -s tests -v
```

The tests cover monetary/quantity validation, authentication, catalog pages, and transactional stock handling. End-to-end database workflow testing requires a configured MySQL Server and the schema above.

## Project layout

```text
app.py                       Flask routes and business logic
database.py                  Environment-configured MySQL connections
requirements.txt             Python dependencies
sql/sales_management.sql     sales_management_app schema, sample data, and stored procedures
templates/                   Login, dashboard, CRUD, inventory, sales, invoice, and report pages
static/css/style.css         Responsive application styling
static/js/script.js          Dynamic sale lines and client-side totals/validation
tests/                       Unit tests
```
