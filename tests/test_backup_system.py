"""
Automated Test Suite for POPCONE CRM Backup & Recovery Engine (Stage 1)
-----------------------------------------------------------------------
Tests:
1. AES-256-GCM encryption & decryption round-trip with unique nonces.
2. Cryptographic tampering detection (ciphertext, header, signature, magic bytes).
3. Checksum verification and payload corruption detection.
4. Sensitive data filtering (sessions excluded, password hashes and customer PII encrypted at rest).
5. Tier 1 and Tier 2 offline verification with in-memory SQLite sandbox.
6. Relational constraint validation (orphaned order items, missing admin).
7. S3 Distributed Lock concurrency, mutual exclusion, and stale lock expiry.
8. Storage configuration errors and truncated/incomplete upload handling.
9. Strict enforcement of the Stage 1 production restoration safety barrier.
"""

import os
import json
import uuid
import struct
import secrets
import hashlib
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# Import backup engine modules
import backup_service


def create_sample_snapshot():
    """Generates a realistic valid database snapshot matching the POPCONE CRM schema."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "extracted_at": now_str,
        "schema_version": 1,
        "schema": [
            {
                "name": "users",
                "type": "table",
                "sql": """CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('ADMIN', 'MEMBER')),
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );"""
            },
            {
                "name": "settings",
                "type": "table",
                "sql": """CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );"""
            },
            {
                "name": "inventory",
                "type": "table",
                "sql": """CREATE TABLE inventory (
                    flavour TEXT PRIMARY KEY,
                    current_stock INTEGER NOT NULL DEFAULT 0,
                    low_stock_threshold INTEGER NOT NULL DEFAULT 10,
                    updated_at TEXT NOT NULL
                );"""
            },
            {
                "name": "inventory_movements",
                "type": "table",
                "sql": """CREATE TABLE inventory_movements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    flavour TEXT NOT NULL,
                    movement_type TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    reference TEXT NOT NULL,
                    created_by TEXT NOT NULL
                );"""
            },
            {
                "name": "orders",
                "type": "table",
                "sql": """CREATE TABLE orders (
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
                    edited_at TEXT NOT NULL,
                    discount_per_bottle REAL NOT NULL DEFAULT 0.0,
                    total_discount REAL NOT NULL DEFAULT 0.0,
                    normal_product_amount REAL NOT NULL DEFAULT 0.0,
                    is_combo INTEGER NOT NULL DEFAULT 0,
                    combo_type TEXT NOT NULL DEFAULT '',
                    combo_price REAL NOT NULL DEFAULT 0.0
                );"""
            },
            {
                "name": "order_items",
                "type": "table",
                "sql": """CREATE TABLE order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    flavour TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    line_amount REAL NOT NULL,
                    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE
                );"""
            },
            {
                "name": "audit_logs",
                "type": "table",
                "sql": """CREATE TABLE audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user TEXT NOT NULL,
                    action TEXT NOT NULL,
                    entity_id TEXT,
                    details TEXT NOT NULL
                );"""
            }
        ],
        "table_counts": {
            "users": 2,
            "settings": 3,
            "inventory": 4,
            "inventory_movements": 2,
            "orders": 1,
            "order_items": 2,
            "audit_logs": 2
        },
        "tables": {
            "users": [
                {"id": 1, "username": "ashish@popcone", "display_name": "Ashish", "role": "ADMIN", "password_hash": "salt1$100000$hash1", "created_at": now_str, "updated_at": now_str},
                {"id": 2, "username": "shriya@popcone", "display_name": "Shriya", "role": "MEMBER", "password_hash": "salt2$100000$hash2", "created_at": now_str, "updated_at": now_str}
            ],
            "settings": [
                {"key": "bottle_price", "value": "160", "updated_at": now_str},
                {"key": "discount_per_bottle", "value": "11", "updated_at": now_str},
                {"key": "low_stock_threshold", "value": "10", "updated_at": now_str}
            ],
            "inventory": [
                {"flavour": "Tomato", "current_stock": 50, "low_stock_threshold": 10, "updated_at": now_str},
                {"flavour": "Cheese", "current_stock": 40, "low_stock_threshold": 10, "updated_at": now_str},
                {"flavour": "Sour Cream", "current_stock": 30, "low_stock_threshold": 10, "updated_at": now_str},
                {"flavour": "Peri Peri", "current_stock": 25, "low_stock_threshold": 10, "updated_at": now_str}
            ],
            "inventory_movements": [
                {"id": 1, "timestamp": now_str, "flavour": "Tomato", "movement_type": "Stock Added", "quantity": 50, "reference": "Batch #1", "created_by": "ashish@popcone"},
                {"id": 2, "timestamp": now_str, "flavour": "Cheese", "movement_type": "Stock Added", "quantity": 40, "reference": "Batch #1", "created_by": "ashish@popcone"}
            ],
            "orders": [
                {
                    "id": 1,
                    "order_id": "ORD-20261017-001",
                    "customer_name": "Ravi Kumar",
                    "phone": "9876543210",
                    "address": "123 Anna Salai, Chennai",
                    "pin_code": "600002",
                    "state": "Tamil Nadu",
                    "district": "Chennai",
                    "total_bottles": 2,
                    "total_weight_grams": 200,
                    "unit_price": 160.0,
                    "product_amount": 298.0,
                    "delivery_fee": 65.0,
                    "final_amount": 363.0,
                    "payment": "Paid",
                    "dispatch_state": "PLACED",
                    "created_by": "shriya@popcone",
                    "created_at": now_str,
                    "edited_by": "shriya@popcone",
                    "edited_at": now_str,
                    "discount_per_bottle": 11.0,
                    "total_discount": 22.0,
                    "normal_product_amount": 298.0,
                    "is_combo": 0,
                    "combo_type": "",
                    "combo_price": 0.0
                }
            ],
            "order_items": [
                {"id": 1, "order_id": "ORD-20261017-001", "flavour": "Tomato", "quantity": 1, "unit_price": 149.0, "line_amount": 149.0},
                {"id": 2, "order_id": "ORD-20261017-001", "flavour": "Cheese", "quantity": 1, "unit_price": 149.0, "line_amount": 149.0}
            ],
            "audit_logs": [
                {"id": 1, "timestamp": now_str, "user": "ashish@popcone", "action": "SYSTEM_INIT", "entity_id": None, "details": "Initialized CRM database"},
                {"id": 2, "timestamp": now_str, "user": "shriya@popcone", "action": "CREATE_ORDER", "entity_id": "ORD-20261017-001", "details": "Created order"}
            ]
        }
    }


class TestBackupEngine(unittest.TestCase):

    def setUp(self):
        self.orig_env = dict(os.environ)
        # Clear any ambient Google Drive credentials to ensure S3 engine tests run in isolation
        for k in ["GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN",
                  "GDRIVE_FOLDER_ID", "GDRIVE_SERVICE_ACCOUNT_JSON"]:
            os.environ.pop(k, None)

        self.enc_key = secrets.token_bytes(32)
        self.sign_key = secrets.token_bytes(32)
        self.enc_keyring = {"enc_v1": self.enc_key}
        self.sign_keyring = {"sign_v1": self.sign_key}
        self.snapshot = create_sample_snapshot()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)

    def test_encryption_decryption_round_trip(self):
        """Test complete AES-256-GCM + HMAC packaging and verification."""
        archive_bytes, header = backup_service.create_backup_package(
            self.snapshot,
            backup_type="MANUAL",
            enc_key=self.enc_key,
            sign_key=self.sign_key,
            enc_key_id="enc_v1",
            sign_key_id="sign_v1"
        )

        self.assertTrue(archive_bytes.startswith(backup_service.BACKUP_MAGIC))
        self.assertEqual(header["enc_key_id"], "enc_v1")
        self.assertEqual(header["sign_key_id"], "sign_v1")

        # Tier 1 verification
        dec_header, dec_snapshot = backup_service.verify_backup_tier1(
            archive_bytes,
            enc_keyring=self.enc_keyring,
            sign_keyring=self.sign_keyring
        )
        self.assertEqual(dec_header["backup_id"], header["backup_id"])
        self.assertEqual(dec_snapshot["table_counts"]["orders"], 1)
        self.assertEqual(dec_snapshot["tables"]["orders"][0]["order_id"], "ORD-20261017-001")

    def test_nonce_uniqueness(self):
        """Test that two backups of identical data produce different ciphertexts due to fresh 96-bit nonces."""
        pkg1, _ = backup_service.create_backup_package(self.snapshot, enc_key=self.enc_key, sign_key=self.sign_key)
        pkg2, _ = backup_service.create_backup_package(self.snapshot, enc_key=self.enc_key, sign_key=self.sign_key)
        self.assertNotEqual(pkg1, pkg2)

    def test_ciphertext_tamper_detection(self):
        """Test that modifying even a single byte in the ciphertext fails verification."""
        archive_bytes, _ = backup_service.create_backup_package(self.snapshot, enc_key=self.enc_key, sign_key=self.sign_key)
        mutable = bytearray(archive_bytes)
        # Flip bit near end of ciphertext
        mutable[-5] ^= 0xFF
        tampered_bytes = bytes(mutable)

        with self.assertRaises(backup_service.BackupIntegrityError) as ctx:
            backup_service.verify_backup_tier1(tampered_bytes, self.enc_keyring, self.sign_keyring)
        self.assertIn("tampered", str(ctx.exception).lower())

    def test_header_tamper_detection(self):
        """Test that modifying envelope metadata (e.g. table_counts or payload_sha256) fails HMAC authentication."""
        archive_bytes, _ = backup_service.create_backup_package(self.snapshot, enc_key=self.enc_key, sign_key=self.sign_key)
        mutable = bytearray(archive_bytes)
        # Header starts after magic (8 bytes) + signature (32 bytes) + len (4 bytes)
        # Flip a byte inside header
        mutable[50] ^= 0x01
        tampered_bytes = bytes(mutable)

        with self.assertRaises(backup_service.BackupIntegrityError):
            backup_service.verify_backup_tier1(tampered_bytes, self.enc_keyring, self.sign_keyring)

    def test_hmac_signature_tamper_detection(self):
        """Test that tampering directly with the HMAC signature fails immediately."""
        archive_bytes, _ = backup_service.create_backup_package(self.snapshot, enc_key=self.enc_key, sign_key=self.sign_key)
        mutable = bytearray(archive_bytes)
        # Signature is at index 8..40
        mutable[12] ^= 0xAA
        tampered_bytes = bytes(mutable)

        with self.assertRaises(backup_service.BackupIntegrityError) as ctx:
            backup_service.verify_backup_tier1(tampered_bytes, self.enc_keyring, self.sign_keyring)
        self.assertIn("mismatch", str(ctx.exception).lower())

    def test_sensitive_data_protection(self):
        """Verify sessions table is completely excluded and customer PII is encrypted at rest."""
        archive_bytes, _ = backup_service.create_backup_package(self.snapshot, enc_key=self.enc_key, sign_key=self.sign_key)

        # 1. sessions table must not exist in snapshot
        self.assertNotIn("sessions", self.snapshot["tables"])

        # 2. Customer phone and password hashes must NOT appear as plaintext in the archive binary
        self.assertNotIn(b"9876543210", archive_bytes)
        self.assertNotIn(b"salt1$100000$hash1", archive_bytes)
        self.assertNotIn(b"123 Anna Salai", archive_bytes)

    def test_tier2_offline_verification_success(self):
        """Test Tier 2 in-memory SQLite sandbox verification passes on valid snapshot."""
        res = backup_service.verify_backup_tier2(self.snapshot)
        self.assertTrue(res["tier2_verified"])
        self.assertEqual(res["integrity_check"], "ok")
        self.assertEqual(res["fk_check"], "ok")
        self.assertEqual(res["total_rows"], 16)

    def test_tier2_verification_succeeds_with_alphabetically_sorted_tables(self):
        """
        Regression test: verify Tier 2 verification succeeds when snapshot table keys
        are sorted alphabetically ('order_items' before 'orders'), as occurs when
        unpacked from canonical JSON.
        """
        snapshot = create_sample_snapshot()
        self.assertTrue(len(snapshot["tables"]["orders"]) > 0)
        self.assertTrue(len(snapshot["tables"]["order_items"]) > 0)
        # Verify order_items references orders
        self.assertEqual(
            snapshot["tables"]["orders"][0]["order_id"],
            snapshot["tables"]["order_items"][0]["order_id"]
        )

        # Sort tables alphabetically so 'order_items' strictly precedes 'orders'
        alphabetical_tables = {k: snapshot["tables"][k] for k in sorted(snapshot["tables"].keys())}
        table_keys = list(alphabetical_tables.keys())
        self.assertLess(table_keys.index("order_items"), table_keys.index("orders"))
        snapshot["tables"] = alphabetical_tables

        # Verification must succeed without SQLite FOREIGN KEY constraint error
        res = backup_service.verify_backup_tier2(snapshot)
        self.assertTrue(res["tier2_verified"])
        self.assertEqual(res["integrity_check"], "ok")
        self.assertEqual(res["fk_check"], "ok")
        self.assertEqual(res["total_rows"], 16)
        self.assertIn("orders", res["tables_verified"])
        self.assertIn("order_items", res["tables_verified"])

    def test_tier2_rejects_orphaned_order_items(self):
        """Test Tier 2 rejects foreign key integrity violations (e.g. order items without parent order)."""
        corrupted_snapshot = create_sample_snapshot()
        # Add an orphaned item pointing to non-existent order
        corrupted_snapshot["tables"]["order_items"].append({
            "id": 99,
            "order_id": "ORD-DOES-NOT-EXIST",
            "flavour": "Tomato",
            "quantity": 5,
            "unit_price": 149.0,
            "line_amount": 745.0
        })
        corrupted_snapshot["table_counts"]["order_items"] += 1

        with self.assertRaises(backup_service.BackupIntegrityError) as ctx:
            backup_service.verify_backup_tier2(corrupted_snapshot)
        self.assertTrue(
            "foreign key" in str(ctx.exception).lower() or "orphaned" in str(ctx.exception).lower()
        )

    def test_tier2_rejects_missing_admin(self):
        """Test Tier 2 rejects backup if users table has no ADMIN account."""
        corrupted_snapshot = create_sample_snapshot()
        # Demote admin to member
        for u in corrupted_snapshot["tables"]["users"]:
            u["role"] = "MEMBER"

        with self.assertRaises(backup_service.BackupIntegrityError) as ctx:
            backup_service.verify_backup_tier2(corrupted_snapshot)
        self.assertIn("no admin account", str(ctx.exception).lower())

    def test_truncated_archive_rejection(self):
        """Test that truncated/incomplete archive bytes are rejected cleanly."""
        archive_bytes, _ = backup_service.create_backup_package(self.snapshot, enc_key=self.enc_key, sign_key=self.sign_key)
        truncated = archive_bytes[:20]

        with self.assertRaises(backup_service.BackupIntegrityError) as ctx:
            backup_service.verify_backup_tier1(truncated, self.enc_keyring, self.sign_keyring)
        self.assertIn("truncated", str(ctx.exception).lower())

    def test_s3_storage_unconfigured_error(self):
        """Test that backup operations fail explicitly when S3 credentials are missing."""
        # Temporarily clear S3 env
        old_bucket = os.environ.get("BACKUP_S3_BUCKET")
        old_key = os.environ.get("BACKUP_S3_ACCESS_KEY_ID")
        try:
            os.environ.pop("BACKUP_S3_BUCKET", None)
            os.environ.pop("BACKUP_S3_ACCESS_KEY_ID", None)

            with self.assertRaises(backup_service.StorageConfigurationError) as ctx:
                backup_service.get_s3_config()
            self.assertIn("external s3 object storage is not configured", str(ctx.exception).lower())
        finally:
            if old_bucket:
                os.environ["BACKUP_S3_BUCKET"] = old_bucket
            if old_key:
                os.environ["BACKUP_S3_ACCESS_KEY_ID"] = old_key

    def test_s3_lock_concurrency_and_expiry(self):
        """Test distributed lock mutual exclusion, CAS reclamation, and safe release ownership."""
        mock_s3 = MagicMock()
        storage = {}
        etags = {}
        etag_counter = [1]

        def mock_put_object(**kwargs):
            key = kwargs["Key"]
            # 1. Conditional object creation: IfNoneMatch="*"
            if kwargs.get("IfNoneMatch") == "*" and key in storage:
                from botocore.exceptions import ClientError
                raise ClientError({"Error": {"Code": "PreconditionFailed", "Message": "At least one precondition failed"}}, "PutObject")

            # 2. Conditional CAS update: IfMatch=ETag
            if "IfMatch" in kwargs and key in storage:
                current_etag = etags.get(key)
                if current_etag != kwargs["IfMatch"]:
                    from botocore.exceptions import ClientError
                    raise ClientError({"Error": {"Code": "PreconditionFailed", "Message": "ETag mismatch"}}, "PutObject")

            storage[key] = kwargs["Body"]
            new_etag = f'"etag-{etag_counter[0]}"'
            etag_counter[0] += 1
            etags[key] = new_etag
            return {"ETag": new_etag}

        def mock_get_object(**kwargs):
            key = kwargs["Key"]
            if key not in storage:
                from botocore.exceptions import ClientError
                raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "GetObject")
            class MockBody:
                def read(self):
                    return storage[key]
            return {"Body": MockBody(), "ETag": etags.get(key, '"etag-0"')}

        def mock_delete_object(**kwargs):
            key = kwargs["Key"]
            storage.pop(key, None)
            etags.pop(key, None)
            return {}

        mock_s3.put_object.side_effect = mock_put_object
        mock_s3.get_object.side_effect = mock_get_object
        mock_s3.delete_object.side_effect = mock_delete_object

        # 1. Acquire lock 1 -> succeeds via IfNoneMatch='*'
        lock1 = backup_service.S3DistributedLock(mock_s3, "test-bucket", initiated_by="user_a", ttl_seconds=300)
        lock1.acquire()
        self.assertTrue(lock1.acquired)

        # 2. Acquire lock 2 concurrently while lock 1 is active -> fails with ConcurrencyLockError
        lock2 = backup_service.S3DistributedLock(mock_s3, "test-bucket", initiated_by="user_b", ttl_seconds=300)
        with self.assertRaises(backup_service.ConcurrencyLockError):
            lock2.acquire()

        # 3. Simulate stale lock: set expires_at in the past
        past_time = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        stale_payload = json.dumps({
            "job_id": "stale-job",
            "initiated_by": "dead_worker",
            "created_at": past_time,
            "expires_at": past_time,
            "ttl_seconds": 300
        }).encode("utf-8")
        storage[backup_service.LOCK_S3_KEY] = stale_payload
        etags[backup_service.LOCK_S3_KEY] = '"etag-stale"'

        # 4. Acquire lock 3 over expired stale lock -> succeeds with CAS (IfMatch=etag)
        lock3 = backup_service.S3DistributedLock(mock_s3, "test-bucket", initiated_by="user_c", ttl_seconds=300)
        lock3.acquire()
        self.assertTrue(lock3.acquired)

        # 5. Safe release: verify that an expired lock from an earlier worker (e.g. lock1)
        # cannot delete the lock owned by lock3
        lock1.release()
        # lock3 must STILL be present in storage!
        self.assertIn(backup_service.LOCK_S3_KEY, storage)
        self.assertTrue(lock3.acquired)

        # 6. lock3 releases its own lock cleanly
        lock3.release()
        self.assertNotIn(backup_service.LOCK_S3_KEY, storage)

    def test_turso_data_extraction_snapshot_consistency(self):
        """
        Verify that Turso data extraction executes in a single atomic batch pipeline,
        ensuring point-in-time snapshot consistency even under concurrent writes.
        """
        # Mock Turso client that tracks batch queries
        mock_turso = MagicMock()

        class MockResultSet:
            def __init__(self, columns, rows):
                self.columns = columns
                self.rows = rows

        def mock_batch(batch_queries):
            # Assert all 9 extraction queries (sqlite_master, pragma user_version, + 7 tables)
            # are executed together in a single atomic batch call
            self.assertEqual(len(batch_queries), 9)
            self.assertIn("sqlite_master", batch_queries[0])
            self.assertIn("PRAGMA user_version", batch_queries[1])
            self.assertEqual(batch_queries[2], "SELECT * FROM users;")
            self.assertEqual(batch_queries[6], "SELECT * FROM orders;")
            self.assertEqual(batch_queries[7], "SELECT * FROM order_items;")

            # Return consistent snapshot result sets
            return [
                MockResultSet(["name", "type", "sql"], [("users", "table", "CREATE TABLE users (id INTEGER);")]),
                MockResultSet(["user_version"], [[1]]),
                MockResultSet(["id", "username", "display_name", "role", "password_hash", "created_at", "updated_at"],
                              [[1, "admin@popcone", "Admin", "ADMIN", "hash", "2026-10-17", "2026-10-17"]]),
                MockResultSet(["key", "value", "updated_at"], [["k1", "v1", "2026-10-17"]]),
                MockResultSet(["flavour", "current_stock", "low_stock_threshold", "updated_at"], [["Tomato", 50, 10, "2026-10-17"]]),
                MockResultSet(["id", "timestamp", "flavour", "movement_type", "quantity", "reference", "created_by"], []),
                MockResultSet(["id", "order_id", "customer_name", "phone", "address", "pin_code", "state", "district",
                               "total_bottles", "total_weight_grams", "unit_price", "product_amount", "delivery_fee",
                               "final_amount", "payment", "dispatch_state", "created_by", "created_at", "edited_by",
                               "edited_at", "discount_per_bottle", "total_discount", "normal_product_amount",
                               "is_combo", "combo_type", "combo_price"],
                              [[1, "ORD-1", "John", "999", "Addr", "600001", "TN", "Chennai", 1, 100, 160.0, 149.0, 50.0, 199.0,
                                "Paid", "PLACED", "user", "2026-10-17", "user", "2026-10-17", 11.0, 11.0, 149.0, 0, "", 0.0]]),
                MockResultSet(["id", "order_id", "flavour", "quantity", "unit_price", "line_amount"],
                              [[1, "ORD-1", "Tomato", 1, 149.0, 149.0]]),
                MockResultSet(["id", "timestamp", "user", "action", "entity_id", "details"], [])
            ]

        mock_turso.batch.side_effect = mock_batch

        # Perform extraction
        snapshot = backup_service.extract_database_snapshot(client=mock_turso)

        # Verify snapshot consistency
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["table_counts"]["orders"], 1)
        self.assertEqual(snapshot["table_counts"]["order_items"], 1)
        self.assertEqual(snapshot["tables"]["orders"][0]["order_id"], snapshot["tables"]["order_items"][0]["order_id"])
        mock_turso.batch.assert_called_once()

    def test_production_restoration_disabled_safety_barrier(self):
        """Verify strict enforcement that production restoration is disabled in Stage 1."""
        with self.assertRaises(backup_service.RestorationDisabledError) as ctx:
            backup_service.restore_production_database()
        self.assertIn("disabled in stage 1", str(ctx.exception).lower())

    def test_api_restore_endpoint_is_forbidden(self):
        """Verify API level safety barrier returns HTTP 403 when attempting restore in Stage 1."""
        from starlette.testclient import TestClient
        from server import app, require_admin

        # Override require_admin to simulate authenticated admin user
        app.dependency_overrides[require_admin] = lambda: {"id": 1, "username": "ashish@popcone", "role": "ADMIN"}
        try:
            client = TestClient(app)
            response = client.post("/api/admin/backups/restore")
            self.assertEqual(response.status_code, 403)
            self.assertIn("disabled in stage 1", response.json()["detail"].lower())
        finally:
            app.dependency_overrides.clear()

    def test_api_status_requires_admin(self):
        """Verify non-admin / unauthenticated requests are rejected with 401/403."""
        from starlette.testclient import TestClient
        from server import app

        client = TestClient(app)
        # 1. Unauthenticated -> 401
        res1 = client.get("/api/admin/backups/status")
        self.assertEqual(res1.status_code, 401)

        # 2. Member user -> 403
        from server import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"id": 2, "username": "shriya@popcone", "role": "MEMBER"}
        try:
            res2 = client.get("/api/admin/backups/status")
            self.assertEqual(res2.status_code, 403)
        finally:
            app.dependency_overrides.clear()

    def test_cron_secret_authentication(self):
        """Verify CRON_SECRET authentication on /api/cron/daily-backup."""
        from starlette.testclient import TestClient
        from server import app

        client = TestClient(app)
        old_secret = os.environ.get("CRON_SECRET")
        test_secret = "test_cron_secret_abc123_xyz789"
        os.environ["CRON_SECRET"] = test_secret

        try:
            # 1. Missing Authorization header -> 401
            res1 = client.get("/api/cron/daily-backup")
            self.assertEqual(res1.status_code, 401)
            self.assertIn("authorization", res1.json()["detail"].lower())

            # 2. Invalid Bearer token -> 401
            res2 = client.get("/api/cron/daily-backup", headers={"Authorization": "Bearer wrong_secret"})
            self.assertEqual(res2.status_code, 401)
            self.assertIn("invalid", res2.json()["detail"].lower())

            # 3. Server missing CRON_SECRET -> 500
            os.environ.pop("CRON_SECRET", None)
            res3 = client.get("/api/cron/daily-backup", headers={"Authorization": "Bearer any_token"})
            self.assertEqual(res3.status_code, 500)
            self.assertIn("cron_secret is not configured", res3.json()["detail"].lower())
        finally:
            if old_secret:
                os.environ["CRON_SECRET"] = old_secret
            else:
                os.environ.pop("CRON_SECRET", None)

    def test_calendar_day_idempotency(self):
        """Verify that check_daily_backup_idempotency correctly identifies same-day completed backups."""
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        manifest = [
            {
                "backup_id": "bak_today_001",
                "backup_type": "SCHEDULED_DAILY",
                "status": "COMPLETED",
                "tier1_verified": True,
                "created_at": f"{today_utc}T02:00:00+00:00",
                "size_bytes": 1024
            },
            {
                "backup_id": "bak_yesterday_001",
                "backup_type": "SCHEDULED_DAILY",
                "status": "COMPLETED",
                "tier1_verified": True,
                "created_at": "2026-10-16T02:00:00+00:00",
                "size_bytes": 1024
            }
        ]

        # Should match today's backup
        today_match = backup_service.check_daily_backup_idempotency(manifest)
        self.assertIsNotNone(today_match)
        self.assertEqual(today_match["backup_id"], "bak_today_001")

        # Different date should match yesterday
        yesterday_match = backup_service.check_daily_backup_idempotency(manifest, target_date_utc="2026-10-16")
        self.assertIsNotNone(yesterday_match)
        self.assertEqual(yesterday_match["backup_id"], "bak_yesterday_001")

        # Date without daily backup returns None
        none_match = backup_service.check_daily_backup_idempotency(manifest, target_date_utc="2026-10-15")
        self.assertIsNone(none_match)

        # Manual backup on same day should not count as SCHEDULED_DAILY
        manual_manifest = [
            {
                "backup_id": "bak_manual_today",
                "backup_type": "MANUAL",
                "status": "COMPLETED",
                "tier1_verified": True,
                "created_at": f"{today_utc}T10:00:00+00:00"
            }
        ]
        self.assertIsNone(backup_service.check_daily_backup_idempotency(manual_manifest))

    def test_safe_retention_pruning_protects_minimum_retained(self):
        """Verify retention pruning deletes expired archives while strictly preserving MIN_BACKUPS_RETAINED."""
        mock_s3 = MagicMock()
        deleted_keys = []

        def mock_delete_object(**kwargs):
            deleted_keys.append(kwargs["Key"])
            return {}

        mock_s3.delete_object.side_effect = mock_delete_object

        # Create 5 backups: all 50 days old
        old_time = (datetime.now(timezone.utc) - timedelta(days=50)).isoformat()
        manifest_entries = [
            {
                "backup_id": f"bak_old_{i}",
                "created_at": old_time,
                "s3_archive_key": f"archives/bak_old_{i}.enc.bak",
                "s3_metadata_key": f"metadata/bak_old_{i}.meta.json"
            }
            for i in range(5)
        ]

        saved_manifest = []
        def mock_get_manifest(*args, **kwargs):
            return list(manifest_entries)

        def mock_save_manifest(entries, *args, **kwargs):
            saved_manifest.clear()
            saved_manifest.extend(entries)

        orig_get = backup_service.get_backups_manifest
        orig_save = backup_service._save_backups_manifest
        orig_cfg = backup_service.get_s3_config
        backup_service.get_backups_manifest = mock_get_manifest
        backup_service._save_backups_manifest = mock_save_manifest
        backup_service.get_s3_config = lambda: {"bucket": "test-b", "access_key": "k", "secret_key": "s"}

        try:
            # Retention = 30 days, min_retained = 3
            res = backup_service.prune_expired_backups(
                s3_client=mock_s3,
                bucket="test-b",
                retention_days=30,
                min_retained=3
            )

            # Exactly 2 backups pruned (5 - 3 = 2), 3 strictly protected!
            self.assertEqual(res["pruned_count"], 2)
            self.assertEqual(res["surviving_count"], 3)
            # 2 backups * 2 objects (archive + meta) = 4 delete calls
            self.assertEqual(len(deleted_keys), 4)
            # Updated manifest must have exactly 3 backups
            self.assertEqual(len(saved_manifest), 3)

            # Re-running with 3 backups should prune 0 backups
            deleted_keys.clear()
            manifest_entries = list(saved_manifest)
            res2 = backup_service.prune_expired_backups(
                s3_client=mock_s3,
                bucket="test-b",
                retention_days=30,
                min_retained=3
            )
            self.assertEqual(res2["pruned_count"], 0)
            self.assertEqual(len(deleted_keys), 0)
        finally:
            backup_service.get_backups_manifest = orig_get
            backup_service._save_backups_manifest = orig_save
            backup_service.get_s3_config = orig_cfg

    def test_retention_pruning_handles_s3_deletion_errors(self):
        """Verify that an S3 deletion failure does not drop the backup from the manifest or crash pruning."""
        mock_s3 = MagicMock()
        from botocore.exceptions import ClientError
        mock_s3.delete_object.side_effect = ClientError({"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "DeleteObject")

        old_time = (datetime.now(timezone.utc) - timedelta(days=50)).isoformat()
        manifest_entries = [
            {"backup_id": "bak_1", "created_at": old_time, "s3_archive_key": "archives/bak_1.enc.bak", "s3_metadata_key": "metadata/bak_1.meta.json"},
            {"backup_id": "bak_2", "created_at": old_time, "s3_archive_key": "archives/bak_2.enc.bak", "s3_metadata_key": "metadata/bak_2.meta.json"}
        ]

        orig_get = backup_service.get_backups_manifest
        orig_save = backup_service._save_backups_manifest
        orig_cfg = backup_service.get_s3_config
        backup_service.get_backups_manifest = lambda *args, **kwargs: list(manifest_entries)
        saved_manifest = []
        backup_service._save_backups_manifest = lambda entries, *args, **kwargs: saved_manifest.extend(entries)
        backup_service.get_s3_config = lambda: {"bucket": "test-b", "access_key": "k", "secret_key": "s"}

        try:
            # min_retained = 1 -> candidate bak_2 should attempt deletion, but fail
            res = backup_service.prune_expired_backups(
                s3_client=mock_s3,
                bucket="test-b",
                retention_days=30,
                min_retained=1
            )
            self.assertEqual(res["pruned_count"], 0)
            self.assertTrue(len(res["errors"]) > 0)
            self.assertIn("failed to delete", res["errors"][0].lower())
        finally:
            backup_service.get_backups_manifest = orig_get
            backup_service._save_backups_manifest = orig_save
            backup_service.get_s3_config = orig_cfg

    def test_cron_daily_backup_flow_with_idempotency(self):
        """Verify complete cron daily backup endpoint flow: execution on run 1, idempotent skip on run 2."""
        from starlette.testclient import TestClient
        from server import app

        client = TestClient(app)
        test_secret = "cron_secret_test_flow_123"
        os.environ["CRON_SECRET"] = test_secret

        mock_s3 = MagicMock()
        mock_db = MagicMock()
        storage = {}

        def mock_put_object(**kwargs):
            storage[kwargs["Key"]] = kwargs["Body"]
            return {"ETag": '"etag-1"'}

        def mock_get_object(**kwargs):
            key = kwargs["Key"]
            if key not in storage:
                from botocore.exceptions import ClientError
                raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "GetObject")
            class MockBody:
                def read(self):
                    return storage[key]
            return {"Body": MockBody(), "ETag": '"etag-1"'}

        mock_s3.put_object.side_effect = mock_put_object
        mock_s3.get_object.side_effect = mock_get_object
        mock_s3.delete_object.return_value = {}

        class MockResultSet:
            def __init__(self, cols, rows):
                self.columns = cols
                self.rows = rows

        sample_snap = create_sample_snapshot()
        schema_rows = [(item["name"], item["type"], item["sql"]) for item in sample_snap["schema"]]

        mock_db.batch.return_value = [
            MockResultSet(["name", "type", "sql"], schema_rows),
            MockResultSet(["user_version"], [[1]]),
            MockResultSet(["id", "username", "display_name", "role", "password_hash", "created_at", "updated_at"],
                          [[1, "admin@popcone", "Admin", "ADMIN", "h", "2026-10-17", "2026-10-17"]]),
            MockResultSet(["key", "value", "updated_at"], []),
            MockResultSet(["flavour", "current_stock", "low_stock_threshold", "updated_at"], []),
            MockResultSet(["id", "timestamp", "flavour", "movement_type", "quantity", "reference", "created_by"], []),
            MockResultSet(["id", "order_id", "customer_name", "phone", "address", "pin_code", "state", "district",
                           "total_bottles", "total_weight_grams", "unit_price", "product_amount", "delivery_fee",
                           "final_amount", "payment", "dispatch_state", "created_by", "created_at", "edited_by",
                           "edited_at", "discount_per_bottle", "total_discount", "normal_product_amount",
                           "is_combo", "combo_type", "combo_price"], []),
            MockResultSet(["id", "order_id", "flavour", "quantity", "unit_price", "line_amount"], []),
            MockResultSet(["id", "timestamp", "user", "action", "entity_id", "details"], [])
        ]

        orig_s3_cfg = backup_service.get_s3_config
        orig_s3_client = backup_service.get_s3_client
        orig_crypto = backup_service.get_crypto_keyring
        key = secrets.token_bytes(32)

        backup_service.get_s3_config = lambda: {"bucket": "test-b", "access_key": "k", "secret_key": "s"}
        backup_service.get_s3_client = lambda cfg=None: mock_s3
        backup_service.get_crypto_keyring = lambda: ({"enc_v1": key}, "enc_v1", {"sign_v1": key}, "sign_v1")

        import database
        orig_get_shared = database.get_shared_client
        database.get_shared_client = lambda: mock_db

        try:
            # 1. First cron invocation -> executes backup
            headers = {"Authorization": f"Bearer {test_secret}"}
            res1 = client.get("/api/cron/daily-backup", headers=headers)
            self.assertEqual(res1.status_code, 200)
            data1 = res1.json()
            self.assertEqual(data1["status"], "COMPLETED")
            self.assertEqual(data1["backup"]["backup_type"], "SCHEDULED_DAILY")

            # 2. Second cron invocation on same day -> idempotent skip
            res2 = client.get("/api/cron/daily-backup", headers=headers)
            self.assertEqual(res2.status_code, 200)
            data2 = res2.json()
            self.assertEqual(data2["status"], "ALREADY_COMPLETED")
            self.assertEqual(data2["backup_id"], data1["backup"]["backup_id"])
        finally:
            backup_service.get_s3_config = orig_s3_cfg
            backup_service.get_s3_client = orig_s3_client
            backup_service.get_crypto_keyring = orig_crypto
            database.get_shared_client = orig_get_shared
            os.environ.pop("CRON_SECRET", None)



# ===========================================================================
# Google Drive Backup Storage Test Suite (Stage 3)
# ===========================================================================

class MockAboutResource:
    def __init__(self, service):
        self.service = service

    def get(self, fields="storageQuota"):
        class MockExec:
            def __init__(self, s):
                self.s = s
            def execute(self):
                return {
                    "storageQuota": {
                        "limit": str(self.s.quota_limit),
                        "usage": str(self.s.quota_usage)
                    }
                }
        return MockExec(self.service)


class MockFilesResource:
    def __init__(self, service):
        self.service = service

    def list(self, q="", **kwargs):
        import re
        name_match = re.search(r"name = '([^']+)'", q)
        parent_match = re.search(r"'([^']+)' in parents", q)
        target_name = name_match.group(1) if name_match else None
        target_parent = parent_match.group(1) if parent_match else None

        results = []
        for fid, f in self.service.files_map.items():
            if target_name and f.get("name") != target_name:
                continue
            if target_parent and target_parent not in f.get("parents", []):
                continue
            results.append({"id": fid, "name": f.get("name")})

        class MockExec:
            def execute(self_inner):
                return {"files": results}
        return MockExec()

    def create(self, body=None, media_body=None, **kwargs):
        fid = f"gdrive_file_{self.service.id_counter}"
        self.service.id_counter += 1
        data = b""
        if media_body and hasattr(media_body, "_fd"):
            data = media_body._fd.getvalue()

        parents = (body or {}).get("parents", [])
        name = (body or {}).get("name", "")
        self.service.files_map[fid] = {
            "id": fid,
            "name": name,
            "parents": parents,
            "data": data,
            "mimeType": (body or {}).get("mimeType", "")
        }
        self.service.quota_usage += len(data)

        class MockExec:
            def execute(self_inner):
                return {"id": fid}
        return MockExec()

    def update(self, fileId, media_body=None, **kwargs):
        data = b""
        if media_body and hasattr(media_body, "_fd"):
            data = media_body._fd.getvalue()
        if fileId in self.service.files_map:
            old_len = len(self.service.files_map[fileId]["data"])
            self.service.files_map[fileId]["data"] = data
            self.service.quota_usage += (len(data) - old_len)
        class MockExec:
            def execute(self_inner):
                return {"id": fileId}
        return MockExec()

    def get_media(self, fileId, **kwargs):
        f = self.service.files_map.get(fileId, {})
        class MockExec:
            def execute(self_inner):
                return f.get("data", b"")
        return MockExec()

    def delete(self, fileId, **kwargs):
        f = self.service.files_map.pop(fileId, None)
        if f:
            self.service.quota_usage = max(0, self.service.quota_usage - len(f.get("data", b"")))
        class MockExec:
            def execute(self_inner):
                return {}
        return MockExec()


class MockGoogleDriveService:
    """In-memory mock of the Google Drive v3 API client."""
    def __init__(self, quota_limit: int = 15 * 1024 * 1024 * 1024, quota_usage: int = 1024 * 1024):
        self.quota_limit = quota_limit
        self.quota_usage = quota_usage
        self.files_map = {}
        self.id_counter = 1
        self._files_resource = MockFilesResource(self)
        self._about_resource = MockAboutResource(self)

    def files(self):
        return self._files_resource

    def about(self):
        return self._about_resource


class TestGoogleDriveBackupStorage(unittest.TestCase):
    """
    Automated tests for Google Drive backup storage provider:
    - Configuration and provider resolution
    - Authentication and token refresh failure handling
    - Storage quota verification (free 15 GB tier protection)
    - Distributed locking and mutual exclusion in Google Drive
    - Complete backup package creation and cryptographic validation
    - Offline archive verification by ID
    - Calendar-day idempotency for automated cron backups
    - Safe retention pruning preserving minimum backups
    - Upload failure handling and existing backup safety
    - FastAPI admin and cron endpoint integration
    """

    def setUp(self):
        self.orig_env = dict(os.environ)
        # Clear any ambient storage credentials
        for k in ["GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN",
                  "GDRIVE_FOLDER_ID", "BACKUP_S3_BUCKET", "BACKUP_S3_ACCESS_KEY_ID",
                  "BACKUP_S3_SECRET_ACCESS_KEY", "CRON_SECRET"]:
            os.environ.pop(k, None)

        # Set consistent cryptographic keys
        self.key = secrets.token_bytes(32)
        self.key_hex = self.key.hex()
        os.environ["BACKUP_ENCRYPTION_KEY"] = self.key_hex
        os.environ["BACKUP_SIGNING_KEY"] = self.key_hex
        os.environ["CURRENT_ENCRYPTION_KEY_ID"] = "enc_v1"
        os.environ["CURRENT_SIGNING_KEY_ID"] = "sign_v1"

        self.mock_srv = MockGoogleDriveService()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)

    def _setup_mock_turso(self):
        """Builds a mock Turso database batch pipeline returning sample data."""
        mock_db = MagicMock()
        sample_snap = create_sample_snapshot()
        schema_rows = [(item["name"], item["type"], item["sql"]) for item in sample_snap["schema"]]

        class MockResultSet:
            def __init__(self, cols, rows):
                self.columns = cols
                self.rows = rows

        mock_db.batch.return_value = [
            MockResultSet(["name", "type", "sql"], schema_rows),
            MockResultSet(["user_version"], [[1]]),
            MockResultSet(["id", "username", "display_name", "role", "password_hash", "created_at", "updated_at"],
                          [[1, "admin@popcone", "Admin", "ADMIN", "hash_abc", "2026-10-17", "2026-10-17"]]),
            MockResultSet(["key", "value", "updated_at"], [["bottle_price", "250", "2026-10-17"]]),
            MockResultSet(["flavour", "current_stock", "low_stock_threshold", "updated_at"], [["Salted", 50, 10, "2026-10-17"]]),
            MockResultSet(["id", "timestamp", "flavour", "movement_type", "quantity", "reference", "created_by"], []),
            MockResultSet(["id", "order_id", "customer_name", "phone", "address", "pin_code", "state", "district",
                           "total_bottles", "total_weight_grams", "unit_price", "product_amount", "delivery_fee",
                           "final_amount", "payment", "dispatch_state", "created_by", "created_at", "edited_by",
                           "edited_at", "discount_per_bottle", "total_discount", "normal_product_amount",
                           "is_combo", "combo_type", "combo_price"], []),
            MockResultSet(["id", "order_id", "flavour", "quantity", "unit_price", "line_amount"], []),
            MockResultSet(["id", "timestamp", "user", "action", "entity_id", "details"], [])
        ]
        return mock_db

    def test_gdrive_configuration_detection(self):
        """Verify configuration detection, placeholder rejection, and provider precedence."""
        self.assertFalse(backup_service.is_gdrive_configured())
        self.assertEqual(backup_service.get_storage_provider(), "none")
        self.assertFalse(backup_service.is_storage_configured())

        # Placeholder rejection
        os.environ["GDRIVE_CLIENT_ID"] = "your_gdrive_client_id_here"
        os.environ["GDRIVE_CLIENT_SECRET"] = "your_gdrive_client_secret_here"
        os.environ["GDRIVE_REFRESH_TOKEN"] = "your_gdrive_refresh_token_here"
        self.assertFalse(backup_service.is_gdrive_configured())

        # Valid configuration
        os.environ["GDRIVE_CLIENT_ID"] = "client-id-123.apps.googleusercontent.com"
        os.environ["GDRIVE_CLIENT_SECRET"] = "secret-xyz"
        os.environ["GDRIVE_REFRESH_TOKEN"] = "1//refresh-token-abc"
        self.assertTrue(backup_service.is_gdrive_configured())
        self.assertEqual(backup_service.get_storage_provider(), "gdrive")
        self.assertTrue(backup_service.is_storage_configured())

        # Precedence over S3
        os.environ["BACKUP_S3_BUCKET"] = "test-bucket"
        os.environ["BACKUP_S3_ACCESS_KEY_ID"] = "s3-access"
        os.environ["BACKUP_S3_SECRET_ACCESS_KEY"] = "s3-secret"
        self.assertEqual(backup_service.get_storage_provider(), "gdrive")

        # Fallback to S3 if GDrive unconfigured
        os.environ.pop("GDRIVE_CLIENT_ID")
        self.assertEqual(backup_service.get_storage_provider(), "s3")

    def test_gdrive_authentication_failure_handling(self):
        """Verify AuthenticationError is raised with clear remediation instructions on auth failure."""
        os.environ["GDRIVE_CLIENT_ID"] = "invalid_client_id"
        os.environ["GDRIVE_CLIENT_SECRET"] = "invalid_secret"
        os.environ["GDRIVE_REFRESH_TOKEN"] = "expired_token"

        with unittest.mock.patch("google.oauth2.credentials.Credentials.refresh") as mock_refresh:
            from google.auth.exceptions import RefreshError
            mock_refresh.side_effect = RefreshError("Token has been expired or revoked.")

            with self.assertRaises(backup_service.AuthenticationError) as ctx:
                backup_service.get_gdrive_credentials()

            err_msg = str(ctx.exception)
            self.assertIn("authentication failed", err_msg.lower())

    def test_gdrive_quota_check_and_quota_exceeded(self):
        """Verify storage quota verification protecting Google Drive's free 15 GB tier."""
        # 1. Healthy quota: 15 GB total, 100 MB used -> Plenty of room
        srv = MockGoogleDriveService(quota_limit=15 * 1024 * 1024 * 1024, quota_usage=100 * 1024 * 1024)
        quota_info = backup_service.check_gdrive_quota(srv, required_bytes=5 * 1024 * 1024)
        self.assertTrue(quota_info["quota_ok"])
        self.assertGreater(quota_info["remaining_bytes"], 14 * 1024 * 1024 * 1024)

        # 2. Exhausted quota: 15 GB total, 14.999 GB used -> Less than required 5 MB
        srv_full = MockGoogleDriveService(quota_limit=15 * 1024 * 1024 * 1024, quota_usage=(15 * 1024 * 1024 * 1024) - (1024 * 1024))
        with self.assertRaises(backup_service.QuotaExceededError) as ctx:
            backup_service.check_gdrive_quota(srv_full, required_bytes=5 * 1024 * 1024)
        self.assertIn("quota exceeded", str(ctx.exception).lower())

        # 3. Upload error handling: Drive API returning quota limit error
        with unittest.mock.patch.object(srv.files(), "create", side_effect=Exception("User storage quota exceeded [403]")):
            with self.assertRaises(backup_service.QuotaExceededError):
                backup_service.upload_bytes_to_gdrive(srv, "folder_1", "test.bin", b"some_data")

    def test_gdrive_distributed_lock_mutual_exclusion_and_expiry(self):
        """Verify distributed locking in Google Drive: concurrency rejection, TTL expiry, and ownership safety."""
        srv = MockGoogleDriveService()
        folders = backup_service.ensure_gdrive_folders(srv)
        root_id = folders["root"]

        # 1. First lock acquisition succeeds
        lock1 = backup_service.GDriveDistributedLock(srv, root_id, initiated_by="worker_1", ttl_seconds=300)
        lock1.acquire()
        self.assertTrue(lock1.acquired)

        # 2. Concurrent second lock attempt fails
        lock2 = backup_service.GDriveDistributedLock(srv, root_id, initiated_by="worker_2", ttl_seconds=300)
        with self.assertRaises(backup_service.ConcurrencyLockError):
            lock2.acquire()

        # 3. Simulate expired stale lock (> 300 seconds ago)
        expired_time = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        stale_payload = {
            "job_id": "stale_job_123",
            "initiated_by": "dead_worker",
            "created_at": expired_time,
            "expires_at": expired_time,
            "ttl_seconds": 300
        }
        backup_service.upload_bytes_to_gdrive(
            srv, root_id, backup_service.GDRIVE_LOCK_NAME,
            json.dumps(stale_payload).encode("utf-8"),
            mime_type="application/json"
        )

        # 4. Third worker reclaims stale lock successfully
        lock3 = backup_service.GDriveDistributedLock(srv, root_id, initiated_by="worker_3", ttl_seconds=300)
        lock3.acquire()
        self.assertTrue(lock3.acquired)

        # 5. Lock release verifies ownership (lock1 cannot release lock3's lock)
        lock1.release()
        lock_bytes = backup_service.download_bytes_from_gdrive(srv, root_id, backup_service.GDRIVE_LOCK_NAME)
        lock_data = json.loads(lock_bytes.decode("utf-8"))
        self.assertEqual(lock_data["job_id"], lock3.job_id)

        # Safe release by owner
        lock3.release()
        with self.assertRaises(backup_service.StorageConfigurationError):
            backup_service.download_bytes_from_gdrive(srv, root_id, backup_service.GDRIVE_LOCK_NAME)

    def test_gdrive_successful_backup_creation_and_crypto_verification(self):
        """Verify complete Google Drive backup: AES-256-GCM encryption, HMAC signing, and Tier 1/2 checks."""
        os.environ["GDRIVE_CLIENT_ID"] = "client-id-123"
        os.environ["GDRIVE_CLIENT_SECRET"] = "secret-xyz"
        os.environ["GDRIVE_REFRESH_TOKEN"] = "refresh-abc"

        mock_db = self._setup_mock_turso()
        srv = self.mock_srv

        # Execute backup
        meta = backup_service.execute_gdrive_backup(
            backup_type="MANUAL",
            initiated_by="admin_test",
            service=srv,
            db_client=mock_db
        )

        # Check metadata
        self.assertEqual(meta["status"], "COMPLETED")
        self.assertEqual(meta["storage_provider"], "gdrive")
        self.assertTrue(meta["tier1_verified"])
        self.assertTrue(meta["tier2_verified"])
        self.assertEqual(meta["enc_key_id"], "enc_v1")
        self.assertEqual(meta["sign_key_id"], "sign_v1")

        backup_id = meta["backup_id"]
        folders = backup_service.ensure_gdrive_folders(srv)

        # Verify archive bytes in Google Drive
        archive_bytes = backup_service.download_bytes_from_gdrive(srv, folders["archives"], f"{backup_id}.enc.bak")
        self.assertTrue(archive_bytes.startswith(backup_service.BACKUP_MAGIC))

        # Cryptographic verification
        header, snapshot = backup_service.verify_backup_tier1(archive_bytes)
        self.assertEqual(header["backup_id"], backup_id)
        self.assertEqual(header["payload_sha256"], hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode("utf-8")).hexdigest())

        # Relational verification
        tier2_res = backup_service.verify_backup_tier2(snapshot)
        self.assertTrue(tier2_res["tier2_verified"])
        self.assertEqual(tier2_res["integrity_check"], "ok")
        self.assertEqual(tier2_res["fk_check"], "ok")

        # Sensitive data check: active sessions must NOT exist in snapshot
        self.assertNotIn("sessions", snapshot.get("tables", {}))

        # Manifest verification in Google Drive
        manifest = backup_service.get_gdrive_manifest(srv, folders["root"])
        self.assertEqual(len(manifest), 1)
        self.assertEqual(manifest[0]["backup_id"], backup_id)

    def test_gdrive_verify_backup_archive_by_id_and_tamper_detection(self):
        """Verify downloading and checking existing archives by ID, including tamper detection."""
        os.environ["GDRIVE_CLIENT_ID"] = "client-id-123"
        os.environ["GDRIVE_CLIENT_SECRET"] = "secret-xyz"
        os.environ["GDRIVE_REFRESH_TOKEN"] = "refresh-abc"

        mock_db = self._setup_mock_turso()
        srv = self.mock_srv
        meta = backup_service.execute_gdrive_backup(
            backup_type="MANUAL",
            initiated_by="admin_test",
            service=srv,
            db_client=mock_db
        )
        backup_id = meta["backup_id"]

        # Verification by ID passes
        header, snapshot = backup_service.verify_backup_archive_by_id(backup_id, gdrive_service=srv)
        self.assertEqual(header["backup_id"], backup_id)

        # Tamper detection: Corrupt a single byte of ciphertext in Drive
        folders = backup_service.ensure_gdrive_folders(srv)
        arch_bytes = bytearray(backup_service.download_bytes_from_gdrive(srv, folders["archives"], f"{backup_id}.enc.bak"))
        arch_bytes[-1] ^= 0xFF  # Flip bits in signature/tag
        backup_service.upload_bytes_to_gdrive(srv, folders["archives"], f"{backup_id}.enc.bak", bytes(arch_bytes))

        with self.assertRaises(backup_service.BackupIntegrityError):
            backup_service.verify_backup_archive_by_id(backup_id, gdrive_service=srv)

    def test_gdrive_scheduled_daily_backup_idempotency(self):
        """Verify calendar-day idempotency: cron backup executes once per UTC day and skips duplicates."""
        os.environ["GDRIVE_CLIENT_ID"] = "client-id-123"
        os.environ["GDRIVE_CLIENT_SECRET"] = "secret-xyz"
        os.environ["GDRIVE_REFRESH_TOKEN"] = "refresh-abc"

        mock_db = self._setup_mock_turso()
        srv = self.mock_srv

        # First run on today UTC -> COMPLETED
        res1 = backup_service.execute_gdrive_scheduled_daily_backup(service=srv, db_client=mock_db)
        self.assertEqual(res1["status"], "COMPLETED")
        self.assertEqual(res1["backup"]["backup_type"], "SCHEDULED_DAILY")
        backup_id_1 = res1["backup"]["backup_id"]

        # Second run on same day -> ALREADY_COMPLETED
        res2 = backup_service.execute_gdrive_scheduled_daily_backup(service=srv, db_client=mock_db)
        self.assertEqual(res2["status"], "ALREADY_COMPLETED")
        self.assertEqual(res2["backup_id"], backup_id_1)

        # Ensure only 1 archive file was created in Google Drive
        folders = backup_service.ensure_gdrive_folders(srv)
        manifest = backup_service.get_gdrive_manifest(srv, folders["root"])
        self.assertEqual(len(manifest), 1)

    def test_gdrive_safe_retention_pruning(self):
        """Verify safe retention pruning in Google Drive: deletes expired files while strictly preserving min_retained."""
        srv = self.mock_srv
        folders = backup_service.ensure_gdrive_folders(srv)
        root_id = folders["root"]
        arch_id = folders["archives"]
        meta_id = folders["metadata"]

        # Create 5 backups in manifest: 1 recent, 4 expired (> 35 days ago)
        now_dt = datetime.now(timezone.utc)
        recent_time = now_dt.isoformat()
        old_time = (now_dt - timedelta(days=45)).isoformat()

        manifest = [
            {"backup_id": "bak_recent", "created_at": recent_time, "archive_filename": "bak_recent.enc.bak", "metadata_filename": "bak_recent.meta.json"},
            {"backup_id": "bak_old_1", "created_at": old_time, "archive_filename": "bak_old_1.enc.bak", "metadata_filename": "bak_old_1.meta.json"},
            {"backup_id": "bak_old_2", "created_at": old_time, "archive_filename": "bak_old_2.enc.bak", "metadata_filename": "bak_old_2.meta.json"},
            {"backup_id": "bak_old_3", "created_at": old_time, "archive_filename": "bak_old_3.enc.bak", "metadata_filename": "bak_old_3.meta.json"},
            {"backup_id": "bak_old_4", "created_at": old_time, "archive_filename": "bak_old_4.enc.bak", "metadata_filename": "bak_old_4.meta.json"}
        ]
        backup_service.save_gdrive_manifest(manifest, srv, root_id)

        # Create dummy archive & metadata files
        for b in manifest:
            backup_service.upload_bytes_to_gdrive(srv, arch_id, b["archive_filename"], b"archive_dummy")
            backup_service.upload_bytes_to_gdrive(srv, meta_id, b["metadata_filename"], b"metadata_dummy")

        # Prune with retention_days=30, min_retained=3
        res = backup_service.prune_expired_gdrive_backups(
            service=srv,
            root_folder_id=root_id,
            retention_days=30,
            min_retained=3
        )

        # 5 total - 3 min_retained = 2 pruned
        self.assertEqual(res["pruned_count"], 2)
        self.assertEqual(res["surviving_count"], 3)
        self.assertEqual(len(res["errors"]), 0)

        # Verify surviving manifest has exactly 3
        surviving_manifest = backup_service.get_gdrive_manifest(srv, root_id)
        self.assertEqual(len(surviving_manifest), 3)

        # Verify pruned files were removed from Drive
        for pruned_id in res["pruned_backups"]:
            with self.assertRaises(backup_service.StorageConfigurationError):
                backup_service.download_bytes_from_gdrive(srv, arch_id, f"{pruned_id}.enc.bak")

    def test_gdrive_retention_pruning_handles_deletion_errors(self):
        """Regression test: verify Google Drive file deletion failure does not drop backup from manifest."""
        srv = self.mock_srv
        folders = backup_service.ensure_gdrive_folders(srv)
        root_id = folders["root"]
        arch_id = folders["archives"]
        meta_id = folders["metadata"]

        old_time = (datetime.now(timezone.utc) - timedelta(days=50)).isoformat()
        manifest = [
            {"backup_id": "bak_keep", "created_at": old_time, "archive_filename": "bak_keep.enc.bak", "metadata_filename": "bak_keep.meta.json"},
            {"backup_id": "bak_fail_del", "created_at": old_time, "archive_filename": "bak_fail_del.enc.bak", "metadata_filename": "bak_fail_del.meta.json"}
        ]
        backup_service.save_gdrive_manifest(manifest, srv, root_id)

        for b in manifest:
            backup_service.upload_bytes_to_gdrive(srv, arch_id, b["archive_filename"], b"archive_dummy")
            backup_service.upload_bytes_to_gdrive(srv, meta_id, b["metadata_filename"], b"metadata_dummy")

        # Mock delete to simulate Google Drive API failure
        orig_delete = srv.files().delete
        def failing_delete(fileId, **kwargs):
            class FailingExec:
                def execute(self_inner):
                    raise RuntimeError("Simulated Google Drive 500 internal server error")
            return FailingExec()

        srv.files().delete = failing_delete
        try:
            res = backup_service.prune_expired_gdrive_backups(
                service=srv,
                root_folder_id=root_id,
                retention_days=30,
                min_retained=1
            )
            self.assertEqual(res["pruned_count"], 0)
            self.assertTrue(len(res["errors"]) > 0)
            self.assertIn("failed to delete", res["errors"][0].lower())

            # Verify both backups are still in the Google Drive manifest
            surviving = backup_service.get_gdrive_manifest(srv, root_id)
            self.assertEqual(len(surviving), 2)
        finally:
            srv.files().delete = orig_delete

    def test_prune_expired_backups_explicit_s3_routing_when_gdrive_configured(self):
        """Regression test: verify prune_expired_backups routes to S3 when s3_client is passed, even if GDrive is configured."""
        os.environ["GDRIVE_CLIENT_ID"] = "client-id-123"
        os.environ["GDRIVE_CLIENT_SECRET"] = "secret-xyz"
        os.environ["GDRIVE_REFRESH_TOKEN"] = "refresh-abc"
        self.assertTrue(backup_service.is_gdrive_configured())

        mock_s3 = MagicMock()
        old_time = (datetime.now(timezone.utc) - timedelta(days=50)).isoformat()
        manifest_entries = [
            {"backup_id": f"bak_{i}", "created_at": old_time, "s3_archive_key": f"archives/bak_{i}.enc.bak", "s3_metadata_key": f"metadata/bak_{i}.meta.json"}
            for i in range(4)
        ]
        orig_get = backup_service.get_backups_manifest
        orig_save = backup_service._save_backups_manifest
        orig_cfg = backup_service.get_s3_config
        saved_manifest = []

        backup_service.get_backups_manifest = lambda *args, **kwargs: list(manifest_entries)
        backup_service._save_backups_manifest = lambda entries, *args, **kwargs: saved_manifest.extend(entries)
        backup_service.get_s3_config = lambda: {"bucket": "test-b", "access_key": "k", "secret_key": "s"}

        try:
            res = backup_service.prune_expired_backups(
                s3_client=mock_s3,
                bucket="test-b",
                retention_days=30,
                min_retained=2
            )
            # 4 total - 2 min_retained = 2 pruned via S3
            self.assertEqual(res["pruned_count"], 2)
            self.assertEqual(res["surviving_count"], 2)
            self.assertEqual(len(saved_manifest), 2)
        finally:
            backup_service.get_backups_manifest = orig_get
            backup_service._save_backups_manifest = orig_save
            backup_service.get_s3_config = orig_cfg

    def test_gdrive_upload_failure_retains_existing_backups(self):
        """Verify that when an upload fails, previous valid backups in Google Drive are retained untouched."""
        os.environ["GDRIVE_CLIENT_ID"] = "client-id-123"
        os.environ["GDRIVE_CLIENT_SECRET"] = "secret-xyz"
        os.environ["GDRIVE_REFRESH_TOKEN"] = "refresh-abc"

        mock_db = self._setup_mock_turso()
        srv = self.mock_srv

        # First backup succeeds
        meta1 = backup_service.execute_gdrive_backup(
            backup_type="MANUAL",
            initiated_by="admin_test",
            service=srv,
            db_client=mock_db
        )
        backup_id_1 = meta1["backup_id"]
        folders = backup_service.ensure_gdrive_folders(srv)

        # Next backup fails during upload (e.g. network error / API error)
        orig_upload = backup_service.upload_bytes_to_gdrive
        call_count = 0
        def fail_on_archive_upload(service, folder_id, file_name, data, mime_type="application/octet-stream"):
            nonlocal call_count
            call_count += 1
            if file_name.endswith(".enc.bak"):
                raise backup_service.BackupError("Simulated socket connection abort")
            return orig_upload(service, folder_id, file_name, data, mime_type)

        with unittest.mock.patch("backup_service.upload_bytes_to_gdrive", side_effect=fail_on_archive_upload):
            with self.assertRaises(backup_service.BackupError):
                backup_service.execute_gdrive_backup(
                    backup_type="MANUAL",
                    initiated_by="admin_test",
                    service=srv,
                    db_client=mock_db
                )

        # Verify existing backup 1 is still completely intact in manifest and storage
        manifest = backup_service.get_gdrive_manifest(srv, folders["root"])
        self.assertEqual(len(manifest), 1)
        self.assertEqual(manifest[0]["backup_id"], backup_id_1)
        arch_bytes = backup_service.download_bytes_from_gdrive(srv, folders["archives"], f"{backup_id_1}.enc.bak")
        self.assertTrue(len(arch_bytes) > 0)

    def test_gdrive_fastapi_endpoints_integration(self):
        """Verify /api/admin/backups/* and /api/cron/daily-backup with Google Drive storage."""
        from starlette.testclient import TestClient
        import server
        from server import app
        import database

        client = TestClient(app)
        os.environ["GDRIVE_CLIENT_ID"] = "client-id-123"
        os.environ["GDRIVE_CLIENT_SECRET"] = "secret-xyz"
        os.environ["GDRIVE_REFRESH_TOKEN"] = "refresh-abc"
        os.environ["CRON_SECRET"] = "cron_secret_test_xyz"

        mock_db = self._setup_mock_turso()
        srv = self.mock_srv

        app.dependency_overrides[server.require_admin] = lambda: {"username": "admin", "role": "ADMIN"}

        try:
            with unittest.mock.patch("backup_service.get_gdrive_service", return_value=srv), \
                 unittest.mock.patch("database.get_shared_client", return_value=mock_db):

                # 1. Status endpoint
                res = client.get("/api/admin/backups/status")
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data["storage_provider"], "gdrive")
                self.assertTrue(data["gdrive_configured"])
                self.assertIn("Google Drive", data["storage_backend"])
                self.assertIn("gdrive_quota", data)

                # 2. Trigger manual backup endpoint
                res = client.post("/api/admin/backups")
                self.assertEqual(res.status_code, 201)
                b_meta = res.json()["backup"]
                backup_id = b_meta["backup_id"]
                self.assertEqual(b_meta["storage_provider"], "gdrive")

                # 3. List manifest endpoint
                res = client.get("/api/admin/backups/manifest")
                self.assertEqual(res.status_code, 200)
                manifest_data = res.json()
                self.assertTrue(manifest_data["configured"])
                self.assertEqual(manifest_data["storage_provider"], "gdrive")
                self.assertEqual(len(manifest_data["backups"]), 1)

                # 4. Verify existing backup endpoint
                res = client.post(f"/api/admin/backups/{backup_id}/verify")
                self.assertEqual(res.status_code, 200)
                v_data = res.json()
                self.assertTrue(v_data["tier1_verified"])
                self.assertTrue(v_data["tier2_verified"])

                # 5. Cron scheduled backup endpoint
                cron_headers = {"Authorization": "Bearer cron_secret_test_xyz"}
                cron_res = client.get("/api/cron/daily-backup", headers=cron_headers)
                self.assertEqual(cron_res.status_code, 200)
                cron_data = cron_res.json()
                self.assertEqual(cron_data["status"], "COMPLETED")
                self.assertEqual(cron_data["backup"]["backup_type"], "SCHEDULED_DAILY")

                # 6. Safety check: Restore endpoint is strictly forbidden
                restore_res = client.post("/api/admin/backups/restore")
                self.assertEqual(restore_res.status_code, 403)
        finally:
            app.dependency_overrides.pop(server.require_admin, None)


