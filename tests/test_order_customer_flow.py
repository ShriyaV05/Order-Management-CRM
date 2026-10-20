import unittest
import os
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
        pass  # Keep in-memory DB active for test assertions

class OrderCustomerFlowTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create an in-memory SQLite database matching POPCONE schema
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
            combo_price REAL NOT NULL DEFAULT 0.0
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
            details TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_orders_phone ON orders(phone);

        INSERT INTO settings (key, value, updated_at) VALUES ('bottle_price', '160', '2026-10-20 00:00:00');
        INSERT INTO settings (key, value, updated_at) VALUES ('discount_per_bottle', '11', '2026-10-20 00:00:00');
        INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at) VALUES ('Tomato', 100, 10, '2026-10-20 00:00:00');
        INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at) VALUES ('Cheese', 100, 10, '2026-10-20 00:00:00');
        INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at) VALUES ('Peri Peri', 100, 10, '2026-10-20 00:00:00');
        """)
        cls.raw_db.commit()

        # Patch get_db in server module
        cls.db_patcher = patch("server.get_db", side_effect=lambda: SQLiteConnectionWrapper(cls.raw_db))
        cls.db_patcher.start()

        # Mock authentication as admin
        app.dependency_overrides[server.get_current_user] = lambda: {
            "id": 1,
            "username": "ashish@popcone",
            "display_name": "Ashish",
            "role": "ADMIN"
        }

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.db_patcher.stop()
        app.dependency_overrides.clear()
        cls.raw_db.close()

    def test_01_check_phone_non_existent(self):
        """When phone is new, check-phone returns exists: False."""
        res = self.client.get("/api/orders/check-phone?phone=9876543210")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data.get("exists"))

    def test_02_new_customer_order_creation(self):
        """New phone number creates a customer and order normally."""
        payload = {
            "customer_name": "Ramesh Kumar",
            "phone": "9876543210",
            "address": "12 Anna Salai, T Nagar",
            "pin_code": "600017",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "delivery_fee": 0.0,
            "apply_combo": False,
            "items": [
                {"flavour": "Tomato", "quantity": 2}
            ]
        }
        res = self.client.post("/api/orders", json=payload)
        self.assertEqual(res.status_code, 200, f"Create order failed: {res.text}")
        order = res.json()
        self.assertTrue(order["order_id"].startswith("ORD"))
        OrderCustomerFlowTestCase.first_order_id = order["order_id"]

    def test_03_existing_customer_details_lookup(self):
        """Existing phone number lookup returns order ID, customer details, and alert message."""
        res = self.client.get("/api/orders/check-phone?phone=9876543210")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("exists"))
        self.assertEqual(data.get("order_id"), OrderCustomerFlowTestCase.first_order_id)
        self.assertEqual(data.get("customer_name"), "Ramesh Kumar")
        self.assertEqual(data.get("address"), "12 Anna Salai, T Nagar")
        self.assertEqual(data.get("pin_code"), "600017")
        self.assertEqual(data.get("state"), "Tamil Nadu")
        self.assertEqual(data.get("district"), "Chennai")
        self.assertIn("associated with Order", data.get("message", ""))

    def test_04_repeat_order_with_same_phone_succeeds(self):
        """Existing customer placing a 2nd order with the same phone number succeeds and does NOT block."""
        payload_2 = {
            "customer_name": "Ramesh Kumar",
            "phone": "9876543210",  # Same phone number!
            "address": "12 Anna Salai, T Nagar (Flat 4B)",
            "pin_code": "600017",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "COD",
            "delivery_fee": 30.0,
            "apply_combo": False,
            "items": [
                {"flavour": "Cheese", "quantity": 1},
                {"flavour": "Peri Peri", "quantity": 1}
            ]
        }
        res = self.client.post("/api/orders", json=payload_2)
        self.assertEqual(res.status_code, 200, f"Repeat order was blocked: {res.text}")
        order_2 = res.json()
        self.assertTrue(order_2["order_id"].startswith("ORD"))
        self.assertNotEqual(order_2["order_id"], OrderCustomerFlowTestCase.first_order_id, "Each order must receive a unique order_id")

        # Verify database contains both distinct orders with unique order IDs
        cursor = self.raw_db.cursor()
        cursor.execute("SELECT order_id, phone, customer_name FROM orders WHERE phone = '9876543210' ORDER BY id ASC;")
        rows = cursor.fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["order_id"], OrderCustomerFlowTestCase.first_order_id)
        self.assertEqual(rows[1]["order_id"], order_2["order_id"])

    def test_05_edit_order_with_same_phone(self):
        """Editing an order preserves or updates details without phone uniqueness conflict."""
        update_payload = {
            "customer_name": "Ramesh K. (Updated)",
            "phone": "9876543210",
            "address": "12 Anna Salai, T Nagar (Flat 4B)",
            "pin_code": "600017",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "COD",
            "dispatch_state": "PLACED",
            "delivery_fee": 30.0,
            "items": [
                {"flavour": "Cheese", "quantity": 2}
            ]
        }
        res = self.client.put(f"/api/orders/{OrderCustomerFlowTestCase.first_order_id}", json=update_payload)
        self.assertEqual(res.status_code, 200, f"Edit order failed: {res.text}")
        updated = res.json()
        self.assertTrue(updated["success"])

        # Verify database record updated
        cursor = self.raw_db.cursor()
        cursor.execute("SELECT customer_name, phone FROM orders WHERE order_id = ?;", (OrderCustomerFlowTestCase.first_order_id,))
        row = cursor.fetchone()
        self.assertEqual(row["customer_name"], "Ramesh K. (Updated)")
        self.assertEqual(row["phone"], "9876543210")

    def test_06_manual_delivery_fee_creation_and_editing(self):
        """Manual delivery fee is properly considered and added to the total amount both with and without combo offers."""
        # 1. Normal pricing (2 bottles: 298.0) + manual delivery fee 55.0 => Final = 353.0
        payload_normal = {
            "customer_name": "Sanjay Testing",
            "phone": "9123456789",
            "address": "45 Lake View Road",
            "pin_code": "600028",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "delivery_fee": 55.0,
            "apply_combo": False,
            "items": [
                {"flavour": "Tomato", "quantity": 1},
                {"flavour": "Cheese", "quantity": 1}
            ]
        }
        res = self.client.post("/api/orders", json=payload_normal)
        self.assertEqual(res.status_code, 200, f"Order creation failed: {res.text}")
        normal_order = res.json()
        oid_normal = normal_order["order_id"]
        self.assertEqual(normal_order["delivery_fee"], 55.0)
        self.assertEqual(normal_order["final_amount"], 353.0)

        # 2. Combo pricing (2 bottles: 289.0) + manual delivery fee 55.0 => Final = 344.0
        payload_combo = {
            "customer_name": "Priya Testing",
            "phone": "9234567890",
            "address": "88 Beach Road",
            "pin_code": "600041",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "delivery_fee": 55.0,
            "apply_combo": True,
            "combo_type": "2_BOTTLE",
            "items": [
                {"flavour": "Sour Cream", "quantity": 1},
                {"flavour": "Peri Peri", "quantity": 1}
            ]
        }
        res2 = self.client.post("/api/orders", json=payload_combo)
        self.assertEqual(res2.status_code, 200, f"Combo order creation failed: {res2.text}")
        combo_order = res2.json()
        self.assertEqual(combo_order["delivery_fee"], 55.0)
        self.assertEqual(combo_order["final_amount"], 344.0)

        # 3. Edit normal order to update manual delivery fee from 55.0 to 45.0 => Final = 343.0
        edit_payload = {
            "customer_name": "Sanjay Testing",
            "phone": "9123456789",
            "address": "45 Lake View Road",
            "pin_code": "600028",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "delivery_fee": 45.0,
            "apply_combo": False,
            "items": [
                {"flavour": "Tomato", "quantity": 1},
                {"flavour": "Cheese", "quantity": 1}
            ]
        }
        res3 = self.client.put(f"/api/orders/{oid_normal}", json=edit_payload)
        self.assertEqual(res3.status_code, 200, f"Edit order failed: {res3.text}")

        # Verify details endpoint returns updated delivery fee and final amount
        res4 = self.client.get(f"/api/orders/{oid_normal}")
        self.assertEqual(res4.status_code, 200)
        details = res4.json()["order"]
        self.assertEqual(details["delivery_fee"], 45.0)
        self.assertEqual(details["product_amount"], 298.0)
        self.assertEqual(details["final_amount"], 343.0)

