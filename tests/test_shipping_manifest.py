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

class ShippingManifestTestCase(unittest.TestCase):
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

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            alternate_phone TEXT DEFAULT NULL,
            address TEXT NOT NULL,
            pin_code TEXT NOT NULL,
            district TEXT NOT NULL,
            state TEXT NOT NULL,
            total_bottles INTEGER NOT NULL,
            total_weight_grams INTEGER NOT NULL,
            product_amount REAL NOT NULL,
            delivery_fee REAL NOT NULL,
            actual_delivery_fee REAL DEFAULT NULL,
            final_amount REAL NOT NULL,
            payment TEXT NOT NULL,
            dispatch_state TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            edited_by TEXT,
            edited_at TEXT,
            discount_per_bottle REAL DEFAULT 0.0,
            total_discount REAL DEFAULT 0.0,
            normal_product_amount REAL DEFAULT 0.0,
            is_combo INTEGER DEFAULT 0,
            combo_type TEXT DEFAULT '',
            combo_price REAL DEFAULT 0.0,
            notes TEXT DEFAULT '',
            order_source TEXT DEFAULT NULL
        );

        -- Insert historical order (actual_delivery_fee is NULL)
        INSERT INTO orders (
            order_id, customer_name, phone, address, pin_code, district, state,
            total_bottles, total_weight_grams, product_amount, delivery_fee, actual_delivery_fee,
            final_amount, payment, dispatch_state, created_by, created_at
        ) VALUES (
            'ORD0001', 'Rahul Sharma', '9876543210', '123 Main St, Indiranagar', '560038', 'Bangalore Urban', 'Karnataka',
            2, 200, 298.0, 40.0, NULL,
            338.0, 'Paid', 'DISPATCHED', 'admin', '2026-11-10 10:00:00'
        );

        -- Insert order with custom collected delivery fee
        INSERT INTO orders (
            order_id, customer_name, phone, address, pin_code, district, state,
            total_bottles, total_weight_grams, product_amount, delivery_fee, actual_delivery_fee,
            final_amount, payment, dispatch_state, created_by, created_at
        ) VALUES (
            'ORD0002', 'Priya Patel', '9123456780', '456 Ring Rd, Vastrapur', '380015', 'Ahmedabad', 'Gujarat',
            4, 400, 596.0, 75.0, 60.0,
            671.0, 'COD', 'PLACED', 'admin', '2026-11-12 14:30:00'
        );

        -- Insert order with free delivery (0 fee)
        INSERT INTO orders (
            order_id, customer_name, phone, address, pin_code, district, state,
            total_bottles, total_weight_grams, product_amount, delivery_fee, actual_delivery_fee,
            final_amount, payment, dispatch_state, created_by, created_at
        ) VALUES (
            'ORD0003', 'Rahul Sharma', '9876543210', '123 Main St, Indiranagar', '560038', 'Bangalore Urban', 'Karnataka',
            10, 1000, 1490.0, 0.0, 0.0,
            1490.0, 'Paid', 'PLACED', 'admin', '2026-11-15 09:15:00'
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            flavour TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            line_amount REAL NOT NULL
        );

        INSERT INTO order_items (order_id, flavour, quantity, unit_price, line_amount) VALUES
        ('ORD0001', 'Tomato', 1, 149.0, 149.0),
        ('ORD0001', 'Cheese', 1, 149.0, 149.0),
        ('ORD0002', 'Tomato', 1, 149.0, 149.0),
        ('ORD0002', 'Cheese', 1, 149.0, 149.0),
        ('ORD0002', 'Sour Cream', 1, 149.0, 149.0),
        ('ORD0002', 'Peri Peri', 1, 149.0, 149.0),
        ('ORD0003', 'Tomato', 4, 149.0, 596.0),
        ('ORD0003', 'Cheese', 3, 149.0, 447.0),
        ('ORD0003', 'Sour Cream', 2, 149.0, 298.0),
        ('ORD0003', 'Peri Peri', 1, 149.0, 149.0);
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

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.db_patcher.stop()
        app.dependency_overrides.clear()

    def test_shipping_manifest_endpoint_returns_all_orders(self):
        """Verify endpoint returns all orders with total_count matching record count."""
        response = self.client.get("/api/orders/shipping-manifest")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("manifest", data)
        self.assertIn("total_count", data)
        self.assertEqual(data["total_count"], 3)
        self.assertEqual(len(data["manifest"]), 3)

    def test_shipping_manifest_has_all_11_required_fields(self):
        """Verify each manifest entry contains all 11 required fields."""
        response = self.client.get("/api/orders/shipping-manifest")
        self.assertEqual(response.status_code, 200)
        manifest = response.json()["manifest"]

        required_keys = [
            "order_id", "name", "date", "phone", "address",
            "pin_code", "district", "state", "weight",
            "actual_delivery_fee", "collected_delivery_fee"
        ]

        for item in manifest:
            for k in required_keys:
                self.assertIn(k, item, f"Key '{k}' missing from manifest item")

    def test_historical_order_preserves_null_actual_delivery_fee(self):
        """Verify historical order with NULL actual_delivery_fee is returned as None (not invented)."""
        response = self.client.get("/api/orders/shipping-manifest")
        self.assertEqual(response.status_code, 200)
        manifest = response.json()["manifest"]

        ord1 = next(item for item in manifest if item["order_id"] == "ORD0001")
        self.assertIsNone(ord1["actual_delivery_fee"])
        self.assertEqual(ord1["collected_delivery_fee"], 40.0)
        self.assertEqual(ord1["name"], "Rahul Sharma")
        self.assertEqual(ord1["weight"], "200g")

    def test_separate_actual_and_collected_fees(self):
        """Verify distinct values for actual (60.0) and collected (75.0) delivery fee."""
        response = self.client.get("/api/orders/shipping-manifest")
        self.assertEqual(response.status_code, 200)
        manifest = response.json()["manifest"]

        ord2 = next(item for item in manifest if item["order_id"] == "ORD0002")
        self.assertEqual(ord2["actual_delivery_fee"], 60.0)
        self.assertEqual(ord2["collected_delivery_fee"], 75.0)
        self.assertEqual(ord2["weight"], "400g")

    def test_weight_formatting(self):
        """Verify weight is properly formatted with units."""
        response = self.client.get("/api/orders/shipping-manifest")
        self.assertEqual(response.status_code, 200)
        manifest = response.json()["manifest"]

        ord3 = next(item for item in manifest if item["order_id"] == "ORD0003")
        self.assertEqual(ord3["weight"], "1kg")
        self.assertEqual(ord3["actual_delivery_fee"], 0.0)
        self.assertEqual(ord3["collected_delivery_fee"], 0.0)

    def test_multiple_orders_for_same_customer(self):
        """Verify customers with multiple orders have separate rows for each order."""
        response = self.client.get("/api/orders/shipping-manifest")
        self.assertEqual(response.status_code, 200)
        manifest = response.json()["manifest"]

        rahul_orders = [item for item in manifest if item["name"] == "Rahul Sharma"]
        self.assertEqual(len(rahul_orders), 2)
        order_ids = {item["order_id"] for item in rahul_orders}
        self.assertEqual(order_ids, {"ORD0001", "ORD0003"})

    def test_shipping_manifest_includes_total_bottles_and_flavour_items(self):
        """Verify manifest items contain total_bottles and items list."""
        response = self.client.get("/api/orders/shipping-manifest")
        self.assertEqual(response.status_code, 200)
        manifest = response.json()["manifest"]

        ord1 = next(item for item in manifest if item["order_id"] == "ORD0001")
        self.assertEqual(ord1["total_bottles"], 2)
        self.assertEqual(len(ord1["items"]), 2)

        ord2 = next(item for item in manifest if item["order_id"] == "ORD0002")
        self.assertEqual(ord2["total_bottles"], 4)
        self.assertEqual(len(ord2["items"]), 4)

        ord3 = next(item for item in manifest if item["order_id"] == "ORD0003")
        self.assertEqual(ord3["total_bottles"], 10)
        self.assertEqual(len(ord3["items"]), 4)

if __name__ == "__main__":
    unittest.main()
