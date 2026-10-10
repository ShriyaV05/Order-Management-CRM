import os
import sqlite3
import math
import urllib.request
import json
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

# Constant original bottle price (Requirement 2: Fixed at ₹160)
ORIGINAL_BOTTLE_PRICE = 160.0

# ----------------- Models -----------------
class LoginRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str

class AdminUserPasswordRequest(BaseModel):
    user_id: Optional[int] = None
    username: Optional[str] = None
    new_password: str

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
    delivery_fee: Optional[float] = 0.0
    apply_combo: Optional[bool] = False
    items: List[OrderItemInput]

class EditOrderRequest(BaseModel):
    customer_name: str
    phone: str
    address: str
    pin_code: str
    state: str
    district: str
    payment: str
    delivery_fee: Optional[float] = 0.0
    apply_combo: Optional[bool] = False
    items: List[OrderItemInput]

class StockMovementRequest(BaseModel):
    flavour: str
    movement_type: str # 'Stock Added' or 'Adjustment'
    quantity: int
    reference: Optional[str] = "Manual update"

class BottlePriceRequest(BaseModel):
    bottle_price: float

class DiscountRequest(BaseModel):
    discount_per_bottle: float

class DeliveryCalcRequest(BaseModel):
    state: str
    district: str
    total_bottles: int
    product_amount: Optional[float] = None

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
    cursor.execute("""
    SELECT id, username, display_name, role, password_hash 
    FROM users 
    WHERE LOWER(username) = ? 
       OR LOWER(display_name) = ? 
       OR LOWER(username) = ?;
    """, (username, username, f"{username}@popcone" if "@" not in username else username))
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
    # Requirement 12: Members must not be allowed to change their own passwords. Only Ashish (ADMIN) may manage passwords.
    raise HTTPException(status_code=403, detail="Forbidden: User password changes are restricted to administrator (Ashish) via Settings.")

