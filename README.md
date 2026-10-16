# POPCONE CRM

A full-stack **Order & Sales CRM** built for POPCONE to manage customer orders, inventory, sales analytics, and business operations in one place.

## Features

* Secure authentication with **Admin / Member** roles
* Create, edit, view and delete orders 
* Real-time inventory management
* Stock additions and adjustments
* Automatic inventory deduction and restoration
* Configurable bottle pricing with historical price preservation
* Automatic delivery-fee calculation
* Order search, filtering and sorting
* Placed / Dispatched tracking
* Created By / Edited By audit tracking
* Complete audit history
* Weekly, Monthly and Annual analytics
* CSV exports for orders and reports
* Password change functionality
* POPCONE branded interface using `logo.jpg` and `icon.png`

## Roles

### Admin

Full access including:

* Inventory management
* Stock adjustments
* Inventory reset
* Bottle price configuration

### Member

* Create and manage orders
* View inventory
* View analytics
* Export data

## Core Modules

```text
Dashboard
New Order
Orders
Inventory
Analytics
```

## Database

Core entities:

```text
Users
Orders
Order Items
Inventory
Inventory Movements
Audit Logs
Settings
```

The system uses transactional operations to maintain consistency between orders, inventory and audit records.

## Security

* Secure password hashing
* Role-based authorization
* Server-side validation
* Protected backend routes
* Secure session handling
* No plaintext passwords

## Vercel Deployment

POPCONE CRM runs as a FastAPI app on Vercel. All live data is stored in **one Turso database**, not on the Vercel filesystem.

1. Import the GitHub repo into Vercel (Framework Preset: FastAPI).
2. In Project Settings -> Environment Variables, set:
   - `TURSO_DATABASE_URL`
   - `TURSO_AUTH_TOKEN`
3. Deploy. Confirm `/health` returns `"database": "turso"` and a live `order_count`.

## Purpose

POPCONE CRM provides a centralized system to manage **orders, customers, inventory, sales analytics and operational history** with accurate real-time data.
