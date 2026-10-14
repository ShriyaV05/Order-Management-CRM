import sqlite3
import os
import shutil
from typing import Optional
from datetime import datetime, timezone
from auth import hash_password

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "popcone.db")

def _auto_restore_if_needed(target_path: str):
    """
    Safety Guard: If the database file does not exist or is empty,
    automatically restore from the latest valid backup or template so data is never lost.
    """
    if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
        return

    base_dir = os.path.dirname(os.path.abspath(target_path))
    backup_file = os.path.join(base_dir, "backups", "popcone_latest.bak")
    
    # 1. Restore from latest snapshot backup if available
    if os.path.exists(backup_file) and os.path.getsize(backup_file) > 0:
        try:
            shutil.copy2(backup_file, target_path)
            print(f"[Database Protection] Auto-restored missing database from backup: {backup_file}")
            return
        except Exception as e:
            print(f"[Database Protection] Warning: Failed to restore from backup: {e}")

    # 2. If target is a persistent mount (/var/data, /data, etc.) and DEFAULT_DB_PATH exists, seed from it
    if os.path.abspath(target_path) != os.path.abspath(DEFAULT_DB_PATH):
        if os.path.exists(DEFAULT_DB_PATH) and os.path.getsize(DEFAULT_DB_PATH) > 0:
            try:
                shutil.copy2(DEFAULT_DB_PATH, target_path)
                print(f"[Database Protection] Initialized persistent database from template: {DEFAULT_DB_PATH}")
                return
            except Exception as e:
                print(f"[Database Protection] Warning: Failed to seed from template: {e}")

def backup_database() -> Optional[str]:
    """
    Safely creates an automated snapshot backup of the SQLite database
    in a dedicated 'backups/' directory using SQLite's online backup API.
    Guarantees no file corruption even under active traffic.
    """
    if os.environ.get("TURSO_DATABASE_URL") and os.environ.get("TURSO_AUTH_TOKEN"):
        return None

    db_path = resolve_db_path()
    if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        return None

    try:
        base_dir = os.path.dirname(os.path.abspath(db_path))
        backup_dir = os.path.join(base_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)

        latest_backup_path = os.path.join(backup_dir, "popcone_latest.bak")
        today_str = datetime.now().strftime("%Y-%m-%d")
        daily_backup_path = os.path.join(backup_dir, f"popcone_backup_{today_str}.db")

        # Use SQLite online backup API for crash-safe, non-blocking backup
        src_conn = sqlite3.connect(db_path)
        try:
            # Update latest backup snapshot
            dst_conn_latest = sqlite3.connect(latest_backup_path)
            with dst_conn_latest:
                src_conn.backup(dst_conn_latest)
            dst_conn_latest.close()

            # Update daily backup snapshot
            dst_conn_daily = sqlite3.connect(daily_backup_path)
            with dst_conn_daily:
                src_conn.backup(dst_conn_daily)
            dst_conn_daily.close()
        finally:
            src_conn.close()

        return latest_backup_path
    except Exception as e:
        print(f"[Database Backup] Notice: Could not create backup snapshot: {e}")
        return None

def resolve_db_path() -> str:
    env_path = os.environ.get("DB_PATH")
    if env_path:
        parent_dir = os.path.dirname(env_path)
        if parent_dir and not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except Exception:
                pass
        _auto_restore_if_needed(env_path)
        return env_path

    # Check known persistent mount directories on Render or Docker
    for mount_dir in ["/var/data", "/data", "/app/data"]:
        if os.path.isdir(mount_dir) and os.access(mount_dir, os.W_OK):
            persistent_path = os.path.join(mount_dir, "popcone.db")
            _auto_restore_if_needed(persistent_path)
            return persistent_path

    # Vercel serverless environment fallback
    if os.environ.get("VERCEL") and not (os.environ.get("TURSO_DATABASE_URL") and os.environ.get("TURSO_AUTH_TOKEN")):
        tmp_path = "/tmp/popcone.db"
        _auto_restore_if_needed(tmp_path)
        return tmp_path

    _auto_restore_if_needed(DEFAULT_DB_PATH)
    return DEFAULT_DB_PATH

DB_PATH = resolve_db_path()

class TursoRow(dict):
    def __init__(self, cols, values):
        super().__init__()
        self._values = list(values)
        self._cols = list(cols)
        for c, v in zip(cols, values):
            self[c] = v

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

    def keys(self):
        return self._cols

