import unittest
import sqlite3
from fastapi.testclient import TestClient

import server

class MockTursoConnection:
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

class OrderNotesTestCase(unittest.TestCase):
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

        INSERT INTO settings (key, value, updated_at) VALUES ('bottle_price', '160', '2026-01-01');
        INSERT INTO settings (key, value, updated_at) VALUES ('discount_per_bottle', '11', '2026-01-01');

        INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at)
        VALUES ('Cheese', 500, 20, '2026-01-01'),
               ('Tomato', 500, 20, '2026-01-01'),
               ('Sour Cream', 500, 20, '2026-01-01'),
               ('Peri Peri', 500, 20, '2026-01-01');
        """)
        cls.raw_db.commit()

        server.get_db = lambda: MockTursoConnection(cls.raw_db)
        server.app.dependency_overrides[server.get_current_user] = lambda: {
            "id": 1,
            "username": "shriya@popcone",
            "display_name": "Shriya",
            "role": "ADMIN"
        }

        cls.client = TestClient(server.app)

    @classmethod
    def tearDownClass(cls):
        server.app.dependency_overrides.clear()

    def test_01_create_order_without_notes(self):
        payload = {
            "customer_name": "Customer One",
            "phone": "9876543210",
            "address": "12 Main Road",
            "pin_code": "600001",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "delivery_fee": 40.0,
            "items": [{"flavour": "Cheese", "quantity": 1}],
            "notes": ""
        }
        res = self.client.post("/api/orders", json=payload)
        self.assertEqual(res.status_code, 200, res.text)
        oid = res.json()["order_id"]

        detail_res = self.client.get(f"/api/orders/{oid}")
        self.assertEqual(detail_res.status_code, 200)
        order = detail_res.json()["order"]
        self.assertEqual(order.get("notes"), "")

    def test_02_create_order_with_notes(self):
        payload = {
            "customer_name": "Customer Two",
            "phone": "9876543211",
            "address": "15 Second Avenue",
            "pin_code": "600001",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "delivery_fee": 40.0,
            "items": [{"flavour": "Cheese", "quantity": 1}],
            "notes": "Deliver strictly between 2 PM and 5 PM"
        }
        res = self.client.post("/api/orders", json=payload)
        self.assertEqual(res.status_code, 200, res.text)
        oid = res.json()["order_id"]

        detail_res = self.client.get(f"/api/orders/{oid}")
        self.assertEqual(detail_res.status_code, 200)
        order = detail_res.json()["order"]
        self.assertEqual(order.get("notes"), "Deliver strictly between 2 PM and 5 PM")

    def test_03_edit_order_add_and_update_notes(self):
        # Create without notes first
        payload = {
            "customer_name": "Customer Three",
            "phone": "9876543212",
            "address": "20 Third Cross",
            "pin_code": "600001",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "delivery_fee": 40.0,
            "items": [{"flavour": "Cheese", "quantity": 1}],
            "notes": ""
        }
        res = self.client.post("/api/orders", json=payload)
        oid = res.json()["order_id"]

        # Edit order to add notes
        edit_payload = {
            "customer_name": "Customer Three",
            "phone": "9876543212",
            "address": "20 Third Cross",
            "pin_code": "600001",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "delivery_fee": 40.0,
            "items": [{"flavour": "Cheese", "quantity": 1}],
            "notes": "Call security at gate for parcel drop-off"
        }
        edit_res = self.client.put(f"/api/orders/{oid}", json=edit_payload)
        self.assertEqual(edit_res.status_code, 200, edit_res.text)

        # Verify Order Details now has the updated notes
        detail_res = self.client.get(f"/api/orders/{oid}")
        self.assertEqual(detail_res.status_code, 200)
        order = detail_res.json()["order"]
        self.assertEqual(order.get("notes"), "Call security at gate for parcel drop-off")

if __name__ == "__main__":
    unittest.main()
