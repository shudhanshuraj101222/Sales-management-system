import os
import re
import secrets
from datetime import date, timedelta, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps

import mysql.connector
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_connection

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE") == "1"
if not app.config["SECRET_KEY"]:
    raise RuntimeError("Set SECRET_KEY in your environment before starting the application.")


@app.before_request
def protect_post_requests():
    if request.method == "POST":
        expected = session.get("_csrf_token", "")
        supplied = request.form.get("_csrf_token", "")
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            abort(400)


@app.context_processor
def provide_csrf_token():
    def csrf_token():
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_urlsafe(32)
        return session["_csrf_token"]

    return {"csrf_token": csrf_token}


@app.cli.command("create-admin")
def create_admin():
    """Create an administrator account interactively."""
    import click

    username = click.prompt("Admin username").strip()
    full_name = click.prompt("Full name").strip()
    password = click.prompt("Password (minimum 10 characters)", hide_input=True, confirmation_prompt=True)
    if not username or not full_name or len(password) < 10:
        raise click.ClickException("Username and full name are required; password must be at least 10 characters.")
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO users (username, password_hash, full_name, role) VALUES (%s, %s, %s, 'admin')",
            (username, generate_password_hash(password), full_name),
        )
        connection.commit()
        click.echo("Administrator account created.")
    except mysql.connector.Error as exc:
        connection.rollback()
        raise click.ClickException("Could not create account. Check that the username is unique and the database is available.") from exc
    finally:
        connection.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def fetch_all(sql, params=()):
    connection = get_connection()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        connection.close()


def fetch_one(sql, params=()):
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def parse_money(value, label):
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValueError(f"{label} must be a valid amount.")
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{label} cannot be negative.")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_positive_int(value, label):
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a whole number.")
    if result < 1:
        raise ValueError(f"{label} must be greater than zero.")
    return result


def parse_nonnegative_int(value, label):
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a whole number.")
    if result < 0:
        raise ValueError(f"{label} cannot be negative.")
    return result


def parse_filter_date(value, label):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"{label} must be a valid date.")


