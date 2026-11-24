import unittest
import sqlite3
from unittest.mock import patch
from fastapi.testclient import TestClient

import server
from server import app

class SQLiteConnectionWrapper:
    def __init__(self, raw_conn):
        self._raw = raw_conn
    def cursor(self):
        return self._raw.cursor()
    def commit(self):
        return self._raw.commit()
    def rollback(self):
        return self._raw.rollback()
    def close(self):
        pass

class DeliveryFeesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_db = sqlite3.connect(":memory:", check_same_thread=False)
        cls.raw_db.row_factory = sqlite3.Row

        cursor = cls.raw_db.cursor()
        cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS inventory (
            flavour TEXT PRIMARY KEY,
            current_stock INTEGER NOT NULL,
            low_stock_threshold INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS inventory_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            flavour TEXT NOT NULL,
            movement_type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            reference TEXT NOT NULL,
            created_by TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            alternate_phone TEXT DEFAULT NULL,
            address TEXT NOT NULL,
            pin_code TEXT NOT NULL,
            state TEXT NOT NULL,
            district TEXT NOT NULL,
            total_bottles INTEGER NOT NULL,
            total_weight_grams INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            product_amount REAL NOT NULL,
            delivery_fee REAL NOT NULL,
            actual_delivery_fee REAL DEFAULT NULL,
            final_amount REAL NOT NULL,
            payment TEXT NOT NULL,
            dispatch_state TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            edited_by TEXT NOT NULL,
            edited_at TEXT NOT NULL,
            discount_per_bottle REAL NOT NULL DEFAULT 0.0,
            total_discount REAL NOT NULL DEFAULT 0.0,
            normal_product_amount REAL NOT NULL DEFAULT 0.0,
            is_combo INTEGER NOT NULL DEFAULT 0,
            combo_type TEXT NOT NULL DEFAULT '',
            combo_price REAL NOT NULL DEFAULT 0.0,
            notes TEXT DEFAULT '',
            order_source TEXT DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            flavour TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            line_amount REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_id TEXT,
            details TEXT
        );

        INSERT INTO settings (key, value, updated_at) VALUES ('bottle_price', '160', '2026-10-20 00:00:00');
        INSERT INTO settings (key, value, updated_at) VALUES ('discount_per_bottle', '11', '2026-10-20 00:00:00');
        INSERT INTO settings (key, value, updated_at) VALUES ('low_stock_threshold', '10', '2026-10-20 00:00:00');

        INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at) VALUES ('Cheese', 100, 10, '2026-10-20 00:00:00');
        INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at) VALUES ('Tomato', 100, 10, '2026-10-20 00:00:00');
        """)
        cls.raw_db.commit()

        cls.db_patcher = patch("server.get_db", side_effect=lambda: SQLiteConnectionWrapper(cls.raw_db))
        cls.db_patcher.start()

        app.dependency_overrides[server.get_current_user] = lambda: {
            "id": 1,
            "username": "ashish",
            "display_name": "Ashish (Admin)",
            "role": "ADMIN"
        }
        app.dependency_overrides[server.require_admin] = lambda: {
            "id": 1,
            "username": "ashish",
            "display_name": "Ashish (Admin)",
            "role": "ADMIN"
        }

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.db_patcher.stop()
        app.dependency_overrides.clear()
        cls.raw_db.close()

    def test_01_create_order_auto_delivery_fee(self):
        # 1 bottle in Tamil Nadu, Chennai -> table delivery fee is 40.0
        payload = {
            "customer_name": "Ravi Kumar",
            "phone": "9876543210",
            "address": "12 Gandhi Road",
            "pin_code": "600001",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "delivery_fee": 40.0,
            "items": [{"flavour": "Cheese", "quantity": 1}]
        }
        res = self.client.post("/api/orders", json=payload)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        order_id = data["order_id"]

        # Check DB
        cursor = self.raw_db.cursor()
        cursor.execute("SELECT delivery_fee, actual_delivery_fee, final_amount FROM orders WHERE order_id = ?;", (order_id,))
        row = cursor.fetchone()
        self.assertEqual(row["delivery_fee"], 40.0)
        self.assertEqual(row["actual_delivery_fee"], 40.0)
        self.assertEqual(row["final_amount"], 149.0 + 40.0)

        # Check get_order_details endpoint
        detail_res = self.client.get(f"/api/orders/{order_id}")
        self.assertEqual(detail_res.status_code, 200)
        order_data = detail_res.json()["order"]
        self.assertEqual(order_data["actual_delivery_fee"], 40.0)
        self.assertEqual(order_data["delivery_fee"], 40.0)

    def test_02_create_order_manual_override(self):
        # 1 bottle in Tamil Nadu, Ranipet -> table fee is 65.0, but user sets manual override 40.0 (like in user screenshot)
        payload = {
            "customer_name": "Suresh Raina",
            "phone": "9876543211",
            "address": "15 Anna Salai",
            "pin_code": "631002",
            "state": "Tamil Nadu",
            "district": "Ranipet",
            "payment": "COD",
            "delivery_fee": 40.0,
            "items": [{"flavour": "Cheese", "quantity": 1}]
        }
        res = self.client.post("/api/orders", json=payload)
        self.assertEqual(res.status_code, 200, res.text)
        order_id = res.json()["order_id"]

        # Check DB
        cursor = self.raw_db.cursor()
        cursor.execute("SELECT delivery_fee, actual_delivery_fee, final_amount FROM orders WHERE order_id = ?;", (order_id,))
        row = cursor.fetchone()
        self.assertEqual(row["delivery_fee"], 40.0)  # Collected fee (user manual override)
        self.assertEqual(row["actual_delivery_fee"], 65.0)  # Actual table fee
        self.assertEqual(row["final_amount"], 149.0 + 40.0)  # Financial total uses collected fee

        detail_res = self.client.get(f"/api/orders/{order_id}")
        order_data = detail_res.json()["order"]
        self.assertEqual(order_data["actual_delivery_fee"], 65.0)
        self.assertEqual(order_data["delivery_fee"], 40.0)

    def test_03_edit_order_preserves_actual_and_collected(self):
        # Create an order in Chennai with table fee 40.0
        payload = {
            "customer_name": "Vikram Patel",
            "phone": "9876543212",
            "address": "20 Main St",
            "pin_code": "600001",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "delivery_fee": 40.0,
            "items": [{"flavour": "Cheese", "quantity": 1}]
        }
        res = self.client.post("/api/orders", json=payload)
        order_id = res.json()["order_id"]

        # Edit order: change manual fee to 55.0 while keeping location
        edit_payload = {
            "customer_name": "Vikram Patel",
            "phone": "9876543212",
            "address": "20 Main St",
            "pin_code": "600001",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "delivery_fee": 55.0,
            "items": [{"flavour": "Cheese", "quantity": 1}]
        }
        edit_res = self.client.put(f"/api/orders/{order_id}", json=edit_payload)
        self.assertEqual(edit_res.status_code, 200)

        # Check DB
        cursor = self.raw_db.cursor()
        cursor.execute("SELECT delivery_fee, actual_delivery_fee, final_amount FROM orders WHERE order_id = ?;", (order_id,))
        row = cursor.fetchone()
        self.assertEqual(row["delivery_fee"], 55.0)
        self.assertEqual(row["actual_delivery_fee"], 40.0)
        self.assertEqual(row["final_amount"], 149.0 + 55.0)

    def test_04_historical_order_with_null_actual_delivery_fee(self):
        # Insert a simulated historical order with NULL actual_delivery_fee
        cursor = self.raw_db.cursor()
        cursor.execute("""
        INSERT INTO orders (
            order_id, customer_name, phone, address, pin_code, state, district,
            total_bottles, total_weight_grams, unit_price, product_amount,
            delivery_fee, actual_delivery_fee, final_amount, payment, dispatch_state,
            created_by, created_at, edited_by, edited_at,
            discount_per_bottle, total_discount, normal_product_amount,
            is_combo, combo_type, combo_price
        ) VALUES (
            'ORD9999', 'Old Customer', '9123456780', 'Old Address', '600001', 'Tamil Nadu', 'Chennai',
            1, 100, 160.0, 149.0,
            40.0, NULL, 189.0, 'Paid', 'PLACED',
            'Ashish', '2026-10-01 10:00:00', 'Ashish', '2026-10-01 10:00:00',
            11.0, 11.0, 149.0,
            0, '', 0.0
        );
        """)
        self.raw_db.commit()

        detail_res = self.client.get("/api/orders/ORD9999")
        self.assertEqual(detail_res.status_code, 200)
        order_data = detail_res.json()["order"]
        self.assertIsNone(order_data["actual_delivery_fee"])
        self.assertEqual(order_data["delivery_fee"], 40.0)
