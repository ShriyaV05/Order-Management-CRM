import unittest
import sqlite3
from typing import Dict, Any
from fastapi.testclient import TestClient

import server
from database import _add_column_if_missing

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

class OrderSourceTestCase(unittest.TestCase):
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
            reference TEXT,
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

        INSERT INTO settings (key, value, updated_at) VALUES ('bottle_price', '160', '2026-11-23 00:00:00');
        INSERT INTO settings (key, value, updated_at) VALUES ('discount_per_bottle', '11', '2026-11-23 00:00:00');

        INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at)
        VALUES ('Tomato', 500, 20, '2026-11-23 00:00:00');
        INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at)
        VALUES ('Cheese', 500, 20, '2026-11-23 00:00:00');
        INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at)
        VALUES ('Sour Cream', 500, 20, '2026-11-23 00:00:00');
        INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at)
        VALUES ('Peri Peri', 500, 20, '2026-11-23 00:00:00');

        -- Seed 1 Historical Order with NULL order_source (ORD9001)
        INSERT INTO orders (
            order_id, customer_name, phone, address, pin_code, state, district,
            total_bottles, total_weight_grams, unit_price, product_amount, delivery_fee,
            actual_delivery_fee, final_amount, payment, dispatch_state,
            created_by, created_at, edited_by, edited_at,
            discount_per_bottle, total_discount, normal_product_amount,
            is_combo, combo_type, combo_price, notes, order_source
        ) VALUES (
            'ORD9001', 'Historical Customer', '9876543210', '123 Old Street', '600001',
            'Tamil Nadu', 'Chennai', 2, 200, 160.0, 289.0, 50.0,
            50.0, 339.0, 'Paid', 'PLACED',
            'Admin', '2026-11-01 10:00:00', 'Admin', '2026-11-01 10:00:00',
            11.0, 22.0, 298.0, 1, '2_BOTTLES', 289.0, 'Historical notes', NULL
        );

        INSERT INTO order_items (order_id, flavour, quantity, unit_price, line_amount)
        VALUES ('ORD9001', 'Tomato', 2, 160.0, 289.0);
        """)
        cls.raw_db.commit()

        # Patch get_db to use our in-memory connection
        server.get_db = lambda: MockTursoConnection(cls.raw_db)

        # Mock authentication dependency
        server.app.dependency_overrides[server.get_current_user] = lambda: {
            "id": 1,
            "username": "tester@popcone",
            "display_name": "Test Runner",
            "role": "ADMIN"
        }

        cls.client = TestClient(server.app)

    def test_01_in_memory_migration_simulation(self):
        """Simulate applying _add_column_if_missing on an orders table initially lacking order_source."""
        test_db = sqlite3.connect(":memory:")
        test_db.row_factory = sqlite3.Row
        cur = test_db.cursor()
        cur.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, order_id TEXT, customer_name TEXT);")
        cur.execute("INSERT INTO orders (order_id, customer_name) VALUES ('TEST01', 'Alice');")
        test_db.commit()

        # Check before migration
        cur.execute("PRAGMA table_info(orders);")
        cols_before = [r["name"] for r in cur.fetchall()]
        self.assertNotIn("order_source", cols_before)

        # Run additive migration
        _add_column_if_missing(cur, "orders", "order_source", "order_source TEXT DEFAULT NULL")
        test_db.commit()

        # Check after migration
        cur.execute("PRAGMA table_info(orders);")
        cols_after = [r["name"] for r in cur.fetchall()]
        self.assertIn("order_source", cols_after)

        # Verify historical row retained NULL
        cur.execute("SELECT order_id, customer_name, order_source FROM orders WHERE order_id = 'TEST01';")
        row = cur.fetchone()
        self.assertIsNone(row["order_source"])

        # Verify idempotency (calling second time does not error or duplicate)
        _add_column_if_missing(cur, "orders", "order_source", "order_source TEXT DEFAULT NULL")
        test_db.commit()
        test_db.close()

    def test_02_create_order_default_assisted(self):
        """Creating an order without explicit order_source defaults to Assisted."""
        payload = {
            "customer_name": "Assisted Customer",
            "phone": "9123456780",
            "address": "456 Market Road",
            "pin_code": "600002",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "items": [{"flavour": "Tomato", "quantity": 1}]
        }
        res = self.client.post("/api/orders", json=payload)
        self.assertEqual(res.status_code, 200, res.text)
        created = res.json()
        oid = created["order_id"]

        # Check database row directly
        cur = self.raw_db.cursor()
        cur.execute("SELECT order_source FROM orders WHERE order_id = ?;", (oid,))
        row = cur.fetchone()
        self.assertEqual(row["order_source"], "Assisted")

        # Check GET /api/orders/{order_id}
        det = self.client.get(f"/api/orders/{oid}").json()
        self.assertEqual(det["order"]["order_source"], "Assisted")

    def test_03_create_order_explicit_website(self):
        """Creating an order with order_source='Website' saves properly."""
        payload = {
            "customer_name": "Website Customer",
            "phone": "9123456781",
            "address": "789 Online Ave",
            "pin_code": "600003",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "items": [{"flavour": "Cheese", "quantity": 1}],
            "order_source": "Website"
        }
        res = self.client.post("/api/orders", json=payload)
        self.assertEqual(res.status_code, 200, res.text)
        created = res.json()
        oid = created["order_id"]

        # Check database row directly
        cur = self.raw_db.cursor()
        cur.execute("SELECT order_source FROM orders WHERE order_id = ?;", (oid,))
        row = cur.fetchone()
        self.assertEqual(row["order_source"], "Website")

        # Check GET /api/orders/{order_id}
        det = self.client.get(f"/api/orders/{oid}").json()
        self.assertEqual(det["order"]["order_source"], "Website")

    def test_04_create_order_invalid_source_rejected(self):
        """Creating an order with an invalid order_source is rejected with 400 Bad Request."""
        payload = {
            "customer_name": "Bad Source Customer",
            "phone": "9123456782",
            "address": "123 Error Lane",
            "pin_code": "600004",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "items": [{"flavour": "Tomato", "quantity": 1}],
            "order_source": "Retail"
        }
        res = self.client.post("/api/orders", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Order Source must be either 'Assisted' or 'Website'", res.json()["detail"])

    def test_05_historical_order_returns_null(self):
        """Historical orders with NULL order_source return None (Not Specified) and don't infer Assisted."""
        det = self.client.get("/api/orders/ORD9001").json()
        self.assertIsNone(det["order"]["order_source"])

        # Also check list endpoint
        list_res = self.client.get("/api/orders?search=ORD9001").json()
        orders = list_res.get("orders", [])
        target = [o for o in orders if o["order_id"] == "ORD9001"]
        self.assertTrue(len(target) > 0)
        self.assertIsNone(target[0]["order_source"])

    def test_06_edit_order_transitions(self):
        """Verify editing order_source between Assisted and Website preserves all other fields."""
        # 1. Create order as Assisted
        res = self.client.post("/api/orders", json={
            "customer_name": "Edit Test Customer",
            "phone": "9123456783",
            "address": "42 Transition Blvd",
            "pin_code": "600005",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "COD",
            "items": [{"flavour": "Sour Cream", "quantity": 1}],
            "order_source": "Assisted"
        })
        self.assertEqual(res.status_code, 200)
        oid = res.json()["order_id"]

        # Fetch original details
        orig = self.client.get(f"/api/orders/{oid}").json()["order"]
        self.assertEqual(orig["order_source"], "Assisted")
        orig_amount = orig["final_amount"]
        orig_bottles = orig["total_bottles"]

        # 2. Edit Assisted -> Website
        edit_payload_1 = {
            "customer_name": orig["customer"],
            "phone": orig["phone"],
            "address": orig["address"],
            "pin_code": orig["pin_code"],
            "state": orig["state"],
            "district": orig["district"],
            "payment": orig["payment"],
            "delivery_fee": orig["delivery_fee"],
            "items": [{"flavour": "Sour Cream", "quantity": 1}],
            "order_source": "Website"
        }
        edit_res_1 = self.client.put(f"/api/orders/{oid}", json=edit_payload_1)
        self.assertEqual(edit_res_1.status_code, 200)

        # Check updated
        updated_1 = self.client.get(f"/api/orders/{oid}").json()["order"]
        self.assertEqual(updated_1["order_source"], "Website")
        self.assertEqual(updated_1["final_amount"], orig_amount, "Pricing must not change when changing order source")
        self.assertEqual(updated_1["total_bottles"], orig_bottles, "Quantities must not change")

        # 3. Edit Website -> Assisted
        edit_payload_2 = {
            "customer_name": orig["customer"],
            "phone": orig["phone"],
            "address": orig["address"],
            "pin_code": orig["pin_code"],
            "state": orig["state"],
            "district": orig["district"],
            "payment": orig["payment"],
            "delivery_fee": orig["delivery_fee"],
            "items": [{"flavour": "Sour Cream", "quantity": 1}],
            "order_source": "Assisted"
        }
        edit_res_2 = self.client.put(f"/api/orders/{oid}", json=edit_payload_2)
        self.assertEqual(edit_res_2.status_code, 200)

        updated_2 = self.client.get(f"/api/orders/{oid}").json()["order"]
        self.assertEqual(updated_2["order_source"], "Assisted")
        self.assertEqual(updated_2["final_amount"], orig_amount)

        # 4. Edit with invalid source -> rejected
        edit_payload_bad = dict(edit_payload_2)
        edit_payload_bad["order_source"] = "Store"
        bad_res = self.client.put(f"/api/orders/{oid}", json=edit_payload_bad)
        self.assertEqual(bad_res.status_code, 400)

    def test_07_edit_historical_order_without_source_preserves_null(self):
        """Editing an order while leaving order_source=None preserves NULL."""
        edit_payload = {
            "customer_name": "Historical Customer Updated",
            "phone": "9876543210",
            "address": "123 Old Street",
            "pin_code": "600001",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "payment": "Paid",
            "delivery_fee": 50.0,
            "apply_combo": True,
            "combo_type": "2_BOTTLES",
            "items": [{"flavour": "Tomato", "quantity": 2}],
            "notes": "Updated historical notes",
            "order_source": None
        }
        res = self.client.put("/api/orders/ORD9001", json=edit_payload)
        self.assertEqual(res.status_code, 200, res.text)

        det = self.client.get("/api/orders/ORD9001").json()["order"]
        self.assertIsNone(det["order_source"])
        self.assertEqual(det["customer"], "Historical Customer Updated")
        self.assertEqual(det["notes"], "Updated historical notes")

if __name__ == "__main__":
    unittest.main()