def validate_email(value):
    if value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("Enter a valid email address.")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = fetch_one(
            "SELECT id, username, password_hash, full_name, role FROM users WHERE username = %s AND is_active = 1",
            (username,),
        )
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.update(user_id=user["id"], username=user["username"], full_name=user["full_name"], role=user["role"])
            return redirect(url_for("dashboard"))
        flash("The username or password is incorrect.", "error")
    return render_template("login.html")


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    username = request.form.get("username", "").strip()
    full_name = request.form.get("full_name", "").strip()
    password = request.form.get("password", "")
    password_confirmation = request.form.get("password_confirmation", "")
    if request.method == "POST":
        if not username or len(username) > 80:
            flash("Enter a username between 1 and 80 characters.", "error")
        elif not full_name or len(full_name) > 160:
            flash("Enter your name (up to 160 characters).", "error")
        elif len(password) < 10:
            flash("Password must contain at least 10 characters.", "error")
        elif password != password_confirmation:
            flash("The passwords do not match.", "error")
        else:
            connection = get_connection()
            lock_acquired = False
            try:
                connection.start_transaction()
                cursor = connection.cursor()
                cursor.execute("SELECT GET_LOCK(%s, 10)", ("sales_management_initial_admin",))
                lock_row = cursor.fetchone()
                lock_acquired = bool(lock_row and lock_row[0] == 1)
                if not lock_acquired:
                    connection.rollback()
                    flash("Administrator setup is busy. Please try again.", "error")
                else:
                    cursor.execute("SELECT id FROM users LIMIT 1")
                    if cursor.fetchone():
                        connection.rollback()
                        flash("An administrator account already exists. Please sign in.", "error")
                        return redirect(url_for("login"))
                    cursor.execute(
                        "INSERT INTO users (username, password_hash, full_name, role) VALUES (%s, %s, %s, 'admin')",
                        (username, generate_password_hash(password), full_name),
                    )
                    connection.commit()
                    flash("Administrator account created. You can now sign in.", "success")
                    return redirect(url_for("login"))
            except mysql.connector.Error:
                connection.rollback()
                app.logger.exception("Initial administrator setup failed.")
                flash("Could not create the account. Check the database connection and try again.", "error")
            finally:
                if lock_acquired:
                    cursor = connection.cursor()
                    cursor.execute("SELECT RELEASE_LOCK(%s)", ("sales_management_initial_admin",))
                connection.close()
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM users LIMIT 1")
        if cursor.fetchone():
            flash("An administrator account already exists. Please sign in.", "error")
            return redirect(url_for("login"))
    finally:
        connection.close()
    return render_template("setup.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    stats = fetch_one(
        """SELECT
            (SELECT COALESCE(SUM(total_amount), 0) FROM sales WHERE DATE(sale_date) = CURDATE()) AS today_revenue,
            (SELECT COUNT(*) FROM sales WHERE DATE(sale_date) = CURDATE()) AS today_orders,
            (SELECT COUNT(*) FROM sales) AS total_sales,
            (SELECT COUNT(*) FROM products WHERE is_active = 1) AS product_count,
            (SELECT COUNT(*) FROM customers WHERE is_active = 1) AS customer_count"""
    )
    recent = fetch_all(
        """SELECT s.id, s.sale_date, s.total_amount, COALESCE(c.name, 'Walk-in customer') AS customer_name
           FROM sales s LEFT JOIN customers c ON c.id = s.customer_id
           ORDER BY s.sale_date DESC LIMIT 6"""
    )
    low_stock = fetch_all(
        "SELECT id, name, stock_quantity, reorder_level FROM products WHERE is_active = 1 AND stock_quantity <= reorder_level ORDER BY stock_quantity LIMIT 5"
    )
    week_start = date.today() - timedelta(days=date.today().weekday())
    weekly = fetch_all(
        """SELECT DATE(sale_date) AS sales_day, SUM(total_amount) AS revenue
           FROM sales WHERE DATE(sale_date) BETWEEN %s AND %s
           GROUP BY DATE(sale_date) ORDER BY sales_day""",
        (week_start, date.today()),
    )
    return render_template(
        "dashboard.html", stats=stats, recent=recent, low_stock=low_stock,
        today=date.today(), weekly=weekly,
        weekly_peak=max((float(row["revenue"]) for row in weekly), default=1) or 1,
    )


@app.route("/products", methods=["GET", "POST"])
@login_required
def products():
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            category = request.form.get("category", "").strip()
            if not name:
                raise ValueError("Product name is required.")
            price = parse_money(request.form.get("unit_price"), "Price")
            stock = parse_nonnegative_int(request.form.get("stock_quantity", "0"), "Stock")
            reorder = parse_nonnegative_int(request.form.get("reorder_level", "5"), "Reorder level")
            connection = get_connection()
            try:
                connection.start_transaction()
                cursor = connection.cursor()
                cursor.execute(
                    "INSERT INTO products (name, category, unit_price, stock_quantity, reorder_level) VALUES (%s, %s, %s, %s, %s)",
                    (name, category or None, price, stock, reorder),
                )
                product_id = cursor.lastrowid
                if stock:
                    cursor.execute(
                        "INSERT INTO inventory_transactions (product_id, user_id, transaction_type, quantity, notes) VALUES (%s, %s, 'restock', %s, 'Opening stock')",
                        (product_id, session["user_id"], stock),
                    )
                connection.commit()
            except mysql.connector.Error:
                connection.rollback()
                raise
            finally:
                connection.close()
            flash("Product added.", "success")
            return redirect(url_for("products"))
        except (ValueError, mysql.connector.Error) as exc:
            flash(str(exc) if isinstance(exc, ValueError) else "Could not save the product. Check for duplicate or invalid values.", "error")
    search = request.args.get("q", "").strip()
    rows = fetch_all(
        """SELECT id, name, category, unit_price, stock_quantity, reorder_level
           FROM products WHERE is_active = 1 AND (%s = '' OR name LIKE %s OR category LIKE %s)
           ORDER BY name""",
        (search, f"%{search}%", f"%{search}%"),
    )
    return render_template("products.html", products=rows, search=search)


