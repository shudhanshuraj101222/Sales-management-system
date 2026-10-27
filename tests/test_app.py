import os
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

from app import app, parse_money, parse_positive_int, parse_nonnegative_int, parse_filter_date, validate_email
from werkzeug.security import generate_password_hash


class FakeSaleCursor:
    def __init__(self, stock_quantity):
        self.stock_quantity = stock_quantity
        self.row = None
        self.rowcount = 0
        self.lastrowid = 501
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        self.rowcount = 0
        if "SELECT id, name, unit_price, stock_quantity" in sql:
            self.row = {
                "id": params[0],
                "name": "USB-C Hub",
                "unit_price": Decimal("39.95"),
                "stock_quantity": self.stock_quantity,
            }
        elif "UPDATE products SET stock_quantity=stock_quantity-" in sql:
            self.rowcount = 1
            self.stock_quantity -= params[0]
        else:
            self.row = None

    def fetchone(self):
        return self.row


class FakeSaleConnection:
    def __init__(self, stock_quantity):
        self.sale_cursor = FakeSaleCursor(stock_quantity)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self, dictionary=False):
        return self.sale_cursor

    def start_transaction(self):
        pass

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class ValidationTests(unittest.TestCase):
    def test_money_is_rounded_to_cents(self):
        self.assertEqual(str(parse_money("12.345", "Price")), "12.35")

    def test_money_rejects_negative_values(self):
        with self.assertRaises(ValueError):
            parse_money("-0.01", "Price")

    def test_quantity_must_be_positive(self):
        with self.assertRaises(ValueError):
            parse_positive_int("0", "Quantity")
        self.assertEqual(parse_positive_int("3", "Quantity"), 3)
        self.assertEqual(parse_nonnegative_int("0", "Stock"), 0)
        with self.assertRaises(ValueError):
            parse_nonnegative_int("-1", "Stock")

    def test_date_filters_and_email_are_validated(self):
        self.assertEqual(parse_filter_date("2026-10-26", "Start date").isoformat(), "2026-10-26")
        with self.assertRaises(ValueError):
            parse_filter_date("not-a-date", "Start date")
        with self.assertRaises(ValueError):
            validate_email("not-an-email")


class RequestTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def sign_in(self):
        with self.client.session_transaction() as browser_session:
            browser_session.update(user_id=7, username="admin", full_name="Admin User", role="admin", _csrf_token="test-token")

    def test_login_page_has_csrf_token_and_rejects_missing_token(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as browser_session:
            token = browser_session["_csrf_token"]
        response = self.client.post("/login", data={"username": "admin", "password": "password"})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(token)

    @patch("app.fetch_one")
    def test_login_accepts_a_valid_password_hash(self, fetch_one):
        fetch_one.return_value = {
            "id": 7,
            "username": "admin",
            "password_hash": generate_password_hash("correct-horse-battery"),
            "full_name": "Admin User",
            "role": "admin",
        }
        self.client.get("/login")
        with self.client.session_transaction() as browser_session:
            token = browser_session["_csrf_token"]
        response = self.client.post(
            "/login",
            data={"username": "admin", "password": "correct-horse-battery", "_csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as browser_session:
            self.assertEqual(browser_session["user_id"], 7)

    @patch("app.fetch_all", return_value=[])
    def test_sales_search_page_renders_with_safe_sort_options(self, fetch_all):
        self.sign_in()
        response = self.client.get("/sales?q=hub&sort=amount&direction=asc")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Sort by", response.data)
        self.assertIn("sales_details", fetch_all.call_args.args[0])

    @patch("app.fetch_all", return_value=[])
    @patch("app.fetch_one", return_value={"order_count": 0, "revenue": 0, "average_order": 0})
    def test_reports_page_renders_period_shortcuts(self, _fetch_one, _fetch_all):
        self.sign_in()
        response = self.client.get("/reports")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"This year", response.data)

    @patch("app.fetch_all")
    @patch("app.fetch_one")
    def test_dashboard_renders_reference_sections(self, fetch_one, fetch_all):
        self.sign_in()
        fetch_one.return_value = {
            "today_revenue": Decimal("0.00"),
            "today_orders": 0,
            "total_sales": 0,
            "product_count": 5,
            "customer_count": 3,
        }
        fetch_all.side_effect = [
            [],
            [{"id": 4, "name": "Desk organizer", "stock_quantity": 2, "reorder_level": 5}],
            [{"sales_day": date.today(), "revenue": Decimal("350.00")}],
        ]
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Welcome back, Admin", response.data)
        self.assertIn(b"Revenue this week", response.data)
        self.assertIn(b"Stock watch", response.data)
        self.assertIn(b"ACTIVE PRODUCTS", response.data)

    @patch("app.fetch_all")
    def test_product_and_customer_pages_render_catalog_layouts(self, fetch_all):
        self.sign_in()
        fetch_all.return_value = [{
            "id": 2, "name": "Desk organizer", "category": "Office",
            "unit_price": Decimal("16.00"), "stock_quantity": 3, "reorder_level": 5,
        }]
        products = self.client.get("/products")
        self.assertEqual(products.status_code, 200)
        self.assertIn(b"Product catalog", products.data)
        self.assertIn(b"Low stock", products.data)
        fetch_all.return_value = [{
            "id": 3, "name": "Avery Morgan", "email": "avery@example.com",
            "phone": "+1 555 0101", "address": None, "created_at": datetime.now(),
            "order_count": 2,
        }]
        customers = self.client.get("/customers")
        self.assertEqual(customers.status_code, 200)
        self.assertIn(b"Customer directory", customers.data)
        self.assertIn(b"SALES", customers.data)

    @patch("app.get_connection")
    def test_sale_decrements_stock_once_and_commits(self, get_connection):
        self.sign_in()
        connection = FakeSaleConnection(stock_quantity=10)
        get_connection.return_value = connection
        response = self.client.post(
            "/sales/new",
            data={"_csrf_token": "test-token", "customer_id": "", "product_id[]": "3", "quantity[]": "2"},
        )
        updates = [
            call for call in connection.sale_cursor.executed
            if "UPDATE products SET stock_quantity=stock_quantity-" in call[0]
        ]
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/sales/501")
        self.assertEqual(len(updates), 1)
        self.assertEqual(connection.sale_cursor.stock_quantity, 8)
        detail_insert = next(
            params for sql, params in connection.sale_cursor.executed
            if "INSERT INTO sales_details" in sql
        )
        self.assertEqual(detail_insert, (501, 3, "USB-C Hub", 2, Decimal("39.95"), Decimal("79.90")))
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertTrue(connection.closed)

    @patch("app.fetch_all", return_value=[])
    @patch("app.get_connection")
    def test_sale_with_insufficient_stock_is_rolled_back(self, get_connection, _fetch_all):
        self.sign_in()
        connection = FakeSaleConnection(stock_quantity=1)
        get_connection.return_value = connection
        response = self.client.post(
            "/sales/new",
            data={"_csrf_token": "test-token", "customer_id": "", "product_id[]": "3", "quantity[]": "2"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(connection.sale_cursor.stock_quantity, 1)
        self.assertFalse(any("INSERT INTO sales (" in sql for sql, _ in connection.sale_cursor.executed))

    def test_all_templates_parse(self):
        for template_name in app.jinja_env.list_templates():
            with self.subTest(template=template_name):
                app.jinja_env.get_template(template_name)


if __name__ == "__main__":
    unittest.main()