class TursoCursor:
    def __init__(self, client):
        self.client = client
        self.results = []
        self._pos = 0

    def execute(self, sql, params=None):
        clean_sql = sql.strip().rstrip(";")
        if clean_sql.upper().startswith("PRAGMA FOREIGN_KEYS"):
            return self
        
        args = list(params) if params is not None else []
        res = self.client.execute(sql, args)
        cols = res.columns
        self.results = [TursoRow(cols, row) for row in res.rows]
        self._pos = 0
        return self

    def executemany(self, sql, seq_of_params):
        for params in seq_of_params:
            self.execute(sql, params)
        return self

    def fetchone(self):
        if self._pos < len(self.results):
            row = self.results[self._pos]
            self._pos += 1
            return row
        return None

    def fetchall(self):
        remaining = self.results[self._pos:]
        self._pos = len(self.results)
        return remaining

class TursoConnection:
    def __init__(self, url, token):
        import libsql_client
        clean_url = url.replace("libsql://", "https://")
        self.client = libsql_client.create_client_sync(clean_url, auth_token=token)

    def cursor(self):
        return TursoCursor(self.client)

    def execute(self, sql, params=None):
        cur = self.cursor()
        return cur.execute(sql, params)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.client.close()

def get_db():
    turso_url = os.environ.get("TURSO_DATABASE_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")
    if turso_url and turso_token:
        return TursoConnection(turso_url, turso_token)

    conn = sqlite3.connect(resolve_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
    except Exception:
        pass
    return conn

def init_db():
    # Automatically take a safe snapshot backup before any migrations or initialization
    backup_database()

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
        low_stock_threshold INTEGER NOT NULL DEFAULT 10,
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

    # Safe Schema Migrations for Orders Table (Pricing & Combo Fields)
    cursor.execute("PRAGMA table_info(orders);")
    existing_cols = [row["name"] for row in cursor.fetchall()]

    if "discount_per_bottle" not in existing_cols:
        cursor.execute("ALTER TABLE orders ADD COLUMN discount_per_bottle REAL NOT NULL DEFAULT 0.0;")
    if "total_discount" not in existing_cols:
        cursor.execute("ALTER TABLE orders ADD COLUMN total_discount REAL NOT NULL DEFAULT 0.0;")
    if "normal_product_amount" not in existing_cols:
        cursor.execute("ALTER TABLE orders ADD COLUMN normal_product_amount REAL NOT NULL DEFAULT 0.0;")
    if "is_combo" not in existing_cols:
        cursor.execute("ALTER TABLE orders ADD COLUMN is_combo INTEGER NOT NULL DEFAULT 0;")
    if "combo_type" not in existing_cols:
        cursor.execute("ALTER TABLE orders ADD COLUMN combo_type TEXT NOT NULL DEFAULT '';")
    if "combo_price" not in existing_cols:
        cursor.execute("ALTER TABLE orders ADD COLUMN combo_price REAL NOT NULL DEFAULT 0.0;")

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
            ("bottle_price", "160", now_str),
            ("discount_per_bottle", "11", now_str),
            ("low_stock_threshold", "10", now_str),
        ]
        cursor.executemany("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?);", initial_settings)
        conn.commit()
    else:
        # Ensure required settings exist without overwriting custom values
        required_defaults = [
            ("bottle_price", "160"),
            ("discount_per_bottle", "11"),
            ("low_stock_threshold", "10"),
        ]
        for key, def_val in required_defaults:
            cursor.execute("SELECT value FROM settings WHERE key = ?;", (key,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?);", (key, def_val, now_str))
        conn.commit()

    # Check inventory
    cursor.execute("SELECT COUNT(*) FROM inventory;")
    if cursor.fetchone()[0] == 0:
        initial_inventory = [
            ("Tomato", 0, 10, now_str),
            ("Cheese", 0, 10, now_str),
            ("Sour Cream", 0, 10, now_str),
            ("Peri Peri", 0, 10, now_str),
        ]
        cursor.executemany("INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at) VALUES (?, ?, ?, ?);", initial_inventory)
        conn.commit()

    conn.close()

def reset_crm_data():
    # Hard safety lock to prevent accidental wipes
    if os.environ.get("ALLOW_DANGEROUS_DB_RESET") != "CONFIRM_PERMANENT_WIPE":
        raise RuntimeError(
            "CRITICAL SAFETY LOCK: Database wipe is locked to protect live data. "
            "To force a wipe, set environment variable ALLOW_DANGEROUS_DB_RESET=CONFIRM_PERMANENT_WIPE"
        )
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