class TestLongTermRetentionAndRecovery(unittest.TestCase):
    """
    Comprehensive tests for:
    - Preserving historical business data (>1 year old) in full snapshots.
    - 90-day daily retention and 12-month monthly recovery points.
    - Protection of latest backup and sole recovery points.
    - Fail-safe retention pruning on corrupted/malformed manifests.
    - Isolated offline reconstitution and integrity checks without touching production.
    - Admin-only authorization and duplicate manual backup handling.
    """

    def setUp(self):
        self.enc_key = b"A" * 32
        self.sign_key = b"B" * 32
        os.environ["BACKUP_ENCRYPTION_KEY"] = self.enc_key.hex()
        os.environ["BACKUP_SIGNING_KEY"] = self.sign_key.hex()

    def tearDown(self):
        os.environ.pop("BACKUP_ENCRYPTION_KEY", None)
        os.environ.pop("BACKUP_SIGNING_KEY", None)

    def test_full_historical_database_snapshot_includes_old_records_and_customers(self):
        """Verify full snapshot captures all historical records including 400-day-old orders and customer details."""
        now_dt = datetime.now(timezone.utc)
        historical_dt_str = (now_dt - timedelta(days=400)).strftime("%Y-%m-%d %H:%M:%S")

        mock_turso = MagicMock()

        class MockResultSet:
            def __init__(self, columns, rows):
                self.columns = columns
                self.rows = rows

        mock_turso.batch.return_value = [
            MockResultSet(
                ["name", "type", "sql"],
                [
                    ("users", "table", "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, role TEXT, password_hash TEXT, created_at TEXT, updated_at TEXT);"),
                    ("settings", "table", "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);"),
                    ("inventory", "table", "CREATE TABLE inventory (flavour TEXT PRIMARY KEY, current_stock INTEGER, low_stock_threshold INTEGER, updated_at TEXT);"),
                    ("inventory_movements", "table", "CREATE TABLE inventory_movements (id INTEGER PRIMARY KEY, timestamp TEXT, flavour TEXT, movement_type TEXT, quantity INTEGER, reference TEXT, created_by TEXT);"),
                    ("orders", "table", "CREATE TABLE orders (id INTEGER PRIMARY KEY, order_id TEXT UNIQUE, customer_name TEXT, phone TEXT, address TEXT, pin_code TEXT, state TEXT, district TEXT, total_bottles INTEGER, total_weight_grams INTEGER, unit_price REAL, product_amount REAL, delivery_fee REAL, final_amount REAL, payment TEXT, dispatch_state TEXT, created_by TEXT, created_at TEXT, edited_by TEXT, edited_at TEXT);"),
                    ("order_items", "table", "CREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id TEXT, flavour TEXT, quantity INTEGER, unit_price REAL, line_amount REAL, FOREIGN KEY (order_id) REFERENCES orders(order_id));"),
                    ("audit_logs", "table", "CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, timestamp TEXT, user TEXT, action TEXT, entity_id TEXT, details TEXT);"),
                ]
            ),
            MockResultSet(["user_version"], [(1,)]),
            # users
            MockResultSet(["id", "username", "display_name", "role", "password_hash", "created_at", "updated_at"], [
                (1, "ashish@popcone", "Ashish", "ADMIN", "hash_admin", historical_dt_str, historical_dt_str),
                (2, "shriya@popcone", "Shriya", "MEMBER", "hash_member", historical_dt_str, historical_dt_str),
            ]),
            # settings
            MockResultSet(["key", "value", "updated_at"], [
                ("bottle_price", "160", historical_dt_str),
            ]),
            # inventory
            MockResultSet(["flavour", "current_stock", "low_stock_threshold", "updated_at"], [
                ("Tomato", 50, 10, historical_dt_str),
                ("Cheese", 40, 10, historical_dt_str),
            ]),
            # inventory_movements
            MockResultSet(["id", "timestamp", "flavour", "movement_type", "quantity", "reference", "created_by"], [
                (1, historical_dt_str, "Tomato", "Initial Stock", 50, "Batch 0", "Ashish"),
            ]),
            # orders - contains historical order from 400 days ago
            MockResultSet(
                ["id", "order_id", "customer_name", "phone", "address", "pin_code", "state", "district", "total_bottles", "total_weight_grams", "unit_price", "product_amount", "delivery_fee", "final_amount", "payment", "dispatch_state", "created_by", "created_at", "edited_by", "edited_at"],
                [
                    (1, "ORD-HIST-001", "Old Customer Alice", "9876543210", "123 Old Heritage Rd", "560001", "Karnataka", "Bengaluru", 2, 500, 160.0, 320.0, 50.0, 370.0, "Paid", "DISPATCHED", "Shriya", historical_dt_str, "Shriya", historical_dt_str)
                ]
            ),
            # order_items
            MockResultSet(["id", "order_id", "flavour", "quantity", "unit_price", "line_amount"], [
                (1, "ORD-HIST-001", "Tomato", 1, 160.0, 160.0),
                (2, "ORD-HIST-001", "Cheese", 1, 160.0, 160.0),
            ]),
            # audit_logs
            MockResultSet(["id", "timestamp", "user", "action", "entity_id", "details"], [
                (1, historical_dt_str, "Shriya", "CREATE_ORDER", "ORD-HIST-001", "Order created 400 days ago"),
            ]),
        ]

        # Extract snapshot
        snapshot = backup_service.extract_database_snapshot(client=mock_turso)
        self.assertIn("orders", snapshot["tables"])
        self.assertEqual(len(snapshot["tables"]["orders"]), 1)
        self.assertEqual(snapshot["tables"]["orders"][0]["order_id"], "ORD-HIST-001")
        self.assertEqual(snapshot["tables"]["orders"][0]["customer_name"], "Old Customer Alice")

        # Package snapshot
        pkg, header = backup_service.create_backup_package(snapshot, backup_type="MANUAL")
        self.assertTrue(header["backup_id"].startswith("bak_"))

        # Tier 1 verification
        hdr1, decrypted_snapshot = backup_service.verify_backup_tier1(pkg)
        self.assertEqual(hdr1["backup_id"], header["backup_id"])

        # Tier 2 verification
        tier2 = backup_service.verify_backup_tier2(decrypted_snapshot)
        self.assertTrue(tier2["tier2_verified"])
        self.assertEqual(tier2["integrity_check"], "ok")
        self.assertEqual(tier2["fk_check"], "ok")

    def test_isolated_restore_to_sqlite_reconstitutes_historical_orders(self):
        """Verify restore_snapshot_to_sqlite creates an isolated, queryable SQLite sandbox."""
        snapshot = {
            "schema": [
                {"name": "orders", "type": "table", "sql": "CREATE TABLE orders (order_id TEXT PRIMARY KEY, customer_name TEXT, total_amount REAL);"},
                {"name": "order_items", "type": "table", "sql": "CREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id TEXT, flavour TEXT, quantity INTEGER, FOREIGN KEY(order_id) REFERENCES orders(order_id));"},
                {"name": "users", "type": "table", "sql": "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT);"}
            ],
            "tables": {
                "orders": [{"order_id": "ORD-1", "customer_name": "Bob", "total_amount": 320.0}],
                "order_items": [{"id": 1, "order_id": "ORD-1", "flavour": "Peri Peri", "quantity": 2}],
                "users": [{"id": 1, "username": "ashish@popcone", "role": "ADMIN"}]
            }
        }

        conn = backup_service.restore_snapshot_to_sqlite(snapshot, target_db_path=":memory:")
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT customer_name, total_amount FROM orders WHERE order_id = 'ORD-1';")
            row = cursor.fetchone()
            self.assertEqual(row, ("Bob", 320.0))

            cursor.execute("SELECT flavour, quantity FROM order_items WHERE order_id = 'ORD-1';")
            item = cursor.fetchone()
            self.assertEqual(item, ("Peri Peri", 2))

            cursor.execute("PRAGMA foreign_key_check;")
            self.assertEqual(len(cursor.fetchall()), 0)
        finally:
            conn.close()

    def test_long_term_retention_preserves_daily_90d_and_monthly_12mo_recovery_points(self):
        """Verify 90-day daily retention and 12-month monthly recovery points."""
        now_dt = datetime.now(timezone.utc)

        # 1. Latest backup (today)
        m_today = {"backup_id": "bak_today", "created_at": now_dt.isoformat()}
        # 2. Daily backups (within 90 days)
        m_day20 = {"backup_id": "bak_day20", "created_at": (now_dt - timedelta(days=20)).isoformat()}
        m_day50 = {"backup_id": "bak_day50", "created_at": (now_dt - timedelta(days=50)).isoformat()}
        m_day80 = {"backup_id": "bak_day80", "created_at": (now_dt - timedelta(days=80)).isoformat()}
        # 3. Month -4 (120 days ago): 2 backups in this month -> newest is kept as Monthly Recovery Point, older pruned
        dt_m4_new = now_dt - timedelta(days=120)
        dt_m4_old = now_dt - timedelta(days=125)
        m_m4_new = {"backup_id": "bak_m4_new", "created_at": dt_m4_new.isoformat()}
        m_m4_old = {"backup_id": "bak_m4_old", "created_at": dt_m4_old.isoformat()}
        # 4. Month -7 (210 days ago): single backup in this month -> kept as Monthly Recovery Point
        m_m7 = {"backup_id": "bak_m7", "created_at": (now_dt - timedelta(days=210)).isoformat()}
        # 5. Month -11 (330 days ago): single backup in this month -> kept as Monthly Recovery Point
        m_m11 = {"backup_id": "bak_m11", "created_at": (now_dt - timedelta(days=330)).isoformat()}
        # 6. Month -15 (450 days ago): older than 12 months -> eligible for pruning
        m_m15 = {"backup_id": "bak_m15", "created_at": (now_dt - timedelta(days=450)).isoformat()}

        manifest = [m_today, m_day20, m_day50, m_day80, m_m4_new, m_m4_old, m_m7, m_m11, m_m15]

        res = backup_service.classify_backups_for_retention(
            manifest=manifest,
            daily_retention_days=90,
            monthly_retention_months=12,
            min_retained=3,
            now_utc=now_dt
        )

        surviving_ids = {item["backup_id"] for item in res["surviving"]}
        prunable_ids = {item["backup_id"] for item in res["prunable"]}

        # Protected:
        # bak_today (LATEST)
        # bak_day20, bak_day50, bak_day80 (DAILY within 90 days)
        # bak_m4_new (MONTHLY_RECOVERY_POINT for month -4)
        # bak_m7 (MONTHLY_RECOVERY_POINT for month -7)
        # bak_m11 (MONTHLY_RECOVERY_POINT for month -11)
        self.assertIn("bak_today", surviving_ids)
        self.assertIn("bak_day20", surviving_ids)
        self.assertIn("bak_day50", surviving_ids)
        self.assertIn("bak_day80", surviving_ids)
        self.assertIn("bak_m4_new", surviving_ids)
        self.assertIn("bak_m7", surviving_ids)
        self.assertIn("bak_m11", surviving_ids)

        # Pruned:
        # bak_m4_old (redundant backup in month -4, older than 90d)
        # bak_m15 (>12 months old)
        self.assertIn("bak_m4_old", prunable_ids)
        self.assertIn("bak_m15", prunable_ids)
        self.assertEqual(len(prunable_ids), 2)
        self.assertEqual(len(surviving_ids), 7)

    def test_newest_backup_and_sole_recovery_points_protected_even_when_old(self):
        """Verify that an inactive database with only 1 backup from 400 days ago is NEVER pruned."""
        now_dt = datetime.now(timezone.utc)
        m_ancient = {"backup_id": "bak_ancient", "created_at": (now_dt - timedelta(days=400)).isoformat()}

        res = backup_service.classify_backups_for_retention(
            manifest=[m_ancient],
            daily_retention_days=90,
            monthly_retention_months=12,
            min_retained=3,
            now_utc=now_dt
        )

        # Must survive because it is the sole and latest backup!
        self.assertEqual(len(res["prunable"]), 0)
        self.assertEqual(len(res["surviving"]), 1)
        self.assertEqual(res["surviving"][0]["backup_id"], "bak_ancient")

    def test_retention_fails_safe_on_corrupted_or_malformed_manifest(self):
        """Verify malformed manifest entries with invalid dates or corrupted fields are NEVER deleted."""
        now_dt = datetime.now(timezone.utc)
        manifest = [
            {"backup_id": "bak_valid_1", "created_at": now_dt.isoformat()},
            {"backup_id": "bak_valid_2", "created_at": (now_dt - timedelta(days=1)).isoformat()},
            {"backup_id": "bak_valid_3", "created_at": (now_dt - timedelta(days=2)).isoformat()},
            {"backup_id": "bak_valid_4", "created_at": (now_dt - timedelta(days=3)).isoformat()},
            {"backup_id": "bak_corrupt_date", "created_at": "not-a-valid-date-string"},
            {"backup_id": "", "created_at": now_dt.isoformat()},
            "not_even_a_dictionary"
        ]

        res = backup_service.classify_backups_for_retention(
            manifest=manifest,
            daily_retention_days=90,
            monthly_retention_months=12,
            min_retained=3,
            now_utc=now_dt
        )

        surviving_ids = [item.get("backup_id") if isinstance(item, dict) else item for item in res["surviving"]]
        self.assertIn("bak_corrupt_date", surviving_ids)
        self.assertIn("not_even_a_dictionary", surviving_ids)
        # None of the malformed items were marked as prunable
        for p in res["prunable"]:
            self.assertNotEqual(p.get("backup_id"), "bak_corrupt_date")

    def test_admin_only_endpoints_reject_member_and_unauthenticated_requests(self):
        """Verify /api/admin/backups rejects unauthenticated callers and non-admin members."""
        from fastapi.testclient import TestClient
        import server
        from server import app

        client = TestClient(app)

        # 1. Unauthenticated request -> 401
        res = client.post("/api/admin/backups")
        self.assertEqual(res.status_code, 401)

        res_manifest = client.get("/api/admin/backups/manifest")
        self.assertEqual(res_manifest.status_code, 401)

        # 2. Member request (authenticated as MEMBER) -> 403 Forbidden
        app.dependency_overrides[server.require_admin] = lambda: (_ for _ in ()).throw(
            server.HTTPException(status_code=403, detail="Admin privileges required")
        )
        try:
            res_member = client.post("/api/admin/backups")
            self.assertEqual(res_member.status_code, 403)

            res_member_manifest = client.get("/api/admin/backups/manifest")
            self.assertEqual(res_member_manifest.status_code, 403)
        finally:
            app.dependency_overrides.pop(server.require_admin, None)

    def test_env_var_precedence_daily_retention(self):
        """Verify BACKUP_DAILY_RETENTION_DAYS takes precedence over legacy BACKUP_RETENTION_DAYS."""
        now_dt = datetime.now(timezone.utc)
        m = [{"backup_id": "bak1", "created_at": now_dt.isoformat()}]

        # 1. Both present: BACKUP_DAILY_RETENTION_DAYS=90 takes precedence over BACKUP_RETENTION_DAYS=30
        with patch.dict(os.environ, {"BACKUP_DAILY_RETENTION_DAYS": "90", "BACKUP_RETENTION_DAYS": "30"}):
            res1 = backup_service.classify_backups_for_retention(manifest=m, now_utc=now_dt)
            self.assertEqual(res1["daily_retention_days"], 90)

        # 2. Only legacy BACKUP_RETENTION_DAYS=30 present
        with patch.dict(os.environ, {"BACKUP_RETENTION_DAYS": "30"}, clear=False):
            if "BACKUP_DAILY_RETENTION_DAYS" in os.environ:
                del os.environ["BACKUP_DAILY_RETENTION_DAYS"]
            res2 = backup_service.classify_backups_for_retention(manifest=m, now_utc=now_dt)
            self.assertEqual(res2["daily_retention_days"], 30)

        # 3. Neither present: defaults to 90
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BACKUP_DAILY_RETENTION_DAYS", None)
            os.environ.pop("BACKUP_RETENTION_DAYS", None)
            res3 = backup_service.classify_backups_for_retention(manifest=m, now_utc=now_dt)
            self.assertEqual(res3["daily_retention_days"], 90)

    def test_exact_12_month_recovery_point_boundary(self):
        """Verify the exact boundary: month -12 is protected, month -13 is pruned."""
        now_dt = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)

        # Month 0 (current month: Oct 2026)
        m_m0 = {"backup_id": "bak_m0", "created_at": "2026-10-10T10:00:00+00:00"}
        # Minimum 3 retained backups (recent)
        m_m0_2 = {"backup_id": "bak_m0_2", "created_at": "2026-10-09T10:00:00+00:00"}
        m_m0_3 = {"backup_id": "bak_m0_3", "created_at": "2026-10-08T10:00:00+00:00"}

        # Month -12 (Oct 2025: exactly 12 calendar months ago)
        # Two backups in Oct 2025: newest must be kept as recovery point, older pruned
        m_m12_new = {"backup_id": "bak_m12_new", "created_at": "2025-10-25T10:00:00+00:00"}
        m_m12_old = {"backup_id": "bak_m12_old", "created_at": "2025-10-10T10:00:00+00:00"}

        # Month -13 (Sep 2025: 13 calendar months ago -> outside 12-month window)
        m_m13 = {"backup_id": "bak_m13", "created_at": "2025-09-20T10:00:00+00:00"}

        manifest = [m_m0, m_m0_2, m_m0_3, m_m12_new, m_m12_old, m_m13]

        res = backup_service.classify_backups_for_retention(
            manifest=manifest,
            daily_retention_days=90,
            monthly_retention_months=12,
            min_retained=3,
            now_utc=now_dt
        )

        surviving_ids = {item["backup_id"] for item in res["surviving"]}
        prunable_ids = {item["backup_id"] for item in res["prunable"]}

        # Month -12 newest is protected as Monthly Recovery Point
        self.assertIn("bak_m12_new", surviving_ids)
        self.assertEqual(res["category_map"]["bak_m12_new"], "MONTHLY_RECOVERY_POINT")

        # Month -12 older is redundant and older than 90d -> pruned
        self.assertIn("bak_m12_old", prunable_ids)

        # Month -13 is 13 months old -> pruned
        self.assertIn("bak_m13", prunable_ids)

    def test_timezone_normalization_with_non_utc_offsets(self):
        """Verify that parsed timestamps with non-UTC offsets normalize to UTC correctly."""
        now_dt = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)

        # 2026-10-01T01:30:00+05:30 in IST is 2026-09-30T20:00:00Z in UTC (September!)
        m_ist_sep = {
            "backup_id": "bak_ist_sep",
            "created_at": "2026-10-01T01:30:00+05:30"
        }
        # 2026-10-02T10:00:00Z in UTC (October)
        m_utc_oct = {
            "backup_id": "bak_utc_oct",
            "created_at": "2026-10-02T10:00:00+00:00"
        }

        manifest = [m_utc_oct, m_ist_sep]

        res = backup_service.classify_backups_for_retention(
            manifest=manifest,
            daily_retention_days=90,
            monthly_retention_months=12,
            min_retained=1,
            now_utc=now_dt
        )

        # bak_utc_oct is LATEST (month 10)
        self.assertEqual(res["category_map"]["bak_utc_oct"], "LATEST")
        # bak_ist_sep normalized to UTC is September (month 9) and survives
        surviving_ids = {item["backup_id"] for item in res["surviving"]}
        self.assertIn("bak_ist_sep", surviving_ids)

    def test_gdrive_pruning_partial_deletion_safety(self):
        """Verify partial deletion failures do NOT leave misleading healthy manifest entries."""
        mock_srv = MagicMock()
        mock_folders = {"root": "root_1", "archives": "arch_1", "metadata": "meta_1"}

        now_dt = datetime.now(timezone.utc)
        m_recent = {"backup_id": "bak_recent", "created_at": now_dt.isoformat()}
        m_expired_1 = {"backup_id": "bak_exp_1", "created_at": (now_dt - timedelta(days=500)).isoformat()}
        m_expired_2 = {"backup_id": "bak_exp_2", "created_at": (now_dt - timedelta(days=501)).isoformat()}

        manifest = [m_recent, m_expired_1, m_expired_2]

        def mock_delete(srv, folder_id, file_name):
            if "bak_exp_1" in file_name and folder_id == "meta_1":
                raise Exception("Metadata delete failed")
            if "bak_exp_2" in file_name and folder_id == "arch_1":
                raise Exception("Archive delete failed")
            return True

        saved_manifests = []
        with patch.object(backup_service, "get_gdrive_service", return_value=mock_srv), \
             patch.object(backup_service, "ensure_gdrive_folders", return_value=mock_folders), \
             patch.object(backup_service, "get_gdrive_manifest", return_value=manifest), \
             patch.object(backup_service, "delete_gdrive_file", side_effect=mock_delete), \
             patch.object(backup_service, "save_gdrive_manifest", side_effect=lambda m, s, r: saved_manifests.append(list(m))):

            res = backup_service.prune_expired_gdrive_backups(
                service=mock_srv,
                retention_days=90,
                monthly_retention_months=12,
                min_retained=1,
                now_utc=now_dt
            )

            final_manifest = saved_manifests[-1]
            final_ids = {m["backup_id"]: m for m in final_manifest}

            self.assertNotIn("bak_exp_1", final_ids, "Partially deleted backup with missing archive must not remain in manifest as healthy")
            if "bak_exp_2" in final_ids:
                self.assertFalse(final_ids["bak_exp_2"].get("tier1_verified", True))
                self.assertEqual(final_ids["bak_exp_2"].get("status"), "INCOMPLETE_ORPHANED_ARCHIVE")

    def test_gdrive_pruning_fails_safely_on_manifest_error(self):
        """Verify pruning aborts safely with 0 deletions if manifest retrieval fails."""
        mock_srv = MagicMock()
        mock_folders = {"root": "root_1", "archives": "arch_1", "metadata": "meta_1"}

        with patch.object(backup_service, "get_gdrive_service", return_value=mock_srv), \
             patch.object(backup_service, "ensure_gdrive_folders", return_value=mock_folders), \
             patch.object(backup_service, "get_gdrive_manifest", side_effect=backup_service.StorageConfigurationError("Corrupted manifest")), \
             patch.object(backup_service, "delete_gdrive_file") as mock_del:

            res = backup_service.prune_expired_gdrive_backups(service=mock_srv)
            self.assertEqual(res["pruned_count"], 0)
            self.assertTrue(len(res["errors"]) > 0)
            mock_del.assert_not_called()


