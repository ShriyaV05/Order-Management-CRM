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
        pass  # Keep in-memory DB active for test assertions

class InventoryAdjustmentTestCase(unittest.TestCase):
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

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_id TEXT,
            details TEXT
        );

        INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at) VALUES ('Tomato', 20, 10, '2026-10-20 00:00:00');
        INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at) VALUES ('Cheese', 5, 10, '2026-10-20 00:00:00');
        """)
        cls.raw_db.commit()

        # Patch get_db in server module
        cls.db_patcher = patch("server.get_db", side_effect=lambda: SQLiteConnectionWrapper(cls.raw_db))
        cls.db_patcher.start()

        # Mock authentication as admin
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

    def test_01_stock_added_increases_stock(self):
        res = self.client.post("/api/inventory/stock-movement", json={
            "flavour": "Tomato",
            "movement_type": "Stock Added",
            "quantity": 10,
            "reference": "Supplier Inward Batch #101"
        })
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["old_stock"], 20)
        self.assertEqual(data["new_stock"], 30)

    def test_02_stock_added_rejects_negative_or_zero(self):
        res_zero = self.client.post("/api/inventory/stock-movement", json={
            "flavour": "Tomato",
            "movement_type": "Stock Added",
            "quantity": 0,
            "reference": "Zero test"
        })
        self.assertEqual(res_zero.status_code, 400)
        self.assertIn("must be greater than 0", res_zero.json()["detail"])

        res_neg = self.client.post("/api/inventory/stock-movement", json={
            "flavour": "Tomato",
            "movement_type": "Stock Added",
            "quantity": -5,
            "reference": "Neg test"
        })
        self.assertEqual(res_neg.status_code, 400)
        self.assertIn("must be greater than 0", res_neg.json()["detail"])

    def test_03_adjustment_positive_increases_stock(self):
        # Current Tomato stock is 30
        res = self.client.post("/api/inventory/stock-movement", json={
            "flavour": "Tomato",
            "movement_type": "Adjustment",
            "quantity": 5,
            "reference": "Found 5 extra boxes"
        })
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["old_stock"], 30)
        self.assertEqual(data["new_stock"], 35)

    def test_04_adjustment_negative_decreases_stock(self):
        # Current Tomato stock is 35
        res = self.client.post("/api/inventory/stock-movement", json={
            "flavour": "Tomato",
            "movement_type": "Adjustment",
            "quantity": -8,
            "reference": "Damaged in transit"
        })
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["old_stock"], 35)
        self.assertEqual(data["new_stock"], 27)

    def test_05_adjustment_rejects_zero(self):
        res = self.client.post("/api/inventory/stock-movement", json={
            "flavour": "Tomato",
            "movement_type": "Adjustment",
            "quantity": 0,
            "reference": "Zero adjustment"
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("Adjustment quantity cannot be 0", res.json()["detail"])

    def test_06_adjustment_prevents_negative_stock(self):
        # Current Cheese stock is 5
        # Attempt to deduct 10 (adjustment -10)
        res = self.client.post("/api/inventory/stock-movement", json={
            "flavour": "Cheese",
            "movement_type": "Adjustment",
            "quantity": -10,
            "reference": "Exceeds stock"
        })
        self.assertEqual(res.status_code, 400)
        detail = res.json()["detail"]
        self.assertIn("Adjustment exceeds available stock", detail)
        self.assertIn("Stock cannot be negative", detail)

        # Confirm Cheese stock is still 5
        cursor = self.raw_db.cursor()
        cursor.execute("SELECT current_stock FROM inventory WHERE flavour = 'Cheese';")
        self.assertEqual(cursor.fetchone()["current_stock"], 5)

    def test_07_adjustment_allows_reducing_stock_to_zero(self):
        # Current Cheese stock is 5
        # Deduct exactly 5 (adjustment -5)
        res = self.client.post("/api/inventory/stock-movement", json={
            "flavour": "Cheese",
            "movement_type": "Adjustment",
            "quantity": -5,
            "reference": "Reconciled to zero"
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["new_stock"], 0)

        # Confirm Cheese stock in DB is 0
        cursor = self.raw_db.cursor()
        cursor.execute("SELECT current_stock FROM inventory WHERE flavour = 'Cheese';")
        self.assertEqual(cursor.fetchone()["current_stock"], 0)

    def test_08_inventory_history_records_movements_correctly(self):
        res = self.client.get("/api/inventory")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        movements = data["movements"]
        self.assertTrue(len(movements) >= 4)

        # Check latest movement: Reconciled to zero (-5)
        latest = movements[0]
        self.assertEqual(latest["flavour"], "Cheese")
        self.assertEqual(latest["type"], "Adjustment")
        self.assertEqual(latest["change"], -5)
        self.assertEqual(latest["reference"], "Reconciled to zero")
