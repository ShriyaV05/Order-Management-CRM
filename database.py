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
        # Initial flavour stock: Tomato 85, Cheese 0, Sour Cream 0, Peri Peri 12
        # (Directly exhibits low stock alerts for Cheese, Sour Cream, Peri Peri as described in prompt)
        initial_inventory = [
            ("Tomato", 85, 20, now_str),
            ("Cheese", 0, 20, now_str),
            ("Sour Cream", 0, 20, now_str),
            ("Peri Peri", 12, 20, now_str),
        ]
        cursor.executemany("INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at) VALUES (?, ?, ?, ?);", initial_inventory)
        
        # Initial movements
        cursor.executemany("""
        INSERT INTO inventory_movements (timestamp, flavour, movement_type, quantity, reference, created_by)
        VALUES (?, ?, ?, ?, ?, ?);
        """, [
            (now_str, "Tomato", "Stock Added", 100, "Initial Stocking", "Ashish"),
            (now_str, "Cheese", "Stock Added", 50, "Initial Stocking", "Ashish"),
            (now_str, "Sour Cream", "Stock Added", 40, "Initial Stocking", "Ashish"),
            (now_str, "Peri Peri", "Stock Added", 60, "Initial Stocking", "Ashish"),
        ])
        conn.commit()

    # Check orders seed
    cursor.execute("SELECT COUNT(*) FROM orders;")
    if cursor.fetchone()[0] == 0:
        seed_orders = [
            {
                "order_id": "ORD0001",
                "customer_name": "Karthik Raja",
                "phone": "9840123456",
                "address": "42 Anna Salai, T. Nagar",
                "pin_code": "600017",
                "state": "Tamil Nadu",
                "district": "Chennai",
                "total_bottles": 2,
                "total_weight_grams": 220,
                "unit_price": 149.0,
                "product_amount": 298.0,
                "delivery_fee": 40.0,
                "final_amount": 338.0,
                "payment": "Paid",
                "dispatch_state": "DISPATCHED",
                "created_by": "Shriya",
                "created_at": "2026-01-14 10:30:00",
                "edited_by": "Ashish",
                "edited_at": "2026-01-14 14:15:00",
                "items": [("Tomato", 2, 149.0, 298.0)]
            },
            {
                "order_id": "ORD0002",
                "customer_name": "Priya Sundaram",
                "phone": "9841234567",
                "address": "15 Gandhipuram 4th Street",
                "pin_code": "641012",
                "state": "Tamil Nadu",
                "district": "Coimbatore",
                "total_bottles": 3,
                "total_weight_grams": 330,
                "unit_price": 149.0,
                "product_amount": 447.0,
                "delivery_fee": 65.0,
                "final_amount": 512.0,
                "payment": "COD",
                "dispatch_state": "PLACED",
                "created_by": "Suguna",
                "created_at": "2026-02-18 11:20:00",
                "edited_by": "Suguna",
                "edited_at": "2026-02-18 11:20:00",
                "items": [("Tomato", 1, 149.0, 149.0), ("Cheese", 2, 149.0, 298.0)]
            },
            {
                "order_id": "ORD0003",
                "customer_name": "Rahul Sharma",
                "phone": "9819876543",
                "address": "802 Palm Beach Residency, Vashi",
                "pin_code": "400703",
                "state": "Maharashtra",
                "district": "Navi Mumbai",
                "total_bottles": 4,
                "total_weight_grams": 440,
                "unit_price": 149.0,
                "product_amount": 596.0,
                "delivery_fee": 150.0,
                "final_amount": 746.0,
                "payment": "Paid",
                "dispatch_state": "DISPATCHED",
                "created_by": "Vaishnavi",
                "created_at": "2026-03-05 15:45:00",
                "edited_by": "Ashish",
                "edited_at": "2026-03-06 09:10:00",
                "items": [("Tomato", 2, 149.0, 298.0), ("Peri Peri", 2, 149.0, 298.0)]
            },
            {
                "order_id": "ORD0023",
                "customer_name": "Ananya Krishnan",
                "phone": "9790554433",
                "address": "28 Besant Nagar Beach Road",
                "pin_code": "600090",
                "state": "Tamil Nadu",
                "district": "Chennai",
                "total_bottles": 2,
                "total_weight_grams": 220,
                "unit_price": 149.0,
                "product_amount": 298.0,
                "delivery_fee": 40.0,
                "final_amount": 338.0,
                "payment": "COD",
                "dispatch_state": "PLACED",
                "created_by": "Harini",
                "created_at": "2026-09-20 16:10:00",
                "edited_by": "Harini",
                "edited_at": "2026-09-20 16:10:00",
                "items": [("Tomato", 1, 149.0, 149.0), ("Peri Peri", 1, 149.0, 149.0)]
            },
            {
                "order_id": "ORD0042",
                "customer_name": "Deepak Menon",
                "phone": "9447123987",
                "address": "12 Marine Drive Apartments",
                "pin_code": "682031",
                "state": "Kerala",
                "district": "Ernakulam",
                "total_bottles": 3,
                "total_weight_grams": 330,
                "unit_price": 149.0,
                "product_amount": 447.0,
                "delivery_fee": 78.0,
                "final_amount": 525.0,
                "payment": "Paid",
                "dispatch_state": "DISPATCHED",
                "created_by": "Shriya",
                "created_at": "2026-09-26 12:00:00",
                "edited_by": "Ashish",
                "edited_at": "2026-09-26 14:30:00",
                "items": [("Tomato", 2, 149.0, 298.0), ("Peri Peri", 1, 149.0, 149.0)]
            }
        ]

        for o in seed_orders:
            cursor.execute("""
            INSERT INTO orders (
                order_id, customer_name, phone, address, pin_code, state, district,
                total_bottles, total_weight_grams, unit_price, product_amount,
                delivery_fee, final_amount, payment, dispatch_state,
                created_by, created_at, edited_by, edited_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                o["order_id"], o["customer_name"], o["phone"], o["address"], o["pin_code"],
                o["state"], o["district"], o["total_bottles"], o["total_weight_grams"],
                o["unit_price"], o["product_amount"], o["delivery_fee"], o["final_amount"],
                o["payment"], o["dispatch_state"], o["created_by"], o["created_at"],
                o["edited_by"], o["edited_at"]
            ))

            for item in o["items"]:
                cursor.execute("""
                INSERT INTO order_items (order_id, flavour, quantity, unit_price, line_amount)
                VALUES (?, ?, ?, ?, ?);
                """, (o["order_id"], item[0], item[1], item[2], item[3]))
                
                # record sold movement
                cursor.execute("""
                INSERT INTO inventory_movements (timestamp, flavour, movement_type, quantity, reference, created_by)
                VALUES (?, ?, ?, ?, ?, ?);
                """, (o["created_at"], item[0], "Sold", -item[1], o["order_id"], o["created_by"]))

            cursor.execute("""
            INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
            VALUES (?, ?, ?, ?, ?);
            """, (o["created_at"], o["created_by"], "Order Created", o["order_id"], f"Created order with {o['total_bottles']} bottles, final ₹{o['final_amount']}"))

        conn.commit()

    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
