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

## Render Deployment & Persistent Storage

POPCONE CRM stores its data in a SQLite database. On Render web services, the container filesystem is ephemeral by default, meaning redeployments or container sleep/restarts reset files in `/app`.

To ensure permanent database persistence across restarts and redeployments:

1. **Persistent Disk on Render**:
   - In the Render Dashboard, navigate to your Web Service -> **Disks**.
   - Click **Add Disk**:
     - **Name**: `popcone-data`
     - **Mount Path**: `/var/data`
     - **Size**: `1 GB` (or higher)
   - In **Environment Variables**, ensure:
     - `DB_PATH`: `/var/data/popcone.db`

2. **Automatic Blueprint Deployment**:
   - `render.yaml` is pre-configured with a persistent disk mounted at `/var/data` and sets `DB_PATH=/var/data/popcone.db`.
   - On initial mount, `database.py` automatically initializes or copies the initial database to `/var/data/popcone.db` if it doesn't already exist.

## Purpose

POPCONE CRM provides a centralized system to manage **orders, customers, inventory, sales analytics and operational history** with accurate real-time data.
