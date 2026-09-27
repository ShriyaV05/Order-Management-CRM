import os
import sqlite3
import math
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Header, Depends, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from auth import hash_password, verify_password, generate_session_token
from database import get_db, init_db
from locations import INDIA_LOCATIONS, calculate_delivery_fee

app = FastAPI(title="POPCONE Orders & Sales CRM", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Models -----------------
class LoginRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str

class OrderItemInput(BaseModel):
    flavour: str
    quantity: int

class CreateOrderRequest(BaseModel):
    customer_name: str
    phone: str
    address: str
    pin_code: str
    state: str
    district: str
    payment: str
    delivery_fee: float
    items: List[OrderItemInput]

class EditOrderRequest(BaseModel):
    customer_name: str
    phone: str
    address: str
    pin_code: str
    state: str
    district: str
    payment: str
    delivery_fee: float
    items: List[OrderItemInput]

class StockMovementRequest(BaseModel):
    flavour: str
    movement_type: str # 'Stock Added' or 'Adjustment'
    quantity: int
    reference: Optional[str] = "Manual update"

class BottlePriceRequest(BaseModel):
    bottle_price: float

class DeliveryCalcRequest(BaseModel):
    state: str
    district: str
    total_bottles: int

# ----------------- Auth Helpers -----------------
def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization token format")
    
    token = parts[1]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT s.token, s.expires_at, u.id, u.username, u.display_name, u.role
    FROM sessions s
    JOIN users u ON s.user_id = u.id
    WHERE s.token = ?;
    """, (token,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    expires_at = datetime.fromisoformat(row["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=401, detail="Session expired. Please login again.")

    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "token": row["token"]
    }

def require_admin(current_user: Dict[str, Any] = Depends(get_current_user)):
    if current_user["role"] != "ADMIN":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
    return current_user

# ----------------- Auth Routes -----------------
@app.post("/api/auth/login")
def login(req: LoginRequest):
    username = (req.username or "").strip().lower()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, display_name, role, password_hash FROM users WHERE LOWER(username) = ?;", (username,))
    user = cursor.fetchone()

    if not user or not verify_password(req.password, user["password_hash"]):
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid username or password")

    # Generate session valid for 7 days
    token = generate_session_token()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=7)

    cursor.execute("""
    INSERT INTO sessions (token, user_id, created_at, expires_at)
    VALUES (?, ?, ?, ?);
    """, (token, user["id"], now.isoformat(), expires_at.isoformat()))
    
    # Audit log
    cursor.execute("""
    INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
    VALUES (?, ?, ?, ?, ?);
    """, (now.strftime("%Y-%m-%d %H:%M:%S"), user["display_name"], "Login", user["username"], "User logged in"))
    
    conn.commit()
    conn.close()

    return {
        "success": True,
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"]
        }
    }

@app.get("/api/auth/me")
def get_me(current_user: Dict[str, Any] = Depends(get_current_user)):
    return {"user": current_user}

@app.post("/api/auth/logout")
def logout(current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE token = ?;", (current_user["token"],))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
    VALUES (?, ?, ?, ?, ?);
    """, (now, current_user["display_name"], "Logout", current_user["username"], "User logged out"))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Logged out successfully"}