class TestKeyRotationAndKeyringFallback(unittest.TestCase):
    """
    Regression tests for key rotation, multi-key keyring resolution,
    unversioned rotation ID collision handling, and diagnostic error clarity.
    """

    def setUp(self):
        self.orig_env = dict(os.environ)
        self.sample_snapshot = create_sample_snapshot()
        self.key_v1 = secrets.token_bytes(32)
        self.key_v2 = secrets.token_bytes(32)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)

    def test_unversioned_key_rotation_fallback_with_dict(self):
        """Verify old archives verify via keyring fallback even if key IDs collide on sign_v1."""
        # Archive created with key_v1
        archive_v1, header_v1 = backup_service.create_backup_package(
            self.sample_snapshot,
            enc_key=self.key_v1,
            sign_key=self.key_v1,
            enc_key_id="enc_v1",
            sign_key_id="sign_v1"
        )

        # Environment rotated to key_v2 without changing key IDs
        os.environ["BACKUP_ENCRYPTION_KEY"] = self.key_v2.hex()
        os.environ["BACKUP_SIGNING_KEY"] = self.key_v2.hex()
        os.environ["CURRENT_ENCRYPTION_KEY_ID"] = "enc_v1"
        os.environ["CURRENT_SIGNING_KEY_ID"] = "sign_v1"

        # Without keyring, archive_v1 fails verification
        with self.assertRaises(backup_service.BackupIntegrityError) as ctx:
            backup_service.verify_backup_tier1(archive_v1)
        self.assertIn("HMAC signature mismatch", str(ctx.exception))

        # Add key_v1 to keyring under the same ID (unversioned rotation)
        os.environ["BACKUP_ENCRYPTION_KEYRING_JSON"] = json.dumps({"enc_v1": self.key_v1.hex()})
        os.environ["BACKUP_SIGNING_KEYRING_JSON"] = json.dumps({"sign_v1": self.key_v1.hex()})

        # Now archive_v1 succeeds via keyring fallback
        h1, s1 = backup_service.verify_backup_tier1(archive_v1)
        self.assertEqual(h1["backup_id"], header_v1["backup_id"])
        self.assertEqual(s1["table_counts"]["users"], 2)

        # And a new archive created with key_v2 also verifies cleanly
        archive_v2, header_v2 = backup_service.create_backup_package(self.sample_snapshot)
        h2, s2 = backup_service.verify_backup_tier1(archive_v2)
        self.assertEqual(h2["backup_id"], header_v2["backup_id"])

    def test_unversioned_key_rotation_fallback_with_list(self):
        """Verify old archives verify when keyring is provided as a JSON list of historical keys."""
        archive_v1, _ = backup_service.create_backup_package(
            self.sample_snapshot,
            enc_key=self.key_v1,
            sign_key=self.key_v1,
            enc_key_id="enc_v1",
            sign_key_id="sign_v1"
        )

        os.environ["BACKUP_ENCRYPTION_KEY"] = self.key_v2.hex()
        os.environ["BACKUP_SIGNING_KEY"] = self.key_v2.hex()
        os.environ["BACKUP_ENCRYPTION_KEYRING_JSON"] = json.dumps([self.key_v1.hex()])
        os.environ["BACKUP_SIGNING_KEYRING_JSON"] = json.dumps([self.key_v1.hex()])

        h1, s1 = backup_service.verify_backup_tier1(archive_v1)
        self.assertIn("backup_id", h1)
        self.assertIn("users", s1["tables"])

    def test_fallback_keys_environment_variable(self):
        """Verify comma-separated fallback variables enable legacy archive verification."""
        archive_v1, _ = backup_service.create_backup_package(
            self.sample_snapshot,
            enc_key=self.key_v1,
            sign_key=self.key_v1,
            enc_key_id="enc_v1",
            sign_key_id="sign_v1"
        )

        os.environ["BACKUP_ENCRYPTION_KEY"] = self.key_v2.hex()
        os.environ["BACKUP_SIGNING_KEY"] = self.key_v2.hex()
        os.environ["BACKUP_ENCRYPTION_KEYS_FALLBACK"] = f"{self.key_v1.hex()}"
        os.environ["BACKUP_SIGNING_KEYS_FALLBACK"] = f"{self.key_v1.hex()}"

        h1, s1 = backup_service.verify_backup_tier1(archive_v1)
        self.assertIn("backup_id", h1)
        self.assertEqual(len(s1["tables"]["users"]), 2)

    def test_tampered_archive_rejected_even_with_keyring(self):
        """Ensure cryptographic authenticity is strictly enforced even when fallback keys exist."""
        archive_v1, _ = backup_service.create_backup_package(
            self.sample_snapshot,
            enc_key=self.key_v1,
            sign_key=self.key_v1,
            enc_key_id="enc_v1",
            sign_key_id="sign_v1"
        )

        os.environ["BACKUP_ENCRYPTION_KEY"] = self.key_v2.hex()
        os.environ["BACKUP_SIGNING_KEY"] = self.key_v2.hex()
        os.environ["BACKUP_ENCRYPTION_KEYRING_JSON"] = json.dumps({"legacy": self.key_v1.hex()})
        os.environ["BACKUP_SIGNING_KEYRING_JSON"] = json.dumps({"legacy": self.key_v1.hex()})

        # 1. Tamper HMAC signature bytes -> rejected
        tampered_sig = bytearray(archive_v1)
        tampered_sig[len(backup_service.BACKUP_MAGIC) + 2] ^= 0xFF
        with self.assertRaises(backup_service.BackupIntegrityError):
            backup_service.verify_backup_tier1(bytes(tampered_sig))

        # 2. Tamper ciphertext payload -> rejected
        tampered_body = bytearray(archive_v1)
        tampered_body[-5] ^= 0xFF
        with self.assertRaises(backup_service.BackupIntegrityError):
            backup_service.verify_backup_tier1(bytes(tampered_body))

    def test_key_parsing_strips_quotes(self):
        """Ensure quotes accidentally copied into environment variables are safely stripped."""
        quoted_key = f'"{self.key_v1.hex()}"'
        parsed = backup_service._parse_key_bytes(quoted_key, "TEST_KEY")
        self.assertEqual(parsed, self.key_v1)

        single_quoted = f"'{self.key_v1.hex()}'"
        parsed_sq = backup_service._parse_key_bytes(single_quoted, "TEST_KEY")
        self.assertEqual(parsed_sq, self.key_v1)

    def test_manifest_context_error_on_intact_archive(self):
        """Verify _verify_archive_with_manifest_context reports intact storage when checksum matches."""
        archive_v1, header = backup_service.create_backup_package(
            self.sample_snapshot,
            enc_key=self.key_v1,
            sign_key=self.key_v1,
            enc_key_id="enc_v1",
            sign_key_id="sign_v1"
        )
        arch_sha = header["archive_sha256"]

        # Active key is key_v2 (mismatch)
        os.environ["BACKUP_ENCRYPTION_KEY"] = self.key_v2.hex()
        os.environ["BACKUP_SIGNING_KEY"] = self.key_v2.hex()

        with self.assertRaises(backup_service.BackupIntegrityError) as ctx:
            backup_service._verify_archive_with_manifest_context(
                archive_v1,
                header["backup_id"],
                manifest_sha256=arch_sha
            )
        err_msg = str(ctx.exception)
        self.assertIn("Storage file checksum matches manifest", err_msg)
        self.assertIn("cannot be authenticated or decrypted", err_msg)
        self.assertIn("BACKUP_SIGNING_KEYRING_JSON", err_msg)


if __name__ == "__main__":
    unittest.main()
