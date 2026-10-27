CREATE DATABASE IF NOT EXISTS sales_management_app
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE sales_management_app;

CREATE TABLE IF NOT EXISTS users (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(80) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(160) NOT NULL,
    role ENUM('admin', 'staff') NOT NULL DEFAULT 'admin',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS products (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(180) NOT NULL,
    category VARCHAR(100),
    unit_price DECIMAL(12,2) NOT NULL,
    stock_quantity INT UNSIGNED NOT NULL DEFAULT 0,
    reorder_level INT UNSIGNED NOT NULL DEFAULT 5,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_products_price CHECK (unit_price >= 0),
    INDEX idx_products_name (name),
    INDEX idx_products_stock (is_active, stock_quantity, reorder_level)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS customers (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(160) NOT NULL,
    email VARCHAR(254),
    phone VARCHAR(32),
    address VARCHAR(500),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_customers_name (name),
    INDEX idx_customers_email (email)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sales (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    customer_id BIGINT UNSIGNED NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    sale_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_amount DECIMAL(14,2) NOT NULL DEFAULT 0,
    CONSTRAINT chk_sales_total CHECK (total_amount >= 0),
    CONSTRAINT fk_sales_customer FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL,
    CONSTRAINT fk_sales_user FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_sales_date (sale_date),
    INDEX idx_sales_customer_date (customer_id, sale_date)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sales_details (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    sale_id BIGINT UNSIGNED NOT NULL,
    product_id BIGINT UNSIGNED NOT NULL,
    product_name VARCHAR(180) NOT NULL,
    quantity INT UNSIGNED NOT NULL,
    unit_price DECIMAL(12,2) NOT NULL,
    subtotal DECIMAL(14,2) NOT NULL,
    CONSTRAINT chk_sales_detail_quantity CHECK (quantity > 0),
    CONSTRAINT chk_sales_detail_price CHECK (unit_price >= 0 AND subtotal >= 0),
    CONSTRAINT fk_details_sale FOREIGN KEY (sale_id) REFERENCES sales(id),
    CONSTRAINT fk_details_product FOREIGN KEY (product_id) REFERENCES products(id),
    INDEX idx_details_product (product_id, sale_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS inventory_transactions (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    product_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    transaction_type ENUM('restock', 'sale', 'adjustment') NOT NULL,
    quantity INT UNSIGNED NOT NULL,
    reference_sale_id BIGINT UNSIGNED NULL,
    notes VARCHAR(500),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_inventory_product FOREIGN KEY (product_id) REFERENCES products(id),
    CONSTRAINT fk_inventory_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_inventory_sale FOREIGN KEY (reference_sale_id) REFERENCES sales(id),
    INDEX idx_inventory_created (created_at),
    INDEX idx_inventory_product (product_id, created_at)
) ENGINE=InnoDB;

INSERT INTO products (name, category, unit_price, stock_quantity, reorder_level)
SELECT seed.name, seed.category, seed.unit_price, seed.stock_quantity, seed.reorder_level
FROM (
    SELECT 'Wireless Mouse' AS name, 'Electronics' AS category, 24.99 AS unit_price, 40 AS stock_quantity, 8 AS reorder_level
    UNION ALL SELECT 'Notebook Set', 'Stationery', 8.50, 75, 15
    UNION ALL SELECT 'USB-C Hub', 'Electronics', 39.95, 18, 5
    UNION ALL SELECT 'Desk Organizer', 'Office', 16.00, 3, 5
) seed
WHERE NOT EXISTS (SELECT 1 FROM products WHERE products.name = seed.name);

INSERT INTO customers (name, email, phone, address)
SELECT seed.name, seed.email, seed.phone, seed.address
FROM (
    SELECT 'Avery Morgan' AS name, 'avery@example.com' AS email, '+1 555 0101' AS phone, '18 Market Street' AS address
    UNION ALL SELECT 'Jordan Lee', 'jordan@example.com', '+1 555 0102', '42 Oak Avenue'
) seed
WHERE NOT EXISTS (SELECT 1 FROM customers WHERE customers.email = seed.email);

DROP PROCEDURE IF EXISTS GetSalesByDateRange;
DROP PROCEDURE IF EXISTS GetLowStockProducts;

DELIMITER //
CREATE PROCEDURE GetSalesByDateRange(IN start_date DATE, IN end_date DATE)
BEGIN
    SELECT s.id, s.sale_date, s.total_amount, c.name AS customer_name, u.full_name AS cashier
    FROM sales s
    LEFT JOIN customers c ON c.id = s.customer_id
    JOIN users u ON u.id = s.user_id
    WHERE DATE(s.sale_date) BETWEEN start_date AND end_date
    ORDER BY s.sale_date DESC;
END//

CREATE PROCEDURE GetLowStockProducts()
BEGIN
    SELECT id, name, category, stock_quantity, reorder_level
    FROM products
    WHERE is_active = TRUE AND stock_quantity <= reorder_level
    ORDER BY stock_quantity, name;
END//
DELIMITER ;