@app.get("/api/users")
def get_users(current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, display_name, role FROM users ORDER BY id ASC;")
    rows = cursor.fetchall()
    conn.close()
    return {
        "users": [
            {
                "id": r["id"],
                "username": r["username"],
                "display_name": r["display_name"],
                "role": r["role"]
            } for r in rows
        ]
    }

# ----------------- Settings Routes -----------------
@app.get("/api/settings")
def get_settings(current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings;")
    rows = cursor.fetchall()
    conn.close()
    settings = {r["key"]: r["value"] for r in rows}
    discount = float(settings.get("discount_per_bottle", 11.0))
    return {
        "original_bottle_price": ORIGINAL_BOTTLE_PRICE,
        "bottle_price": ORIGINAL_BOTTLE_PRICE,
        "discount_per_bottle": discount,
        "effective_bottle_price": ORIGINAL_BOTTLE_PRICE - discount,
        "low_stock_threshold": int(settings.get("low_stock_threshold", 20))
    }

@app.post("/api/settings/discount")
def update_discount(req: DiscountRequest, current_user: Dict[str, Any] = Depends(require_admin)):
    # Requirement 3: Only admin (Ashish) may change discount per bottle. Validate discount.
    if req.discount_per_bottle < 0:
        raise HTTPException(status_code=400, detail="Discount per bottle cannot be negative")
    if req.discount_per_bottle >= ORIGINAL_BOTTLE_PRICE:
        raise HTTPException(status_code=400, detail=f"Discount per bottle must be less than original bottle price (Rs.{ORIGINAL_BOTTLE_PRICE:.0f})")
    
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("SELECT value FROM settings WHERE key = 'discount_per_bottle';")
    old_val = cursor.fetchone()
    old_disc = old_val["value"] if old_val else "11"

    cursor.execute("""
    INSERT INTO settings (key, value, updated_at) VALUES ('discount_per_bottle', ?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
    """, (str(req.discount_per_bottle), now))

    effective_price = ORIGINAL_BOTTLE_PRICE - req.discount_per_bottle
    cursor.execute("""
    INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
    VALUES (?, ?, ?, ?, ?);
    """, (now, current_user["display_name"], "Discount Per Bottle Changed", "discount_per_bottle", f"Changed from Rs.{old_disc} to Rs.{req.discount_per_bottle} per bottle (Effective price: Rs.{effective_price:.2f})"))

    conn.commit()
    conn.close()
    return {
        "success": True,
        "discount_per_bottle": req.discount_per_bottle,
        "effective_bottle_price": effective_price,
        "message": f"Discount updated to Rs.{req.discount_per_bottle} per bottle (Effective price: Rs.{effective_price:.2f})"
    }

@app.post("/api/settings/bottle-price")
def update_bottle_price(req: BottlePriceRequest, current_user: Dict[str, Any] = Depends(require_admin)):
    # Requirement 2: Original bottle price is fixed at Rs.160. Users must not be able to modify this original price.
    raise HTTPException(status_code=400, detail="Original selling price is fixed at Rs.160 per bottle and cannot be modified.")

@app.post("/api/settings/user-password")
def admin_set_user_password(req: AdminUserPasswordRequest, current_user: Dict[str, Any] = Depends(require_admin)):
    # Requirement 12: Admin password management for any of the 5 user accounts
    new_pwd = (req.new_password or "").strip()
    if len(new_pwd) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    
    conn = get_db()
    cursor = conn.cursor()

    if req.user_id:
        cursor.execute("SELECT id, username, display_name FROM users WHERE id = ?;", (req.user_id,))
    elif req.username:
        u = req.username.strip().lower()
        cursor.execute("SELECT id, username, display_name FROM users WHERE LOWER(username) = ? OR LOWER(display_name) = ?;", (u, u))
    else:
        conn.close()
        raise HTTPException(status_code=400, detail="Please select a user account to update password")

    target_user = cursor.fetchone()
    if not target_user:
        conn.close()
        raise HTTPException(status_code=404, detail="Selected user account not found")

    new_hash = hash_password(new_pwd)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Update password hash in database
    cursor.execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?;", (new_hash, now, target_user["id"]))
    # Invalidate active sessions for that user so old password stops working immediately
    cursor.execute("DELETE FROM sessions WHERE user_id = ?;", (target_user["id"],))

    cursor.execute("""
    INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
    VALUES (?, ?, ?, ?, ?);
    """, (now, current_user["display_name"], "Admin Set User Password", target_user["username"], f"Admin changed password for {target_user['display_name']} ({target_user['username']})"))

    conn.commit()
    conn.close()
    return {
        "success": True,
        "message": f"Password for {target_user['display_name']} updated successfully. New password is active immediately."
    }

# ----------------- Locations, Postal PIN Lookup & Delivery -----------------
@app.get("/api/locations")
def get_locations():
    return {"locations": INDIA_LOCATIONS}

@app.get("/api/pincode/{pincode}")
def lookup_pincode(pincode: str):
    # Requirement 9: Automatic District and State lookup using PIN code via India Post API
    cleaned_pin = "".join(filter(str.isdigit, pincode or ""))
    if len(cleaned_pin) != 6:
        raise HTTPException(status_code=400, detail="Please enter a valid 6-digit Indian PIN code")

    url = f"https://api.postalpincode.in/pincode/{cleaned_pin}"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) POPCONE-CRM/1.0",
                "Origin": "http://localhost:8000"
            }
        )
        with urllib.request.urlopen(req, timeout=6) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
            if isinstance(data, list) and len(data) > 0:
                entry = data[0]
                if entry.get("Status") == "Success" and entry.get("PostOffice"):
                    post_offices = entry["PostOffice"]
                    district = (post_offices[0].get("District") or "").strip()
                    state = (post_offices[0].get("State") or "").strip()
                    office_names = [p.get("Name") for p in post_offices[:6] if p.get("Name")]
                    return {
                        "success": True,
                        "status": "success",
                        "pincode": cleaned_pin,
                        "state": state,
                        "district": district,
                        "post_offices": office_names
                    }
        return {
            "success": False,
            "status": "error",
            "message": "No matching postal records found for this PIN code. Please select District and State manually."
        }
    except Exception as e:
        return {
            "success": False,
            "status": "error",
            "message": f"Postal lookup service unavailable ({str(e)}). Manual entry enabled."
        }

