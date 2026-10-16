import os
import sqlite3
import threading
from typing import Optional, List, Tuple, Any
from datetime import datetime, timezone
from auth import hash_password

# Live data lives in ONE Turso database only.
# Orders/inventory are never auto-wiped on startup, deploy, or schema init.
# Allowed deletes: explicit SQL, this app's order-delete API, or a manual AI query.


def _load_env_file():
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass


_load_env_file()

LOCAL_SQLITE_ARCHIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "popcone.db")

PLACEHOLDER_TOKENS = {
    "",
    "your_turso_auth_token_here",
    "changeme",
    "replace_me",
}

SAFE_TABLES = frozenset({
    "users",
    "sessions",
    "settings",
    "inventory",
    "inventory_movements",
    "orders",
    "order_items",
    "audit_logs",
})


def get_turso_credentials() -> Tuple[str, str]:
    url = (os.environ.get("TURSO_DATABASE_URL") or "").strip()
    token = (os.environ.get("TURSO_AUTH_TOKEN") or "").strip()
    if not url or not token or token.lower() in PLACEHOLDER_TOKENS:
        raise RuntimeError(
            "POPCONE requires a single Turso database. "
            "Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in .env "
            "(or the host environment). Local SQLite is disabled so deploys "
            "cannot start on an empty file and look like data was erased."
        )
    return url, token


def using_turso() -> bool:
    try:
        get_turso_credentials()
        return True
    except RuntimeError:
        return False


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
    def __init__(self, conn: "TursoConnection"):
        self.conn = conn
        self.results = []
        self._pos = 0

    def execute(self, sql, params=None):
        clean_sql = sql.strip().rstrip(";")
        upper = clean_sql.upper()
        args = list(params) if params is not None else []

        if upper.startswith("PRAGMA FOREIGN_KEYS"):
            return self

        if upper.startswith("BEGIN"):
            self.conn._pending = []
            return self
        if upper.startswith("COMMIT"):
            self.conn.commit()
            return self
        if upper.startswith("ROLLBACK"):
            self.conn.rollback()
            return self

        if self.conn._pending is not None:
            # Queue writes until commit so they run as one atomic Turso batch.
            self.conn._pending.append((clean_sql, args))
            self.results = []
            self._pos = 0
            return self

        res = self.conn.client.execute(clean_sql, args)
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


_shared_client = None
_client_lock = threading.Lock()


def get_shared_client():
    global _shared_client
    if _shared_client is not None:
        return _shared_client
    with _client_lock:
        if _shared_client is not None:
            return _shared_client
        url, token = get_turso_credentials()
        import libsql_client
        clean_url = url.replace("libsql://", "https://")
        _shared_client = libsql_client.create_client_sync(clean_url, auth_token=token)
        return _shared_client


class TursoConnection:
    def __init__(self, url=None, token=None):
        self.client = get_shared_client()
        self._pending: Optional[List[Tuple[str, list]]] = None

    def cursor(self):
        return TursoCursor(self)

    def execute(self, sql, params=None):
        cur = self.cursor()
        return cur.execute(sql, params)

    def commit(self):
        pending = self._pending
        self._pending = None
        if not pending:
            return
        batch_args: List[Any] = []
        for sql, args in pending:
            batch_args.append((sql, args) if args else sql)
        self.client.batch(batch_args)

    def rollback(self):
        self._pending = None

    def close(self):
        self._pending = None


def get_db():
    return TursoConnection()


def _scalar(row) -> Any:
    if row is None:
        return None
    try:
        if "cnt" in row.keys():
            return row["cnt"]
    except Exception:
        pass
    return row[0]


def _table_row_count(cursor, table: str) -> int:
    if table not in SAFE_TABLES:
        raise ValueError(f"Refusing count on unexpected table: {table}")
    cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table};")
    value = _scalar(cursor.fetchone())
    return int(value or 0)


def _column_names(cursor, table: str) -> List[str]:
    if table not in SAFE_TABLES:
        raise ValueError(f"Refusing pragma on unexpected table: {table}")
    cursor.execute(f"PRAGMA table_info({table});")
    names = []
    for row in cursor.fetchall():
        try:
            names.append(row["name"])
        except Exception:
            names.append(row[1])
    return names