@app.route("/products/<int:product_id>/edit", methods=["POST"])
@login_required
def edit_product(product_id):
    try:
        name = request.form.get("name", "").strip()
        if not name:
            raise ValueError("Product name is required.")
        price = parse_money(request.form.get("unit_price"), "Price")
        reorder = parse_nonnegative_int(request.form.get("reorder_level", "5"), "Reorder level")
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """UPDATE products SET name=%s, category=%s, unit_price=%s, reorder_level=%s
                   WHERE id=%s AND is_active=1""",
                (name, request.form.get("category", "").strip() or None, price, reorder, product_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Product not found.")
            connection.commit()
        finally:
            connection.close()
        flash("Product updated.", "success")
    except (ValueError, mysql.connector.Error) as exc:
        flash(str(exc) if isinstance(exc, ValueError) else "Could not update the product.", "error")
    return redirect(url_for("products"))


@app.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
def delete_product(product_id):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE products SET is_active=0 WHERE id=%s AND is_active=1", (product_id,))
        connection.commit()
        flash("Product archived." if cursor.rowcount else "Product not found.", "success" if cursor.rowcount else "error")
    except mysql.connector.Error:
        connection.rollback()
        flash("Could not archive the product.", "error")
    finally:
        connection.close()
    return redirect(url_for("products"))


@app.route("/customers", methods=["GET", "POST"])
@login_required
def customers():
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip() or None
            phone = request.form.get("phone", "").strip() or None
            if not name:
                raise ValueError("Customer name is required.")
            validate_email(email)
            connection = get_connection()
            try:
                cursor = connection.cursor()
                cursor.execute(
                    "INSERT INTO customers (name, email, phone, address) VALUES (%s, %s, %s, %s)",
                    (name, email, phone, request.form.get("address", "").strip() or None),
                )
                connection.commit()
            finally:
                connection.close()
            flash("Customer added.", "success")
            return redirect(url_for("customers"))
        except (ValueError, mysql.connector.Error) as exc:
            flash(str(exc) if isinstance(exc, ValueError) else "Could not save customer details.", "error")
    search = request.args.get("q", "").strip()
    rows = fetch_all(
        """SELECT c.id, c.name, c.email, c.phone, c.address, c.created_at, COUNT(s.id) AS order_count
           FROM customers c LEFT JOIN sales s ON s.customer_id=c.id
           WHERE c.is_active=1 AND (%s='' OR c.name LIKE %s OR c.email LIKE %s OR c.phone LIKE %s)
           GROUP BY c.id, c.created_at ORDER BY c.name""",
        (search, f"%{search}%", f"%{search}%", f"%{search}%"),
    )
    return render_template("customers.html", customers=rows, search=search)


@app.route("/customers/<int:customer_id>/edit", methods=["POST"])
@login_required
def edit_customer(customer_id):
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip() or None
    if not name:
        flash("Customer name is required.", "error")
        return redirect(url_for("customers"))
    try:
        validate_email(email)
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE customers SET name=%s, email=%s, phone=%s, address=%s WHERE id=%s AND is_active=1",
                (name, email, request.form.get("phone", "").strip() or None,
                 request.form.get("address", "").strip() or None, customer_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Customer not found.")
            connection.commit()
        finally:
            connection.close()
        flash("Customer updated.", "success")
    except (ValueError, mysql.connector.Error) as exc:
        flash(str(exc) if isinstance(exc, ValueError) else "Could not update customer details.", "error")
    return redirect(url_for("customers"))


@app.route("/customers/<int:customer_id>/delete", methods=["POST"])
@login_required
def delete_customer(customer_id):
    try:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("UPDATE customers SET is_active=0 WHERE id=%s AND is_active=1", (customer_id,))
            connection.commit()
            flash("Customer archived." if cursor.rowcount else "Customer not found.", "success" if cursor.rowcount else "error")
        finally:
            connection.close()
    except mysql.connector.Error:
        flash("Could not archive customer details.", "error")
    return redirect(url_for("customers"))


@app.route("/sales/new", methods=["GET", "POST"])
@login_required
def create_sale():
    if request.method == "POST":
        connection = get_connection()
        try:
            customer_value = request.form.get("customer_id", "").strip()
            customer_id = parse_positive_int(customer_value, "Customer") if customer_value else None
            raw_ids = request.form.getlist("product_id[]")
            raw_quantities = request.form.getlist("quantity[]")
            if not raw_ids or len(raw_ids) != len(raw_quantities):
                raise ValueError("Add at least one product to the sale.")
            quantities = {}
            for raw_id, raw_qty in zip(raw_ids, raw_quantities):
                product_id = parse_positive_int(raw_id, "Product")
                qty = parse_positive_int(raw_qty, "Quantity")
                quantities[product_id] = quantities.get(product_id, 0) + qty
            connection.start_transaction()
            cursor = connection.cursor(dictionary=True)
            if customer_id is not None:
                cursor.execute("SELECT id FROM customers WHERE id=%s AND is_active=1", (customer_id,))
                if not cursor.fetchone():
                    raise ValueError("Select a valid customer.")
            products_by_id = {}
            for product_id in sorted(quantities):
                cursor.execute(
                    "SELECT id, name, unit_price, stock_quantity FROM products WHERE id=%s AND is_active=1 FOR UPDATE",
                    (product_id,),
                )
                product = cursor.fetchone()
                if not product:
                    raise ValueError("One of the selected products is no longer available.")
                if product["stock_quantity"] < quantities[product_id]:
                    raise ValueError(f"Insufficient stock for {product['name']}. Available: {product['stock_quantity']}.")
                products_by_id[product_id] = product
            total = sum((products_by_id[pid]["unit_price"] * qty for pid, qty in quantities.items()), Decimal("0.00"))
            cursor.execute(
                "INSERT INTO sales (customer_id, user_id, total_amount) VALUES (%s, %s, %s)",
                (customer_id, session["user_id"], total),
            )
            sale_id = cursor.lastrowid
            for product_id, qty in quantities.items():
                product = products_by_id[product_id]
                cursor.execute(
                    "INSERT INTO sales_details (sale_id, product_id, product_name, quantity, unit_price, subtotal) VALUES (%s, %s, %s, %s, %s, %s)",
                    (sale_id, product_id, product["name"], qty, product["unit_price"], product["unit_price"] * qty),
                )
                cursor.execute(
                    "UPDATE products SET stock_quantity=stock_quantity-%s WHERE id=%s AND stock_quantity >= %s",
                    (qty, product_id, qty),
                )
                if cursor.rowcount != 1:
                    raise ValueError(f"Stock changed while processing {product['name']}. Please try again.")
                cursor.execute(
                    "INSERT INTO inventory_transactions (product_id, user_id, transaction_type, quantity, reference_sale_id, notes) VALUES (%s, %s, 'sale', %s, %s, %s)",
                    (product_id, session["user_id"], qty, sale_id, f"Sale #{sale_id}"),
                )
            connection.commit()
            flash("Sale recorded and inventory updated.", "success")
            return redirect(url_for("invoice", sale_id=sale_id))
        except (ValueError, mysql.connector.Error) as exc:
            connection.rollback()
            flash(str(exc) if isinstance(exc, ValueError) else "The sale could not be completed. No changes were saved.", "error")
        finally:
            connection.close()
    customer_rows = fetch_all("SELECT id, name FROM customers WHERE is_active=1 ORDER BY name")
    product_rows = fetch_all(
        "SELECT id, name, category, unit_price, stock_quantity FROM products WHERE is_active=1 AND stock_quantity>0 ORDER BY name"
    )
    return render_template("create_sale.html", customers=customer_rows, products=product_rows)


@app.route("/sales")
@login_required
def sales_history():
    search = request.args.get("q", "").strip()
    date_from, date_to = request.args.get("from", "").strip(), request.args.get("to", "").strip()
    sort = request.args.get("sort", "date")
    direction = request.args.get("direction", "desc").lower()
    sort_columns = {
        "date": "s.sale_date",
        "amount": "s.total_amount",
        "customer": "customer_name",
        "id": "s.id",
    }
    if sort not in sort_columns:
        sort = "date"
    if direction not in {"asc", "desc"}:
        direction = "desc"
    try:
        start_date, end_date = parse_filter_date(date_from, "Start date"), parse_filter_date(date_to, "End date")
        if start_date and end_date and start_date > end_date:
            raise ValueError("Start date cannot be after end date.")
    except ValueError as exc:
        flash(str(exc), "error")
        date_from, date_to = "", ""
    rows = fetch_all(
        """SELECT s.id, s.sale_date, s.total_amount, COALESCE(c.name, 'Walk-in customer') AS customer_name,
                  u.full_name AS cashier
           FROM sales s LEFT JOIN customers c ON c.id=s.customer_id JOIN users u ON u.id=s.user_id
           WHERE (%s='' OR CAST(s.id AS CHAR)=%s OR c.name LIKE %s OR EXISTS (
                    SELECT 1 FROM sales_details sd
                    WHERE sd.sale_id=s.id AND sd.product_name LIKE %s))
             AND (%s='' OR DATE(s.sale_date)>=%s) AND (%s='' OR DATE(s.sale_date)<=%s)
           ORDER BY """ + sort_columns[sort] + " " + direction + """ LIMIT 250""",
        (search, search, f"%{search}%", f"%{search}%", date_from, date_from, date_to, date_to),
    )
    return render_template(
        "sales.html", sales=rows, search=search, date_from=date_from, date_to=date_to,
        sort=sort, direction=direction,
    )


@app.route("/sales/<int:sale_id>")
@login_required
def invoice(sale_id):
    sale = fetch_one(
        """SELECT s.id, s.sale_date, s.total_amount, COALESCE(c.name, 'Walk-in customer') AS customer_name,
                  c.phone, c.email, u.full_name AS cashier
           FROM sales s LEFT JOIN customers c ON c.id=s.customer_id JOIN users u ON u.id=s.user_id WHERE s.id=%s""",
        (sale_id,),
    )
    if not sale:
        flash("Sale record not found.", "error")
        return redirect(url_for("sales_history"))
    details = fetch_all(
        """SELECT sd.product_name, sd.quantity, sd.unit_price, sd.subtotal
           FROM sales_details sd WHERE sd.sale_id=%s ORDER BY sd.id""",
        (sale_id,),
    )
    return render_template("invoice.html", sale=sale, details=details)


@app.route("/inventory", methods=["GET", "POST"])
@login_required
def inventory():
    if request.method == "POST":
        try:
            product_id = parse_positive_int(request.form.get("product_id"), "Product")
            quantity = parse_positive_int(request.form.get("quantity"), "Quantity")
            connection = get_connection()
            try:
                connection.start_transaction()
                cursor = connection.cursor()
                cursor.execute("SELECT id FROM products WHERE id=%s AND is_active=1 FOR UPDATE", (product_id,))
                if not cursor.fetchone():
                    raise ValueError("Product not found.")
                cursor.execute("UPDATE products SET stock_quantity=stock_quantity+%s WHERE id=%s", (quantity, product_id))
                cursor.execute(
                    "INSERT INTO inventory_transactions (product_id, user_id, transaction_type, quantity, notes) VALUES (%s, %s, 'restock', %s, %s)",
                    (product_id, session["user_id"], quantity, request.form.get("notes", "").strip() or None),
                )
                connection.commit()
            finally:
                connection.close()
            flash("Stock replenished.", "success")
            return redirect(url_for("inventory"))
        except (ValueError, mysql.connector.Error) as exc:
            flash(str(exc) if isinstance(exc, ValueError) else "Could not update stock.", "error")
    products_rows = fetch_all(
        "SELECT id, name, category, stock_quantity, reorder_level FROM products WHERE is_active=1 ORDER BY stock_quantity, name"
    )
    transactions = fetch_all(
        """SELECT it.id, it.transaction_type, it.quantity, it.created_at, it.notes, p.name AS product_name,
                  it.reference_sale_id
           FROM inventory_transactions it JOIN products p ON p.id=it.product_id
           ORDER BY it.created_at DESC LIMIT 30"""
    )
    return render_template("inventory.html", products=products_rows, transactions=transactions)


@app.route("/reports")
@login_required
def reports():
    today = date.today()
    default_from = today.replace(day=1).isoformat()
    week_from = (today - timedelta(days=today.weekday())).isoformat()
    year_from = today.replace(month=1, day=1).isoformat()
    date_from = request.args.get("from", default_from)
    date_to = request.args.get("to", today.isoformat())
    try:
        start_date, end_date = parse_filter_date(date_from, "Start date"), parse_filter_date(date_to, "End date")
        if not start_date or not end_date or start_date > end_date:
            raise ValueError("Choose a valid date range with the start date on or before the end date.")
    except ValueError as exc:
        flash(str(exc), "error")
        date_from, date_to = default_from, today.isoformat()
    summary = fetch_one(
        """SELECT COUNT(*) AS order_count, COALESCE(SUM(total_amount),0) AS revenue,
                  COALESCE(AVG(total_amount),0) AS average_order
           FROM sales WHERE DATE(sale_date) BETWEEN %s AND %s""",
        (date_from, date_to),
    )
    daily = fetch_all(
        """SELECT DATE(sale_date) AS sales_day, SUM(total_amount) AS revenue
           FROM sales WHERE DATE(sale_date) BETWEEN %s AND %s
           GROUP BY DATE(sale_date) ORDER BY sales_day""",
        (date_from, date_to),
    )
    top_products = fetch_all(
        """SELECT sd.product_name AS name, SUM(sd.quantity) AS units_sold, SUM(sd.subtotal) AS revenue
           FROM sales_details sd JOIN sales s ON s.id=sd.sale_id JOIN products p ON p.id=sd.product_id
           WHERE DATE(s.sale_date) BETWEEN %s AND %s
           GROUP BY p.id, sd.product_name ORDER BY units_sold DESC LIMIT 5""",
        (date_from, date_to),
    )
    peak = max((float(item["revenue"]) for item in daily), default=1) or 1
    return render_template(
        "reports.html", summary=summary, daily=daily, top_products=top_products,
        date_from=date_from, date_to=date_to, chart_peak=peak, today=today,
        presets={"day": today.isoformat(), "week": week_from, "month": default_from, "year": year_from},
    )


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        user = fetch_one("SELECT password_hash FROM users WHERE id=%s", (session["user_id"],))
        if not user or not check_password_hash(user["password_hash"], current_password):
            flash("Current password is incorrect.", "error")
        elif len(new_password) < 10:
            flash("New password must contain at least 10 characters.", "error")
        else:
            connection = get_connection()
            try:
                cursor = connection.cursor()
                cursor.execute("UPDATE users SET password_hash=%s WHERE id=%s", (generate_password_hash(new_password), session["user_id"]))
                connection.commit()
                flash("Password updated.", "success")
            except mysql.connector.Error:
                connection.rollback()
                flash("Could not update your password.", "error")
            finally:
                connection.close()
    user = fetch_one("SELECT username, full_name, role, created_at FROM users WHERE id=%s", (session["user_id"],))
    return render_template("settings.html", user=user)


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="The page you requested could not be found."), 404


@app.errorhandler(500)
def server_error(_error):
    return render_template("error.html", code=500, message="Something went wrong. Please try again."), 500


@app.errorhandler(mysql.connector.Error)
def database_error(error):
    app.logger.exception("A database operation failed: %s", error)
    return render_template(
        "error.html",
        code=503,
        message="Database unavailable. Check your local MySQL settings and restart the application.",
    ), 503


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