@app.post("/api/calculate-delivery")
def calc_delivery(req: DeliveryCalcRequest):
    return calculate_delivery_fee(req.state, req.district, req.total_bottles, req.product_amount)

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
    has_sales = any(qty > 0 for qty in flavour_sales.values())
    if has_sales:
        most_purchased = max(flavour_sales.items(), key=lambda x: x[1])
    else:
        most_purchased = ("None", 0)

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
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
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

    # Date filter: Today, Yesterday, This Week, This Month, This Year, All
    now = datetime.now()
    if date_filter == "Today":
        today_str = now.strftime("%Y-%m-%d")
        query += " AND created_at >= ?"
        params.append(f"{today_str} 00:00:00")
    elif date_filter == "Yesterday":
        yest_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        query += " AND created_at >= ? AND created_at <= ?"
        params.append(f"{yest_str} 00:00:00")
        params.append(f"{yest_str} 23:59:59")
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

    # Custom From/To Date Filter
    if date_from and date_from.strip():
        query += " AND created_at >= ?"
        params.append(f"{date_from.strip()} 00:00:00")
    if date_to and date_to.strip():
        query += " AND created_at <= ?"
        params.append(f"{date_to.strip()} 23:59:59")

    # Sorting
    if sort_by in ["Oldest", "oldest"]:
        query += " ORDER BY created_at ASC, id ASC"
    elif sort_by in ["Highest Amount", "AmountHigh"]:
        query += " ORDER BY final_amount DESC, created_at DESC"
    elif sort_by in ["Lowest Amount", "AmountLow"]:
        query += " ORDER BY final_amount ASC, created_at DESC"
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
        flavours_display = ", ".join([f"{it['flavour']} x {it['quantity']}" for it in items])
        weight_str = f"{r['total_weight_grams']}g" if r['total_weight_grams'] < 1000 else (f"{r['total_weight_grams']//1000}kg" if r['total_weight_grams'] % 1000 == 0 else f"{r['total_weight_grams']/1000:.2f}kg")

        # Safely extract pricing fields with fallback for legacy records
        discount_per_bottle = float(r["discount_per_bottle"]) if "discount_per_bottle" in r.keys() and r["discount_per_bottle"] is not None else 0.0
        total_discount = float(r["total_discount"]) if "total_discount" in r.keys() and r["total_discount"] is not None else 0.0
        normal_product_amount = float(r["normal_product_amount"]) if "normal_product_amount" in r.keys() and r["normal_product_amount"] is not None and r["normal_product_amount"] > 0 else float(r["product_amount"])
        is_combo = bool(r["is_combo"]) if "is_combo" in r.keys() and r["is_combo"] is not None else False
        combo_type = str(r["combo_type"] or "") if "combo_type" in r.keys() else ""
        combo_price = float(r["combo_price"]) if "combo_price" in r.keys() and r["combo_price"] is not None else 0.0

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
            "unit_price": r["unit_price"],
            "discount_per_bottle": discount_per_bottle,
            "total_discount": total_discount,
            "normal_product_amount": normal_product_amount,
            "is_combo": is_combo,
            "combo_type": combo_type,
            "combo_price": combo_price,
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

    # Rule: Phone number uniqueness
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

    # Requirement 5: Bottle Weight = 100 grams
    total_weight_grams = total_bottles * 100

    # Requirement 2: Original Unit Price is fixed at Rs.160
    original_unit_price = ORIGINAL_BOTTLE_PRICE

    # Requirement 3: Configured Discount per Bottle from Settings
    cursor.execute("SELECT value FROM settings WHERE key = 'discount_per_bottle';")
    disc_row = cursor.fetchone()
    discount_per_bottle = float(disc_row["value"]) if disc_row else 11.0

    # Financial formulas:
    # Original Product Amount = Total Bottle Quantity * Rs.160
    # Total Discount = Total Bottle Quantity * Discount Per Bottle
    # Discounted Product Amount = Original Product Amount - Total Discount
    original_product_amount = total_bottles * original_unit_price
    total_discount = total_bottles * discount_per_bottle
    normal_product_amount = original_product_amount - total_discount

    # Requirement 4: Optional Combo Offers
    # Combo A: Exactly 2 bottles for Rs.289
    # Combo B: Exactly 4 bottles for Rs.559
    is_combo = 0
    combo_type = ""
    combo_price = 0.0

    if req.apply_combo and total_bottles == 2:
        is_combo = 1
        combo_type = "2_BOTTLE"
        combo_price = 289.0
        applicable_product_amount = 289.0
    elif req.apply_combo and total_bottles == 4:
        is_combo = 1
        combo_type = "4_BOTTLE"
        combo_price = 559.0
        applicable_product_amount = 559.0
    else:
        applicable_product_amount = normal_product_amount

    # Requirement 8: Free Delivery if applicable product amount strictly exceeds Rs.800
    if applicable_product_amount > 800.0:
        delivery_fee = 0.0
    else:
        calc = calculate_delivery_fee(req.state, req.district, total_bottles, applicable_product_amount)
        # Preserve legitimate manual delivery fee override if provided and applicable_product_amount <= 800
        delivery_fee = float(req.delivery_fee) if req.delivery_fee is not None else calc["fee"]

    final_amount = applicable_product_amount + delivery_fee

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
            created_by, created_at, edited_by, edited_at,
            discount_per_bottle, total_discount, normal_product_amount,
            is_combo, combo_type, combo_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            new_order_id, req.customer_name.strip(), cleaned_phone, req.address.strip(),
            req.pin_code.strip(), req.state.strip(), req.district.strip(),
            total_bottles, total_weight_grams, original_unit_price, applicable_product_amount,
            delivery_fee, final_amount, req.payment, "PLACED",
            current_user["display_name"], now_str, current_user["display_name"], now_str,
            discount_per_bottle, total_discount, normal_product_amount,
            is_combo, combo_type, combo_price
        ))

        for it in valid_items:
            # Calculate item line share
            line_amt = (applicable_product_amount / total_bottles) * it.quantity
            cursor.execute("""
            INSERT INTO order_items (order_id, flavour, quantity, unit_price, line_amount)
            VALUES (?, ?, ?, ?, ?);
            """, (new_order_id, it.flavour, it.quantity, original_unit_price, line_amt))

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
            """, (now_str, it.flavour, "Sold", -it.quantity, new_order_id, "System"))

        # Audit log
        combo_note = f" (Combo: {combo_type})" if is_combo else ""
        cursor.execute("""
        INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
        VALUES (?, ?, ?, ?, ?);
        """, (
            now_str, current_user["display_name"], "Order Created", new_order_id,
            f"Created {new_order_id} for {req.customer_name} ({total_bottles} bottles, Product: Rs.{applicable_product_amount:.2f}, Delivery: Rs.{delivery_fee:.2f}, Final: Rs.{final_amount:.2f}){combo_note}"
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
        "product_amount": applicable_product_amount,
        "applicable_product_amount": applicable_product_amount,
        "delivery_fee": delivery_fee,
        "final_amount": final_amount,
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

    total_w = order['total_weight_grams']
    weight_str = f"{total_w}g" if total_w < 1000 else (f"{total_w // 1000}kg" if total_w % 1000 == 0 else f"{total_w / 1000:.2f}kg")

    discount_per_bottle = float(order["discount_per_bottle"]) if "discount_per_bottle" in order.keys() and order["discount_per_bottle"] is not None else 0.0
    total_discount = float(order["total_discount"]) if "total_discount" in order.keys() and order["total_discount"] is not None else 0.0
    normal_product_amount = float(order["normal_product_amount"]) if "normal_product_amount" in order.keys() and order["normal_product_amount"] is not None and order["normal_product_amount"] > 0 else float(order["product_amount"])
    is_combo = bool(order["is_combo"]) if "is_combo" in order.keys() and order["is_combo"] is not None else False
    combo_type = str(order["combo_type"] or "") if "combo_type" in order.keys() else ""
    combo_price = float(order["combo_price"]) if "combo_price" in order.keys() and order["combo_price"] is not None else 0.0

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
            "discount_per_bottle": discount_per_bottle,
            "total_discount": total_discount,
            "normal_product_amount": normal_product_amount,
            "is_combo": is_combo,
            "combo_type": combo_type,
            "combo_price": combo_price,
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

    # Requirement 5: Bottle Weight = 100 grams
    total_weight_grams = total_bottles * 100

    # Historical pricing preservation
    historical_unit_price = existing_order["unit_price"]
    historical_discount = float(existing_order["discount_per_bottle"]) if "discount_per_bottle" in existing_order.keys() and existing_order["discount_per_bottle"] is not None else 0.0

    original_product_amount = total_bottles * historical_unit_price
    total_discount = total_bottles * historical_discount
    normal_product_amount = original_product_amount - total_discount

    # Combo handling
    is_combo = 0
    combo_type = ""
    combo_price = 0.0

    if req.apply_combo and total_bottles == 2:
        is_combo = 1
        combo_type = "2_BOTTLE"
        combo_price = 289.0
        applicable_product_amount = 289.0
    elif req.apply_combo and total_bottles == 4:
        is_combo = 1
        combo_type = "4_BOTTLE"
        combo_price = 559.0
        applicable_product_amount = 559.0
    else:
        applicable_product_amount = normal_product_amount

    # Free delivery rule (> Rs.800)
    if applicable_product_amount > 800.0:
        delivery_fee = 0.0
    else:
        calc = calculate_delivery_fee(req.state, req.district, total_bottles, applicable_product_amount)
        delivery_fee = float(req.delivery_fee) if req.delivery_fee is not None else calc["fee"]

    final_amount = applicable_product_amount + delivery_fee

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Get old items to calculate inventory diff
    cursor.execute("SELECT flavour, quantity FROM order_items WHERE order_id = ?;", (order_id,))
    old_items_dict = {r["flavour"]: r["quantity"] for r in cursor.fetchall()}

    try:
        cursor.execute("BEGIN TRANSACTION;")

        cursor.execute("""
        UPDATE orders
        SET customer_name = ?, phone = ?, address = ?, pin_code = ?, state = ?, district = ?,
            total_bottles = ?, total_weight_grams = ?, product_amount = ?, delivery_fee = ?,
            final_amount = ?, payment = ?, edited_by = ?, edited_at = ?,
            discount_per_bottle = ?, total_discount = ?, normal_product_amount = ?,
            is_combo = ?, combo_type = ?, combo_price = ?
        WHERE order_id = ?;
        """, (
            req.customer_name.strip(), cleaned_phone, req.address.strip(), req.pin_code.strip(),
            req.state.strip(), req.district.strip(), total_bottles, total_weight_grams,
            applicable_product_amount, delivery_fee, final_amount, req.payment,
            current_user["display_name"], now_str,
            historical_discount, total_discount, normal_product_amount,
            is_combo, combo_type, combo_price,
            order_id
        ))

        # Adjust inventory differences
        all_flavours = set(old_items_dict.keys()).union(new_items_dict.keys())
        for flv in all_flavours:
            old_qty = old_items_dict.get(flv, 0)
            new_qty = new_items_dict.get(flv, 0)
            diff = new_qty - old_qty
            if diff != 0:
                cursor.execute("""
                UPDATE inventory 
                SET current_stock = current_stock - ?, updated_at = ?
                WHERE flavour = ?;
                """, (diff, now_str, flv))

                movement_type = "Sold (Edit)" if diff > 0 else "Adjustment (Edit)"
                cursor.execute("""
                INSERT INTO inventory_movements (timestamp, flavour, movement_type, quantity, reference, created_by)
                VALUES (?, ?, ?, ?, ?, ?);
                """, (now_str, flv, movement_type, -diff, f"{order_id} Edit", "System"))

        # Replace order items
        cursor.execute("DELETE FROM order_items WHERE order_id = ?;", (order_id,))
        for flv, qty in new_items_dict.items():
            line_amt = (applicable_product_amount / total_bottles) * qty
            cursor.execute("""
            INSERT INTO order_items (order_id, flavour, quantity, unit_price, line_amount)
            VALUES (?, ?, ?, ?, ?);
            """, (order_id, flv, qty, historical_unit_price, line_amt))

        # Audit log
        combo_note = f" (Combo: {combo_type})" if is_combo else ""
        cursor.execute("""
        INSERT INTO audit_logs (timestamp, user, action, entity_id, details)
        VALUES (?, ?, ?, ?, ?);
        """, (
            now_str, current_user["display_name"], "Order Edited", order_id,
            f"Edited {order_id} ({total_bottles} bottles, Product: Rs.{applicable_product_amount:.2f}, Delivery: Rs.{delivery_fee:.2f}, Final: Rs.{final_amount:.2f}){combo_note}"
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
            """, (now_str, it["flavour"], "Order Deletion Reversal", it["quantity"], order_id, "System"))

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
def get_analytics(year: Optional[int] = None, month: Optional[int] = None, current_user: Dict[str, Any] = Depends(get_current_user)):
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

    has_sales = any(s["bottles"] > 0 for s in flavour_stats.values())
    most_purchased = max(flavour_stats.items(), key=lambda x: x[1]["bottles"]) if has_sales else ("None", {"bottles": 0, "revenue": 0.0})

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
        month_rev_map = {f: 0.0 for f in flavours}
        month_revenue = 0.0
        month_total_bottles = 0

        for r in cursor.fetchall():
            flv = r["flavour"]
            if flv in month_flavour_map:
                month_flavour_map[flv] = r["qty"]
                month_rev_map[flv] = r["rev"]
            month_revenue += r["rev"]
            month_total_bottles += r["qty"]

        # Count orders in this month
        cursor.execute("""
        SELECT COUNT(*) as month_orders
        FROM orders
        WHERE strftime('%Y', created_at) = ? AND strftime('%m', created_at) = ?;
        """, (str(target_year), m_str))
        m_orders_row = cursor.fetchone()
        month_orders_count = m_orders_row["month_orders"] if m_orders_row else 0

        # Most purchased flavour of this month
        has_m_sales = any(month_flavour_map.values())
        m_most = max(month_flavour_map.items(), key=lambda x: x[1]) if has_m_sales else ("None", 0)

        monthly_data.append({
            "month_num": month_idx,
            "month_name": month_label,
            "total_orders": month_orders_count,
            "tomato": month_flavour_map["Tomato"],
            "tomato_revenue": month_rev_map["Tomato"],
            "cheese": month_flavour_map["Cheese"],
            "cheese_revenue": month_rev_map["Cheese"],
            "sour_cream": month_flavour_map["Sour Cream"],
            "sour_cream_revenue": month_rev_map["Sour Cream"],
            "peri_peri": month_flavour_map["Peri Peri"],
            "peri_peri_revenue": month_rev_map["Peri Peri"],
            "total_bottles": month_total_bottles,
            "revenue": month_revenue,
            "most_purchased_flavour": m_most[0] if m_most[1] > 0 else "None"
        })

    # Specific month overview if month is requested
    selected_month_data = None
    if month and 1 <= month <= 12:
        selected_month_data = monthly_data[month - 1]

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
                "tomato": 0, "tomato_revenue": 0.0,
                "cheese": 0, "cheese_revenue": 0.0,
                "sour_cream": 0, "sour_cream_revenue": 0.0,
                "peri_peri": 0, "peri_peri_revenue": 0.0,
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
            weekly_dict[wn]["tomato_revenue"] += rev
        elif flv == "Cheese":
            weekly_dict[wn]["cheese"] += qty
            weekly_dict[wn]["cheese_revenue"] += rev
        elif flv == "Sour Cream":
            weekly_dict[wn]["sour_cream"] += qty
            weekly_dict[wn]["sour_cream_revenue"] += rev
        elif flv == "Peri Peri":
            weekly_dict[wn]["peri_peri"] += qty
            weekly_dict[wn]["peri_peri_revenue"] += rev

    weekly_data = []
    for wn in sorted(weekly_dict.keys()):
        w = weekly_dict[wn]
        f_counts = {
            "Tomato": w["tomato"],
            "Cheese": w["cheese"],
            "Sour Cream": w["sour_cream"],
            "Peri Peri": w["peri_peri"]
        }
        w_most = max(f_counts.items(), key=lambda x: x[1]) if any(f_counts.values()) else ("None", 0)
        w["most_purchased_flavour"] = w_most[0] if w_most[1] > 0 else "None"
        weekly_data.append(w)

    # 5. Annual Report (All months of target year combined)
    annual_data = {
        "year": target_year,
        "total_orders": year_total_orders,
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
        "selected_month": month,
        "selected_month_data": selected_month_data,
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

# Directly serve favicon.ico using logo.jpg
@app.get("/favicon.ico")
def serve_favicon():
    logo_path = os.path.join(os.path.dirname(__file__), "logo.jpg")
    if os.path.exists(logo_path):
        return FileResponse(logo_path, media_type="image/jpeg")
    return FileResponse(os.path.join(STATIC_DIR, "assets", "logo.jpg"), media_type="image/jpeg")

# Directly serve icon.png from workspace or static/assets
@app.get("/icon.png")
def serve_icon():
    icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
    if os.path.exists(icon_path):
        return FileResponse(icon_path, media_type="image/png")
    return FileResponse(os.path.join(STATIC_DIR, "assets", "icon.png"), media_type="image/png")

@app.api_route("/", methods=["GET", "HEAD"])
def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok"}

@app.on_event("startup")
def startup_event():
    init_db()

if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))
    reload = os.environ.get("ENV", "development").lower() == "development"
    uvicorn.run("server:app", host=host, port=port, reload=reload)