@app.post("/api/auth/change-password")
def change_password(req: ChangePasswordRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    if req.new_password != req.confirm_password:
        raise HTTPException(status_code=400, detail="New password and confirm password do not match")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE id = ?;", (current_user["id"],))
    user = cursor.fetchone()

    if not user or not verify_password(req.current_password, user["password_hash"]):
        conn.close()
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    new_hash = hash_password(req.new_password)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?;", (new_hash, now, current_user["id"]))
    
    cursor.execute("""
    INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
    VALUES (?, ?, ?, ?, ?);
    """, (now, current_user["display_name"], "Password Changed", current_user["username"], "Password was updated successfully"))
    
    conn.commit()
    conn.close()
    return {"success": True, "message": "Password changed successfully"}

# ----------------- Settings Routes -----------------
@app.get("/api/settings")
def get_settings(current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings;")
    rows = cursor.fetchall()
    conn.close()
    settings = {r["key"]: r["value"] for r in rows}
    return {
        "bottle_price": float(settings.get("bottle_price", 149.0)),
        "low_stock_threshold": int(settings.get("low_stock_threshold", 20))
    }

@app.post("/api/settings/bottle-price")
def update_bottle_price(req: BottlePriceRequest, current_user: Dict[str, Any] = Depends(require_admin)):
    if req.bottle_price <= 0:
        raise HTTPException(status_code=400, detail="Bottle price must be greater than 0")
    
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("SELECT value FROM settings WHERE key = 'bottle_price';")
    old_val = cursor.fetchone()
    old_price = old_val["value"] if old_val else "149"
    
    cursor.execute("""
    INSERT INTO settings (key, value, updated_at) VALUES ('bottle_price', ?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
    """, (str(req.bottle_price), now))
    
    cursor.execute("""
    INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
    VALUES (?, ?, ?, ?, ?);
    """, (now, current_user["display_name"], "Bottle Price Changed", "bottle_price", f"Changed from Rs.{old_price} to Rs.{req.bottle_price}"))
    
    conn.commit()
    conn.close()
    return {"success": True, "bottle_price": req.bottle_price, "message": f"Bottle price updated to Rs.{req.bottle_price}"}

# ----------------- Locations & Delivery Calculation -----------------
@app.get("/api/locations")
def get_locations():
    return {"locations": INDIA_LOCATIONS}

@app.post("/api/calculate-delivery")
def calc_delivery(req: DeliveryCalcRequest):
    return calculate_delivery_fee(req.state, req.district, req.total_bottles)

# ----------------- Dashboard -----------------
@app.get("/api/dashboard/stats")
def get_dashboard_stats(current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()

    # KPI stats from valid placed orders in CRM
    cursor.execute("""
    SELECT 
        COUNT(*) as total_orders,
        COALESCE(SUM(final_amount), 0) as total_revenue,
        COALESCE(SUM(total_bottles), 0) as bottles_sold,
        SUM(CASE WHEN payment = 'Paid' THEN 1 ELSE 0 END) as paid_orders,
        SUM(CASE WHEN payment = 'COD' THEN 1 ELSE 0 END) as cod_orders
    FROM orders;
    """)
    stats_row = cursor.fetchone()
    total_orders = stats_row["total_orders"] or 0
    total_revenue = stats_row["total_revenue"] or 0.0
    bottles_sold = stats_row["bottles_sold"] or 0
    paid_orders = stats_row["paid_orders"] or 0
    cod_orders = stats_row["cod_orders"] or 0

    # Low Stock Alert (threshold = 20)
    cursor.execute("""
    SELECT flavour, current_stock, low_stock_threshold
    FROM inventory
    WHERE current_stock <= low_stock_threshold
    ORDER BY current_stock ASC;
    """)
    low_stock_rows = cursor.fetchall()
    low_stock = [{"flavour": r["flavour"], "stock": r["current_stock"]} for r in low_stock_rows]

    # Flavour Sales Breakdown
    flavours = ["Tomato", "Cheese", "Sour Cream", "Peri Peri"]
    flavour_sales = {f: 0 for f in flavours}
    cursor.execute("""
    SELECT flavour, COALESCE(SUM(quantity), 0) as total_qty
    FROM order_items
    GROUP BY flavour;
    """)
    for r in cursor.fetchall():
        if r["flavour"] in flavour_sales:
            flavour_sales[r["flavour"]] = r["total_qty"]

    # Most purchased flavour
    most_purchased = max(flavour_sales.items(), key=lambda x: x[1]) if flavour_sales else ("None", 0)

    # Recent Orders (last 5)
    cursor.execute("""
    SELECT order_id, customer_name, final_amount, payment, dispatch_state, created_at
    FROM orders
    ORDER BY created_at DESC, id DESC
    LIMIT 5;
    """)
    recent_orders = [
        {
            "order_id": r["order_id"],
            "customer": r["customer_name"],
            "amount": r["final_amount"],
            "payment": r["payment"],
            "dispatch_state": r["dispatch_state"],
            "created_at": r["created_at"]
        } for r in cursor.fetchall()
    ]

    conn.close()

    return {
        "kpis": {
            "total_revenue": total_revenue,
            "total_orders": total_orders,
            "bottles_sold": bottles_sold,
            "paid_orders": paid_orders,
            "cod_orders": cod_orders
        },
        "low_stock": low_stock,
        "flavour_sales": flavour_sales,
        "most_purchased_flavour": {
            "name": most_purchased[0],
            "bottles": most_purchased[1]
        },
        "recent_orders": recent_orders
    }

# ----------------- Orders API -----------------
@app.get("/api/orders/check-phone")
def check_phone(phone: str, exclude_order_id: Optional[str] = None):
    cleaned_phone = "".join(filter(str.isdigit, phone or ""))
    if not cleaned_phone:
        return {"exists": False}
    
    conn = get_db()
    cursor = conn.cursor()
    if exclude_order_id:
        cursor.execute("SELECT order_id FROM orders WHERE phone = ? AND order_id != ? LIMIT 1;", (cleaned_phone, exclude_order_id))
    else:
        cursor.execute("SELECT order_id FROM orders WHERE phone = ? LIMIT 1;", (cleaned_phone,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "exists": True,
            "order_id": row["order_id"],
            "message": f"This phone number is already associated with Order ID: {row['order_id']}"
        }
    return {"exists": False}

@app.get("/api/orders")
def get_orders(
    search: Optional[str] = None,
    payment: Optional[str] = "All",
    dispatch: Optional[str] = "All",
    district: Optional[str] = "All",
    date_filter: Optional[str] = "All",
    sort_by: Optional[str] = "Newest",
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    conn = get_db()
    cursor = conn.cursor()

    # Get list of all distinct districts in orders for filter dropdown
    cursor.execute("SELECT DISTINCT district FROM orders WHERE district != '' ORDER BY district ASC;")
    available_districts = [r["district"] for r in cursor.fetchall()]

    query = "SELECT * FROM orders WHERE 1=1"
    params = []

    # Search filter: Order ID, Customer Name, Phone
    if search and search.strip():
        s = f"%{search.strip()}%"
        query += " AND (order_id LIKE ? OR customer_name LIKE ? OR phone LIKE ?)"
        params.extend([s, s, s])

    # Payment filter: Paid, COD
    if payment and payment != "All":
        query += " AND payment = ?"
        params.append(payment)

    # Dispatch filter: Placed, Dispatched
    if dispatch and dispatch != "All":
        query += " AND dispatch_state = ?"
        params.append(dispatch.upper())

    # District filter
    if district and district != "All":
        query += " AND district = ?"
        params.append(district)

    # Date filter: Today, This Week, This Month, This Year, All
    now = datetime.now()
    if date_filter == "Today":
        today_str = now.strftime("%Y-%m-%d")
        query += " AND created_at >= ?"
        params.append(f"{today_str} 00:00:00")
    elif date_filter == "This Week":
        # Monday of current week
        start_of_week = now - timedelta(days=now.weekday())
        query += " AND created_at >= ?"
        params.append(f"{start_of_week.strftime('%Y-%m-%d')} 00:00:00")
    elif date_filter == "This Month":
        start_of_month = now.strftime("%Y-%m-01")
        query += " AND created_at >= ?"
        params.append(f"{start_of_month} 00:00:00")
    elif date_filter == "This Year":
        start_of_year = now.strftime("%Y-01-01")
        query += " AND created_at >= ?"
        params.append(f"{start_of_year} 00:00:00")

    # Sorting
    if sort_by == "Oldest":
        query += " ORDER BY created_at ASC, id ASC"
    elif sort_by == "Highest Amount":
        query += " ORDER BY final_amount DESC, created_at DESC"
    elif sort_by == "Customer Name":
        query += " ORDER BY customer_name ASC, created_at DESC"
    elif sort_by == "District":
        query += " ORDER BY district ASC, customer_name ASC"
    elif sort_by == "Dispatched / Placed":
        query += " ORDER BY dispatch_state DESC, created_at DESC"
    else: # "Newest"
        query += " ORDER BY created_at DESC, id DESC"

    cursor.execute(query, params)
    order_rows = cursor.fetchall()

    # Get items for all orders
    cursor.execute("SELECT order_id, flavour, quantity, unit_price, line_amount FROM order_items WHERE quantity > 0;")
    all_items = cursor.fetchall()
    items_by_order: Dict[str, List[Dict[str, Any]]] = {}
    for it in all_items:
        oid = it["order_id"]
        if oid not in items_by_order:
            items_by_order[oid] = []
        items_by_order[oid].append({
            "flavour": it["flavour"],
            "quantity": it["quantity"],
            "unit_price": it["unit_price"],
            "line_amount": it["line_amount"]
        })

    conn.close()

    orders_list = []
    for r in order_rows:
        oid = r["order_id"]
        items = items_by_order.get(oid, [])
        # Ordered flavours display: only ordered flavours (quantity > 0)
        flavours_display = ", ".join([f"{it['flavour']} x {it['quantity']}" for it in items])
        weight_str = f"{r['total_weight_grams']}g" if r['total_weight_grams'] < 1000 else f"{r['total_weight_grams']/1000:.2f}kg"

        orders_list.append({
            "order_id": r["order_id"],
            "date": r["created_at"],
            "customer": r["customer_name"],
            "phone": r["phone"],
            "district": r["district"],
            "state": r["state"],
            "address": r["address"],
            "pin_code": r["pin_code"],
            "bottles": r["total_bottles"],
            "weight": weight_str,
            "weight_grams": r["total_weight_grams"],
            "product": r["product_amount"],
            "delivery": r["delivery_fee"],
            "final": r["final_amount"],
            "payment": r["payment"],
            "dispatch": r["dispatch_state"],
            "created_by": r["created_by"],
            "created_at": r["created_at"],
            "edited_by": r["edited_by"],
            "edited_at": r["edited_at"],
            "flavours_display": flavours_display,
            "items": items
        })

    return {
        "orders": orders_list,
        "available_districts": available_districts,
        "total_count": len(orders_list)
    }

@app.post("/api/orders")
def create_order(req: CreateOrderRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    cleaned_phone = "".join(filter(str.isdigit, req.phone or ""))
    if len(cleaned_phone) < 10:
        raise HTTPException(status_code=400, detail="Please enter a valid 10-digit Indian phone number")

    conn = get_db()
    cursor = conn.cursor()

    # Rule 11: Phone number uniqueness
    cursor.execute("SELECT order_id FROM orders WHERE phone = ? LIMIT 1;", (cleaned_phone,))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail=f"This phone number is already associated with Order ID: {existing['order_id']}"
        )

    # Filter items with quantity > 0
    valid_items = [it for it in req.items if it.quantity > 0]
    total_bottles = sum(it.quantity for it in valid_items)
    if total_bottles <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Order must contain at least 1 bottle")

    # Get current bottle price from settings
    cursor.execute("SELECT value FROM settings WHERE key = 'bottle_price';")
    price_row = cursor.fetchone()
    current_bottle_price = float(price_row["value"]) if price_row else 149.0

    # Calculate weights and amounts
    total_weight_grams = total_bottles * 110
    product_amount = total_bottles * current_bottle_price
    final_amount = product_amount + float(req.delivery_fee)

    # Generate next Order ID
    cursor.execute("SELECT order_id FROM orders ORDER BY id DESC LIMIT 1;")
    last_order = cursor.fetchone()
    if last_order:
        last_id_str = last_order["order_id"]
        numeric_part = "".join(filter(str.isdigit, last_id_str))
        next_num = int(numeric_part) + 1 if numeric_part else 1
    else:
        next_num = 1
    new_order_id = f"ORD{next_num:04d}"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Transaction: Save order, items, deduct inventory, record movements, audit log
    try:
        cursor.execute("BEGIN TRANSACTION;")

        cursor.execute("""
        INSERT INTO orders (
            order_id, customer_name, phone, address, pin_code, state, district,
            total_bottles, total_weight_grams, unit_price, product_amount,
            delivery_fee, final_amount, payment, dispatch_state,
            created_by, created_at, edited_by, edited_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            new_order_id, req.customer_name.strip(), cleaned_phone, req.address.strip(),
            req.pin_code.strip(), req.state.strip(), req.district.strip(),
            total_bottles, total_weight_grams, current_bottle_price, product_amount,
            float(req.delivery_fee), final_amount, req.payment, "PLACED",
            current_user["display_name"], now_str, current_user["display_name"], now_str
        ))

        for it in valid_items:
            line_amt = it.quantity * current_bottle_price
            cursor.execute("""
            INSERT INTO order_items (order_id, flavour, quantity, unit_price, line_amount)
            VALUES (?, ?, ?, ?, ?);
            """, (new_order_id, it.flavour, it.quantity, current_bottle_price, line_amt))

            # Deduct inventory
            cursor.execute("""
            UPDATE inventory 
            SET current_stock = current_stock - ?, updated_at = ?
            WHERE flavour = ?;
            """, (it.quantity, now_str, it.flavour))

            # Record inventory movement
            cursor.execute("""
            INSERT INTO inventory_movements (timestamp, flavour, movement_type, quantity, reference, created_by)
            VALUES (?, ?, ?, ?, ?, ?);
            """, (now_str, it.flavour, "Sold", -it.quantity, new_order_id, current_user["display_name"]))

        # Audit log
        cursor.execute("""
        INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
        VALUES (?, ?, ?, ?, ?);
        """, (
            now_str, current_user["display_name"], "Order Created", new_order_id,
            f"Created {new_order_id} for {req.customer_name} ({total_bottles} bottles, Rs.{final_amount:.2f})"
        ))

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Failed to create order: {str(e)}")

    conn.close()
    return {
        "success": True,
        "order_id": new_order_id,
        "message": f"Order {new_order_id} created successfully"
    }

@app.get("/api/orders/{order_id}")
def get_order_details(order_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE order_id = ?;", (order_id,))
    order = cursor.fetchone()
    if not order:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")

    cursor.execute("SELECT flavour, quantity, unit_price, line_amount FROM order_items WHERE order_id = ? AND quantity > 0;", (order_id,))
    items = [
        {
            "flavour": r["flavour"],
            "quantity": r["quantity"],
            "unit_price": r["unit_price"],
            "line_amount": r["line_amount"]
        } for r in cursor.fetchall()
    ]

    cursor.execute("SELECT timestamp, user, action, details FROM audit_logs WHERE entity_id = ? ORDER BY id DESC;", (order_id,))
    audit_history = [
        {
            "timestamp": r["timestamp"],
            "user": r["user"],
            "action": r["action"],
            "details": r["details"]
        } for r in cursor.fetchall()
    ]
    conn.close()

    weight_str = f"{order['total_weight_grams']}g" if order['total_weight_grams'] < 1000 else f"{order['total_weight_grams']/1000:.2f}kg"

    return {
        "order": {
            "order_id": order["order_id"],
            "date": order["created_at"],
            "customer": order["customer_name"],
            "phone": order["phone"],
            "address": order["address"],
            "pin_code": order["pin_code"],
            "state": order["state"],
            "district": order["district"],
            "total_bottles": order["total_bottles"],
            "total_weight": weight_str,
            "total_weight_grams": order["total_weight_grams"],
            "unit_price": order["unit_price"],
            "product_amount": order["product_amount"],
            "delivery_fee": order["delivery_fee"],
            "final_amount": order["final_amount"],
            "payment": order["payment"],
            "dispatch_state": order["dispatch_state"],
            "created_by": order["created_by"],
            "created_at": order["created_at"],
            "edited_by": order["edited_by"],
            "edited_at": order["edited_at"],
            "items": items,
            "audit_history": audit_history
        }
    }

@app.put("/api/orders/{order_id}")
def edit_order(order_id: str, req: EditOrderRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    cleaned_phone = "".join(filter(str.isdigit, req.phone or ""))
    if len(cleaned_phone) < 10:
        raise HTTPException(status_code=400, detail="Please enter a valid 10-digit Indian phone number")

    conn = get_db()
    cursor = conn.cursor()

    # Check order exists
    cursor.execute("SELECT * FROM orders WHERE order_id = ?;", (order_id,))
    existing_order = cursor.fetchone()
    if not existing_order:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")

    # Check phone uniqueness excluding this order
    cursor.execute("SELECT order_id FROM orders WHERE phone = ? AND order_id != ? LIMIT 1;", (cleaned_phone, order_id))
    phone_conflict = cursor.fetchone()
    if phone_conflict:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail=f"This phone number is already associated with Order ID: {phone_conflict['order_id']}"
        )

    # Valid items
    new_items_dict = {it.flavour: it.quantity for it in req.items if it.quantity > 0}
    total_bottles = sum(new_items_dict.values())
    if total_bottles <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Order must contain at least 1 bottle")

    # Crucial Rule 14 & 38: Maintain historical unit price of this order
    historical_unit_price = existing_order["unit_price"]
    product_amount = total_bottles * historical_unit_price
    total_weight_grams = total_bottles * 110
    final_amount = product_amount + float(req.delivery_fee)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Get old items to calculate inventory diff
    cursor.execute("SELECT flavour, quantity FROM order_items WHERE order_id = ?;", (order_id,))
    old_items_dict = {r["flavour"]: r["quantity"] for r in cursor.fetchall()}

    try:
        cursor.execute("BEGIN TRANSACTION;")

        # Update order table (Created By NEVER changes, Edited By updates to current user)
        cursor.execute("""
        UPDATE orders
        SET customer_name = ?, phone = ?, address = ?, pin_code = ?, state = ?, district = ?,
            total_bottles = ?, total_weight_grams = ?, product_amount = ?, delivery_fee = ?,
            final_amount = ?, payment = ?, edited_by = ?, edited_at = ?
        WHERE order_id = ?;
        """, (
            req.customer_name.strip(), cleaned_phone, req.address.strip(), req.pin_code.strip(),
            req.state.strip(), req.district.strip(), total_bottles, total_weight_grams,
            product_amount, float(req.delivery_fee), final_amount, req.payment,
            current_user["display_name"], now_str, order_id
        ))

        # Adjust inventory differences
        all_flavours = set(old_items_dict.keys()).union(new_items_dict.keys())
        for flv in all_flavours:
            old_qty = old_items_dict.get(flv, 0)
            new_qty = new_items_dict.get(flv, 0)
            diff = new_qty - old_qty
            if diff != 0:
                # If diff > 0, deduct diff from stock (Change = -diff)
                # If diff < 0, restore |diff| to stock (Change = +|diff|)
                cursor.execute("""
                UPDATE inventory 
                SET current_stock = current_stock - ?, updated_at = ?
                WHERE flavour = ?;
                """, (diff, now_str, flv))

                movement_type = "Sold (Edit)" if diff > 0 else "Adjustment (Edit)"
                cursor.execute("""
                INSERT INTO inventory_movements (timestamp, flavour, movement_type, quantity, reference, created_by)
                VALUES (?, ?, ?, ?, ?, ?);
                """, (now_str, flv, movement_type, -diff, f"{order_id} Edit", current_user["display_name"]))

        # Replace order items
        cursor.execute("DELETE FROM order_items WHERE order_id = ?;", (order_id,))
        for flv, qty in new_items_dict.items():
            line_amt = qty * historical_unit_price
            cursor.execute("""
            INSERT INTO order_items (order_id, flavour, quantity, unit_price, line_amount)
            VALUES (?, ?, ?, ?, ?);
            """, (order_id, flv, qty, historical_unit_price, line_amt))

        # Audit log
        cursor.execute("""
        INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
        VALUES (?, ?, ?, ?, ?);
        """, (
            now_str, current_user["display_name"], "Order Edited", order_id,
            f"Edited {order_id} ({total_bottles} bottles, final Rs.{final_amount:.2f})"
        ))

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Failed to edit order: {str(e)}")

    conn.close()
    return {"success": True, "message": f"Order {order_id} updated successfully"}

@app.delete("/api/orders/{order_id}")
def delete_order(order_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM orders WHERE order_id = ?;", (order_id,))
    order = cursor.fetchone()
    if not order:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")

    cursor.execute("SELECT flavour, quantity FROM order_items WHERE order_id = ?;", (order_id,))
    items = cursor.fetchall()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        cursor.execute("BEGIN TRANSACTION;")

        # Rule 28 & 39: Reverse inventory impact
        for it in items:
            cursor.execute("""
            UPDATE inventory 
            SET current_stock = current_stock + ?, updated_at = ?
            WHERE flavour = ?;
            """, (it["quantity"], now_str, it["flavour"]))

            cursor.execute("""
            INSERT INTO inventory_movements (timestamp, flavour, movement_type, quantity, reference, created_by)
            VALUES (?, ?, ?, ?, ?, ?);
            """, (now_str, it["flavour"], "Order Deletion Reversal", it["quantity"], order_id, current_user["display_name"]))

        # Delete order and order_items
        cursor.execute("DELETE FROM order_items WHERE order_id = ?;", (order_id,))
        cursor.execute("DELETE FROM orders WHERE order_id = ?;", (order_id,))

        cursor.execute("""
        INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
        VALUES (?, ?, ?, ?, ?);
        """, (
            now_str, current_user["display_name"], "Order Deleted", order_id,
            f"Deleted {order_id} and restored inventory impact ({order['total_bottles']} bottles)"
        ))

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Failed to delete order: {str(e)}")

    conn.close()
    return {"success": True, "message": f"Order {order_id} deleted and stock restored"}

@app.post("/api/orders/{order_id}/dispatch")
def toggle_dispatch(order_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT dispatch_state FROM orders WHERE order_id = ?;", (order_id,))
    order = cursor.fetchone()
    if not order:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")

    # Toggle PLACED <-> DISPATCHED
    current_state = order["dispatch_state"]
    new_state = "DISPATCHED" if current_state == "PLACED" else "PLACED"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
    UPDATE orders 
    SET dispatch_state = ?, edited_by = ?, edited_at = ?
    WHERE order_id = ?;
    """, (new_state, current_user["display_name"], now_str, order_id))

    action_name = "Dispatched" if new_state == "DISPATCHED" else "Undispatched"
    cursor.execute("""
    INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
    VALUES (?, ?, ?, ?, ?);
    """, (now_str, current_user["display_name"], action_name, order_id, f"Order {order_id} changed to {new_state}"))

    conn.commit()
    conn.close()

    return {
        "success": True,
        "order_id": order_id,
        "dispatch_state": new_state,
        "edited_by": current_user["display_name"]
    }

# ----------------- Inventory API -----------------
@app.get("/api/inventory")
def get_inventory(current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT flavour, current_stock, low_stock_threshold, updated_at FROM inventory ORDER BY flavour ASC;")
    stock_rows = cursor.fetchall()

    cursor.execute("""
    SELECT timestamp, flavour, movement_type, quantity, reference, created_by 
    FROM inventory_movements 
    ORDER BY id DESC 
    LIMIT 100;
    """)
    movements = [
        {
            "when": r["timestamp"],
            "flavour": r["flavour"],
            "type": r["movement_type"],
            "change": r["quantity"],
            "reference": r["reference"],
            "created_by": r["created_by"]
        } for r in cursor.fetchall()
    ]

    conn.close()

    stocks = [
        {
            "flavour": r["flavour"],
            "current_stock": r["current_stock"],
            "low_stock_threshold": r["low_stock_threshold"],
            "is_low_stock": r["current_stock"] <= r["low_stock_threshold"],
            "updated_at": r["updated_at"]
        } for r in stock_rows
    ]

    return {
        "stocks": stocks,
        "movements": movements
    }

@app.post("/api/inventory/stock-movement")
def add_or_adjust_stock(req: StockMovementRequest, current_user: Dict[str, Any] = Depends(require_admin)):
    flavour = req.flavour.strip()
    movement_type = req.movement_type.strip()
    qty = int(req.quantity)

    if movement_type not in ["Stock Added", "Adjustment"]:
        raise HTTPException(status_code=400, detail="Invalid movement type. Must be 'Stock Added' or 'Adjustment'")

    if movement_type == "Stock Added" and qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity for 'Stock Added' must be greater than 0")

    if movement_type == "Adjustment" and qty == 0:
        raise HTTPException(status_code=400, detail="Adjustment quantity cannot be 0")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT current_stock FROM inventory WHERE flavour = ?;", (flavour,))
    curr = cursor.fetchone()
    if not curr:
        conn.close()
        raise HTTPException(status_code=404, detail="Flavour not found")

    old_stock = curr["current_stock"]
    # Both Stock Added (+qty) and Adjustment (+/- qty) add the signed integer directly to stock
    new_stock = old_stock + qty
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        cursor.execute("BEGIN TRANSACTION;")

        cursor.execute("UPDATE inventory SET current_stock = ?, updated_at = ? WHERE flavour = ?;", (new_stock, now_str, flavour))
        cursor.execute("""
        INSERT INTO inventory_movements (timestamp, flavour, movement_type, quantity, reference, created_by)
        VALUES (?, ?, ?, ?, ?, ?);
        """, (now_str, flavour, movement_type, qty, req.reference or "Manual adjustment", current_user["display_name"]))

        cursor.execute("""
        INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
        VALUES (?, ?, ?, ?, ?);
        """, (
            now_str, current_user["display_name"], f"Inventory {movement_type}", flavour,
            f"{flavour} stock changed by {qty:+d} ({old_stock} -> {new_stock})"
        ))

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Failed to update stock: {str(e)}")

    conn.close()
    return {
        "success": True,
        "flavour": flavour,
        "old_stock": old_stock,
        "new_stock": new_stock,
        "message": f"Successfully updated {flavour} stock to {new_stock}"
    }

@app.post("/api/inventory/reset")
def reset_inventory(current_user: Dict[str, Any] = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT flavour, current_stock FROM inventory;")
    all_stocks = cursor.fetchall()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        cursor.execute("BEGIN TRANSACTION;")

        for row in all_stocks:
            flv = row["flavour"]
            old_qty = row["current_stock"]
            cursor.execute("UPDATE inventory SET current_stock = 0, updated_at = ? WHERE flavour = ?;", (now_str, flv))
            cursor.execute("""
            INSERT INTO inventory_movements (timestamp, flavour, movement_type, quantity, reference, created_by)
            VALUES (?, ?, ?, ?, ?, ?);
            """, (now_str, flv, "Reset Stock", -old_qty, "Reset to 0", current_user["display_name"]))

        cursor.execute("""
        INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
        VALUES (?, ?, ?, ?, ?);
        """, (now_str, current_user["display_name"], "Inventory Reset", "All Flavours", "All flavour stock quantities reset to 0"))

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Failed to reset inventory: {str(e)}")

    conn.close()
    return {"success": True, "message": "All flavour stock quantities set to 0"}

# ----------------- Analytics API -----------------
@app.get("/api/analytics")
def get_analytics(year: Optional[int] = None, current_user: Dict[str, Any] = Depends(get_current_user)):
    target_year = year or datetime.now().year

    conn = get_db()
    cursor = conn.cursor()

    # All available years in order history
    cursor.execute("SELECT DISTINCT strftime('%Y', created_at) as yr FROM orders ORDER BY yr DESC;")
    available_years = [int(r["yr"]) for r in cursor.fetchall() if r["yr"]]
    if target_year not in available_years:
        available_years.insert(0, target_year)
    available_years.sort(reverse=True)

    # 1. Total Overview for selected year
    cursor.execute("""
    SELECT 
        COUNT(*) as total_orders,
        COALESCE(SUM(total_bottles), 0) as total_bottles,
        COALESCE(SUM(product_amount), 0) as total_revenue
    FROM orders
    WHERE strftime('%Y', created_at) = ?;
    """, (str(target_year),))
    overview_row = cursor.fetchone()
    year_total_orders = overview_row["total_orders"] or 0
    year_total_bottles = overview_row["total_bottles"] or 0
    year_total_revenue = overview_row["total_revenue"] or 0.0

    # 2. Flavour Breakdown for selected year
    flavours = ["Tomato", "Cheese", "Sour Cream", "Peri Peri"]
    flavour_stats = {f: {"bottles": 0, "revenue": 0.0} for f in flavours}

    cursor.execute("""
    SELECT oi.flavour, SUM(oi.quantity) as bottles, SUM(oi.line_amount) as revenue
    FROM order_items oi
    JOIN orders o ON oi.order_id = o.order_id
    WHERE strftime('%Y', o.created_at) = ?
    GROUP BY oi.flavour;
    """, (str(target_year),))
    for r in cursor.fetchall():
        if r["flavour"] in flavour_stats:
            flavour_stats[r["flavour"]]["bottles"] = r["bottles"] or 0
            flavour_stats[r["flavour"]]["revenue"] = r["revenue"] or 0.0

    most_purchased = max(flavour_stats.items(), key=lambda x: x[1]["bottles"]) if flavour_stats else ("None", {"bottles": 0, "revenue": 0.0})

    # 3. Monthly Report (All 12 months: Jan to Dec)
    months_labels = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    monthly_data = []

    for month_idx in range(1, 13):
        m_str = f"{month_idx:02d}"
        month_label = months_labels[month_idx - 1]

        cursor.execute("""
        SELECT 
            oi.flavour,
            COALESCE(SUM(oi.quantity), 0) as qty,
            COALESCE(SUM(oi.line_amount), 0) as rev
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.order_id
        WHERE strftime('%Y', o.created_at) = ? AND strftime('%m', o.created_at) = ?
        GROUP BY oi.flavour;
        """, (str(target_year), m_str))

        month_flavour_map = {f: 0 for f in flavours}
        month_revenue = 0.0
        month_total_bottles = 0

        for r in cursor.fetchall():
            flv = r["flavour"]
            if flv in month_flavour_map:
                month_flavour_map[flv] = r["qty"]
            month_revenue += r["rev"]
            month_total_bottles += r["qty"]

        # Most purchased flavour of this month
        m_most = max(month_flavour_map.items(), key=lambda x: x[1]) if any(month_flavour_map.values()) else ("-", 0)

        monthly_data.append({
            "month_num": month_idx,
            "month_name": month_label,
            "tomato": month_flavour_map["Tomato"],
            "cheese": month_flavour_map["Cheese"],
            "sour_cream": month_flavour_map["Sour Cream"],
            "peri_peri": month_flavour_map["Peri Peri"],
            "total_bottles": month_total_bottles,
            "revenue": month_revenue,
            "most_purchased_flavour": m_most[0] if m_most[1] > 0 else "None"
        })

    # 4. Weekly Report for the selected year
    cursor.execute("""
    SELECT 
        strftime('%W', o.created_at) as week_num,
        MIN(strftime('%Y-%m-%d', o.created_at)) as week_start,
        oi.flavour,
        SUM(oi.quantity) as qty,
        SUM(oi.line_amount) as rev
    FROM order_items oi
    JOIN orders o ON oi.order_id = o.order_id
    WHERE strftime('%Y', o.created_at) = ?
    GROUP BY week_num, oi.flavour
    ORDER BY CAST(week_num AS INTEGER) ASC;
    """, (str(target_year),))
    weekly_rows = cursor.fetchall()

    weekly_dict = {}
    for r in weekly_rows:
        wn = int(r["week_num"] or 0)
        if wn not in weekly_dict:
            weekly_dict[wn] = {
                "week_num": wn,
                "week_label": f"Week {wn + 1} ({r['week_start']})",
                "tomato": 0,
                "cheese": 0,
                "sour_cream": 0,
                "peri_peri": 0,
                "total_bottles": 0,
                "revenue": 0.0
            }
        flv = r["flavour"]
        qty = r["qty"] or 0
        rev = r["rev"] or 0.0
        weekly_dict[wn]["total_bottles"] += qty
        weekly_dict[wn]["revenue"] += rev
        if flv == "Tomato":
            weekly_dict[wn]["tomato"] += qty
        elif flv == "Cheese":
            weekly_dict[wn]["cheese"] += qty
        elif flv == "Sour Cream":
            weekly_dict[wn]["sour_cream"] += qty
        elif flv == "Peri Peri":
            weekly_dict[wn]["peri_peri"] += qty

    weekly_data = []
    for wn in sorted(weekly_dict.keys()):
        w = weekly_dict[wn]
        f_counts = {
            "Tomato": w["tomato"],
            "Cheese": w["cheese"],
            "Sour Cream": w["sour_cream"],
            "Peri Peri": w["peri_peri"]
        }
        w_most = max(f_counts.items(), key=lambda x: x[1]) if any(f_counts.values()) else ("-", 0)
        w["most_purchased_flavour"] = w_most[0] if w_most[1] > 0 else "None"
        weekly_data.append(w)

    # 5. Annual Report (All months of target year combined)
    annual_data = {
        "year": target_year,
        "total_bottles": year_total_bottles,
        "total_revenue": year_total_revenue,
        "tomato_bottles": flavour_stats["Tomato"]["bottles"],
        "tomato_revenue": flavour_stats["Tomato"]["revenue"],
        "cheese_bottles": flavour_stats["Cheese"]["bottles"],
        "cheese_revenue": flavour_stats["Cheese"]["revenue"],
        "sour_cream_bottles": flavour_stats["Sour Cream"]["bottles"],
        "sour_cream_revenue": flavour_stats["Sour Cream"]["revenue"],
        "peri_peri_bottles": flavour_stats["Peri Peri"]["bottles"],
        "peri_peri_revenue": flavour_stats["Peri Peri"]["revenue"],
        "most_purchased_flavour": most_purchased[0] if most_purchased[1]["bottles"] > 0 else "None"
    }

    conn.close()

    return {
        "selected_year": target_year,
        "available_years": available_years,
        "overview": {
            "total_orders": year_total_orders,
            "total_bottles": year_total_bottles,
            "total_revenue": year_total_revenue,
            "most_purchased_flavour": most_purchased[0] if most_purchased[1]["bottles"] > 0 else "None",
            "most_purchased_bottles": most_purchased[1]["bottles"],
            "flavour_breakdown": flavour_stats
        },
        "weekly_report": weekly_data,
        "monthly_report": monthly_data,
        "annual_report": annual_data
    }

# ----------------- Static Files & Frontend -----------------
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Directly serve logo.jpg from workspace or static/assets
@app.get("/logo.jpg")
def serve_logo():
    logo_path = os.path.join(os.path.dirname(__file__), "logo.jpg")
    if os.path.exists(logo_path):
        return FileResponse(logo_path, media_type="image/jpeg")
    return FileResponse(os.path.join(STATIC_DIR, "assets", "logo.jpg"), media_type="image/jpeg")

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.on_event("startup")
def startup_event():
    init_db()

if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))
    reload = os.environ.get("ENV", "development").lower() == "development"
    uvicorn.run("server:app", host=host, port=port, reload=reload)
