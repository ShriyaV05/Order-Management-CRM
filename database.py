import sqlite3
import os
from datetime import datetime, timezone
from auth import hash_password

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "popcone.db"))

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # 1. Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('ADMIN', 'MEMBER')),
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # 2. Sessions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # 3. Settings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # 4. Inventory table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        flavour TEXT PRIMARY KEY,
        current_stock INTEGER NOT NULL DEFAULT 0,
        low_stock_threshold INTEGER NOT NULL DEFAULT 20,
        updated_at TEXT NOT NULL
    );
    """)

    # 5. Inventory movements table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        flavour TEXT NOT NULL,
        movement_type TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        reference TEXT NOT NULL,
        created_by TEXT NOT NULL
    );
    """)

    # 6. Orders table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT UNIQUE NOT NULL,
        customer_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        address TEXT NOT NULL,
        pin_code TEXT NOT NULL,
        state TEXT NOT NULL,
        district TEXT NOT NULL,
        total_bottles INTEGER NOT NULL,
        total_weight_grams INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        product_amount REAL NOT NULL,
        delivery_fee REAL NOT NULL,
        final_amount REAL NOT NULL,
        payment TEXT NOT NULL CHECK(payment IN ('Paid', 'COD')),
        dispatch_state TEXT NOT NULL CHECK(dispatch_state IN ('PLACED', 'DISPATCHED')),
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        edited_by TEXT NOT NULL,
        edited_at TEXT NOT NULL
    );
    """)

    # 7. Order items table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        flavour TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        line_amount REAL NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE
    );
    """)

    # 8. Audit logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        user TEXT NOT NULL,
        action TEXT NOT NULL,
        entity_id TEXT,
        details TEXT NOT NULL
    );
    """)

    conn.commit()

    # Seed Initial Data if empty
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Check users
    cursor.execute("SELECT COUNT(*) FROM users;")
    if cursor.fetchone()[0] == 0:
        default_pwd_hash = hash_password("Popcone@123")
        initial_users = [
            ("suguna@popcone", "Suguna", "MEMBER", default_pwd_hash, now_str, now_str),
            ("vaishnavi@popcone", "Vaishnavi", "MEMBER", default_pwd_hash, now_str, now_str),
            ("harini@popcone", "Harini", "MEMBER", default_pwd_hash, now_str, now_str),
            ("shriya@popcone", "Shriya", "MEMBER", default_pwd_hash, now_str, now_str),
            ("ashish@popcone", "Ashish", "ADMIN", default_pwd_hash, now_str, now_str),
        ]
        cursor.executemany("""
        INSERT INTO users (username, display_name, role, password_hash, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?);
        """, initial_users)
        conn.commit()

    # Check settings
    cursor.execute("SELECT COUNT(*) FROM settings;")
    if cursor.fetchone()[0] == 0:
        initial_settings = [
            ("bottle_price", "149", now_str),
            ("low_stock_threshold", "20", now_str),
        ]
        cursor.executemany("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?);", initial_settings)
        conn.commit()

    # Check inventory
    cursor.execute("SELECT COUNT(*) FROM inventory;")
    if cursor.fetchone()[0] == 0:
        initial_inventory = [
            ("Tomato", 0, 20, now_str),
            ("Cheese", 0, 20, now_str),
            ("Sour Cream", 0, 20, now_str),
            ("Peri Peri", 0, 20, now_str),
        ]
        cursor.executemany("INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at) VALUES (?, ?, ?, ?);", initial_inventory)
        conn.commit()

    conn.close()

def reset_crm_data():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM order_items;")
    cursor.execute("DELETE FROM orders;")
    cursor.execute("DELETE FROM inventory_movements;")
    cursor.execute("DELETE FROM audit_logs WHERE action IN ('Order Created', 'Order Edited', 'Order Deleted', 'Dispatched', 'Undispatched', 'Inventory Reset', 'Inventory Stock Added', 'Inventory Adjustment');")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE inventory SET current_stock = 0, updated_at = ?;", (now_str,))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