def _add_column_if_missing(cursor, table: str, column: str, ddl: str):
    existing = _column_names(cursor, table)
    if column in existing:
        return
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {ddl};")
    except Exception as e:
        msg = str(e).lower()
        if "duplicate column" in msg or "already exists" in msg:
            return
        raise


def backup_database() -> Optional[str]:
    # Live data is remote Turso; there is no local sqlite file to snapshot.
    return None


def resolve_db_path() -> str:
    return "turso://popcone"


_schema_lock = threading.Lock()
_schema_ready = False


def init_db():
    """
    Additive-only startup:
    - CREATE TABLE IF NOT EXISTS (never DROP)
    - ALTER TABLE ADD COLUMN if a new field is missing
    - Seed users/settings/inventory only when those tables are empty
    Never deletes orders, items, movements, or audit rows.
    Safe to call on every Vercel cold start / request.
    """
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        _init_db_unlocked()
        _schema_ready = True


def _init_db_unlocked():
    conn = get_db()
    cursor = conn.cursor()

    # Fast path: check if database schema has already been initialized and seeded
    try:
        cursor.execute("SELECT value FROM settings WHERE key = 'bottle_price' LIMIT 1;")
        if cursor.fetchone():
            conn.close()
            return
    except Exception:
        pass

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

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        flavour TEXT PRIMARY KEY,
        current_stock INTEGER NOT NULL DEFAULT 0,
        low_stock_threshold INTEGER NOT NULL DEFAULT 10,
        updated_at TEXT NOT NULL
    );
    """)

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

    _add_column_if_missing(cursor, "orders", "discount_per_bottle", "discount_per_bottle REAL NOT NULL DEFAULT 0.0")
    _add_column_if_missing(cursor, "orders", "total_discount", "total_discount REAL NOT NULL DEFAULT 0.0")
    _add_column_if_missing(cursor, "orders", "normal_product_amount", "normal_product_amount REAL NOT NULL DEFAULT 0.0")
    _add_column_if_missing(cursor, "orders", "is_combo", "is_combo INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(cursor, "orders", "combo_type", "combo_type TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(cursor, "orders", "combo_price", "combo_price REAL NOT NULL DEFAULT 0.0")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if _table_row_count(cursor, "users") == 0:
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

    if _table_row_count(cursor, "settings") == 0:
        initial_settings = [
            ("bottle_price", "160", now_str),
            ("discount_per_bottle", "11", now_str),
            ("low_stock_threshold", "10", now_str),
        ]
        cursor.executemany(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?);",
            initial_settings,
        )
    else:
        required_defaults = [
            ("bottle_price", "160"),
            ("discount_per_bottle", "11"),
            ("low_stock_threshold", "10"),
        ]
        for key, def_val in required_defaults:
            cursor.execute("SELECT value FROM settings WHERE key = ?;", (key,))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?);",
                    (key, def_val, now_str),
                )

    if _table_row_count(cursor, "inventory") == 0:
        initial_inventory = [
            ("Tomato", 0, 10, now_str),
            ("Cheese", 0, 10, now_str),
            ("Sour Cream", 0, 10, now_str),
            ("Peri Peri", 0, 10, now_str),
        ]
        cursor.executemany(
            "INSERT INTO inventory (flavour, current_stock, low_stock_threshold, updated_at) VALUES (?, ?, ?, ?);",
            initial_inventory,
        )

    _import_local_sqlite_if_turso_orders_empty(cursor)

    order_count = _table_row_count(cursor, "orders")
    print(f"[Database] Connected to single Turso database. Live orders: {order_count}. Init is additive-only.")
    conn.close()


def _row_get(row, key, default=None):
    try:
        keys = list(row.keys())
        if key in keys:
            val = row[key]
            return default if val is None else val
    except Exception:
        pass
    return default


def _import_local_sqlite_if_turso_orders_empty(cursor):
    """
    One-way safety copy: if Turso has no orders yet but the old local popcone.db
    still has them, copy into Turso. Never deletes Turso rows. Never writes back to sqlite.
    """
    if _table_row_count(cursor, "orders") > 0:
        return
    if not os.path.exists(LOCAL_SQLITE_ARCHIVE) or os.path.getsize(LOCAL_SQLITE_ARCHIVE) == 0:
        return

    try:
        src = sqlite3.connect(LOCAL_SQLITE_ARCHIVE)
        src.row_factory = sqlite3.Row
        sc = src.cursor()
        sc.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders';")
        if not sc.fetchone():
            src.close()
            return
        sc.execute("SELECT COUNT(*) FROM orders;")
        local_orders = int(sc.fetchone()[0] or 0)
        if local_orders <= 0:
            src.close()
            return

        sc.execute("SELECT * FROM orders ORDER BY id ASC;")
        orders = sc.fetchall()
        for row in orders:
            cursor.execute(
                """
                INSERT INTO orders (
                    order_id, customer_name, phone, address, pin_code, state, district,
                    total_bottles, total_weight_grams, unit_price, product_amount,
                    delivery_fee, final_amount, payment, dispatch_state,
                    created_by, created_at, edited_by, edited_at,
                    discount_per_bottle, total_discount, normal_product_amount,
                    is_combo, combo_type, combo_price
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    row["order_id"], row["customer_name"], row["phone"], row["address"],
                    row["pin_code"], row["state"], row["district"],
                    row["total_bottles"], row["total_weight_grams"], row["unit_price"],
                    row["product_amount"], row["delivery_fee"], row["final_amount"],
                    row["payment"], row["dispatch_state"],
                    row["created_by"], row["created_at"], row["edited_by"], row["edited_at"],
                    _row_get(row, "discount_per_bottle", 0.0),
                    _row_get(row, "total_discount", 0.0),
                    _row_get(row, "normal_product_amount", 0.0),
                    _row_get(row, "is_combo", 0),
                    _row_get(row, "combo_type", ""),
                    _row_get(row, "combo_price", 0.0),
                ),
            )

        try:
            sc.execute("SELECT * FROM order_items;")
            for row in sc.fetchall():
                cursor.execute(
                    """
                    INSERT INTO order_items (order_id, flavour, quantity, unit_price, line_amount)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (row["order_id"], row["flavour"], row["quantity"], row["unit_price"], row["line_amount"]),
                )
        except Exception as e:
            print(f"[Database] Notice: could not import local order_items: {e}")

        try:
            sc.execute("SELECT * FROM inventory_movements;")
            for row in sc.fetchall():
                cursor.execute(
                    """
                    INSERT INTO inventory_movements (timestamp, flavour, movement_type, quantity, reference, created_by)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (row["timestamp"], row["flavour"], row["movement_type"], row["quantity"], row["reference"], row["created_by"]),
                )
        except Exception as e:
            print(f"[Database] Notice: could not import local inventory_movements: {e}")

        try:
            sc.execute("SELECT * FROM audit_logs;")
            for row in sc.fetchall():
                cursor.execute(
                    """
                    INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (row["timestamp"], row["user"], row["action"], row["entity_id"], row["details"]),
                )
        except Exception as e:
            print(f"[Database] Notice: could not import local audit_logs: {e}")

        try:
            sc.execute("SELECT flavour, current_stock, low_stock_threshold, updated_at FROM inventory;")
            for row in sc.fetchall():
                cursor.execute(
                    """
                    UPDATE inventory
                    SET current_stock = ?, low_stock_threshold = ?, updated_at = ?
                    WHERE flavour = ?;
                    """,
                    (row["current_stock"], row["low_stock_threshold"], row["updated_at"], row["flavour"]),
                )
        except Exception as e:
            print(f"[Database] Notice: could not import local inventory levels: {e}")

        src.close()
        print(f"[Database] One-way import: copied {local_orders} local sqlite order(s) into Turso. Local file was not deleted.")
    except Exception as e:
        print(f"[Database] Warning: local sqlite import skipped: {e}")


def reset_crm_data():
    raise RuntimeError(
        "Database wipe is permanently disabled. "
        "Orders are only removed by deleting them on the Orders page, "
        "or by an explicit SQL/AI query you run yourself."
    )


if __name__ == "__main__":
    init_db()
    print("Turso database initialized (additive only).")
