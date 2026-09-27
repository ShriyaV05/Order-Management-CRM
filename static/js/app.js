// POPCONE ORDER & SALES CRM - MAIN CLIENT APPLICATION
document.addEventListener('DOMContentLoaded', async () => {
  // Global App State
  const state = {
    user: api.getUser(),
    activeTab: 'dashboard',
    locations: {},
    settings: { bottle_price: 149, low_stock_threshold: 20 },
    orders: [],
    availableDistricts: [],
    currentOrderFilter: {
      search: '',
      payment: 'All',
      dispatch: 'All',
      district: 'All',
      date_filter: 'All',
      sort_by: 'Newest'
    },
    analyticsYear: new Date().getFullYear(),
    newOrderState: {
      flavours: {
        'Tomato': 0,
        'Cheese': 0,
        'Sour Cream': 0,
        'Peri Peri': 0
      },
      deliveryFee: 0.0,
      deliveryCalculated: 0.0,
      deliveryNotes: ''
    }
  };

  // Toast Helper
  function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    const icon = type === 'success' ? '✅' : type === 'danger' ? '❌' : '⚠️';
    toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  // ---------------- Authentication UI ----------------
  const loginOverlay = document.getElementById('login-overlay');
  const loginForm = document.getElementById('login-form');
  const loginError = document.getElementById('login-error');

  function updateAuthUI() {
    state.user = api.getUser();
    if (!state.user) {
      loginOverlay.style.display = 'flex';
      return;
    }
    loginOverlay.style.display = 'none';

    // Update Sidebar User Section (Requirement 6)
    const displayName = state.user.display_name || state.user.username.split('@')[0];
    document.getElementById('sidebar-user-name').textContent = displayName;
    const roleBadge = document.getElementById('sidebar-user-role');
    roleBadge.textContent = state.user.role;
    roleBadge.className = `user-role-badge role-${state.user.role.toLowerCase()}`;

    // Admin-only controls visibility
    const isAdmin = state.user.role === 'ADMIN';
    document.querySelectorAll('.admin-only').forEach(el => {
      el.style.display = isAdmin ? '' : 'none';
    });

    // Refresh current active view
    switchTab(state.activeTab);
  }

  window.addEventListener('auth-changed', () => updateAuthUI());

  loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    loginError.style.display = 'none';
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;

    try {
      await api.login(username, password);
      showToast('Logged in successfully!');
      updateAuthUI();
    } catch (err) {
      loginError.textContent = err.message || 'Login failed';
      loginError.style.display = 'block';
    }
  });

  document.getElementById('btn-logout').addEventListener('click', async () => {
    await api.logout();
    showToast('Logged out');
    updateAuthUI();
  });

  // ---------------- Navigation / Tabs ----------------
  const navItems = document.querySelectorAll('.nav-item');
  navItems.forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const tab = item.dataset.tab;
      switchTab(tab);
    });
  });

  function switchTab(tab) {
    state.activeTab = tab;
    navItems.forEach(item => {
      item.classList.toggle('active', item.dataset.tab === tab);
    });

    document.querySelectorAll('.view-page').forEach(page => {
      page.style.display = page.id === `view-${tab}` ? 'block' : 'none';
    });

    // Set page header title
    const titles = {
      dashboard: 'Dashboard',
      'new-order': 'New Order',
      orders: 'Orders Management',
      inventory: 'Inventory & Stock History',
      analytics: 'Sales Analytics & Reports'
    };
    document.getElementById('header-page-title').textContent = titles[tab] || 'POPCONE CRM';

    // Load tab-specific data
    if (tab === 'dashboard') loadDashboard();
    else if (tab === 'new-order') initNewOrderPage();
    else if (tab === 'orders') loadOrders();
    else if (tab === 'inventory') loadInventory();
    else if (tab === 'analytics') loadAnalytics();
  }

  // ---------------- Change Password Modal ----------------
  const changePasswordModal = document.getElementById('modal-change-password');
  document.getElementById('btn-open-change-password').addEventListener('click', () => {
    document.getElementById('form-change-password').reset();
    document.getElementById('change-pwd-error').style.display = 'none';
    changePasswordModal.classList.add('show');
  });

  document.getElementById('btn-close-change-pwd').addEventListener('click', () => {
    changePasswordModal.classList.remove('show');
  });

  document.getElementById('form-change-password').addEventListener('submit', async (e) => {
    e.preventDefault();
    const curr = document.getElementById('pwd-current').value;
    const nw = document.getElementById('pwd-new').value;
    const conf = document.getElementById('pwd-confirm').value;
    const errBox = document.getElementById('change-pwd-error');
    errBox.style.display = 'none';

    if (nw !== conf) {
      errBox.textContent = 'New passwords do not match';
      errBox.style.display = 'block';
      return;
    }

    try {
      await api.changePassword(curr, nw, conf);
      showToast('Password changed successfully');
      changePasswordModal.classList.remove('show');
    } catch (err) {
      errBox.textContent = err.message || 'Failed to change password';
      errBox.style.display = 'block';
    }
  });

  // ---------------- Bottle Price Setting Modal (Admin Only) ----------------
  const bottlePriceModal = document.getElementById('modal-bottle-price');
  document.getElementById('btn-open-bottle-price')?.addEventListener('click', async () => {
    const s = await api.getSettings();
    document.getElementById('setting-bottle-price-input').value = s.bottle_price;
    bottlePriceModal.classList.add('show');
  });

  document.getElementById('btn-close-bottle-price').addEventListener('click', () => {
    bottlePriceModal.classList.remove('show');
  });

  document.getElementById('form-bottle-price').addEventListener('submit', async (e) => {
    e.preventDefault();
    const newPrice = document.getElementById('setting-bottle-price-input').value;
    try {
      await api.updateBottlePrice(newPrice);
      showToast(`Bottle price updated to ₹${newPrice}`);
      bottlePriceModal.classList.remove('show');
      await refreshGlobalSettings();
      if (state.activeTab === 'new-order') recalcNewOrderPricing();
    } catch (err) {
      showToast(err.message, 'danger');
    }
  });

  async function refreshGlobalSettings() {
    try {
      const res = await api.getSettings();
      state.settings = res;
      document.querySelectorAll('.current-bottle-price-display').forEach(el => {
        el.textContent = `₹${res.bottle_price}`;
      });
    } catch (e) {
      console.warn('Could not load settings:', e);
    }
  }

  // ---------------- 1. DASHBOARD ----------------
  async function loadDashboard() {
    try {
      const data = await api.getDashboardStats();
      const kpis = data.kpis;

      // Update KPI Cards (Rule 8: ONLY these 5 KPIs, NO prohibited metrics!)
      document.getElementById('kpi-total-revenue').textContent = `₹${kpis.total_revenue.toLocaleString('en-IN')}`;
      document.getElementById('kpi-total-orders').textContent = kpis.total_orders;
      document.getElementById('kpi-bottles-sold').textContent = kpis.bottles_sold;
      document.getElementById('kpi-paid-orders').textContent = kpis.paid_orders;
      document.getElementById('kpi-cod-orders').textContent = kpis.cod_orders;

      // Low Stock Alert (<= 20 bottles)
      const alertBanner = document.getElementById('low-stock-alert-banner');
      const alertItems = document.getElementById('low-stock-items-list');
      if (data.low_stock && data.low_stock.length > 0) {
        alertItems.innerHTML = data.low_stock.map(item => 
          `<span class="low-stock-tag">${item.flavour} (${item.stock})</span>`
        ).join(' ');
        alertBanner.style.display = 'flex';
      } else {
        alertBanner.style.display = 'none';
      }

      // Most purchased flavour & Flavour Sales breakdown
      const mostFlv = data.most_purchased_flavour;
      document.getElementById('dashboard-most-flavour').textContent = mostFlv.name !== 'None' ? `${mostFlv.name} (${mostFlv.bottles} bottles)` : 'None';

      const flavourContainer = document.getElementById('dashboard-flavour-sales-grid');
      const sales = data.flavour_sales;
      const totalBottles = Object.values(sales).reduce((a, b) => a + b, 0) || 1;
      flavourContainer.innerHTML = Object.entries(sales).map(([flv, qty]) => {
        const pct = Math.round((qty / totalBottles) * 100);
        return `
          <div class="flavour-card">
            <div class="flavour-header">
              <span class="flavour-name">${flv}</span>
              <span class="badge ${qty > 20 ? 'badge-paid' : 'badge-cod'}">${qty} sold</span>
            </div>
            <div style="background: #E2E8F0; height: 8px; border-radius: 4px; overflow: hidden; margin-top: 6px;">
              <div style="background: var(--primary-blue); width: ${pct}%; height: 100%; border-radius: 4px;"></div>
            </div>
            <div style="display:flex; justify-content:space-between; font-size:11px; color:var(--text-muted); margin-top:2px;">
              <span>Share: ${pct}%</span>
              <span>₹${(qty * state.settings.bottle_price).toLocaleString('en-IN')}</span>
            </div>
          </div>
        `;
      }).join('');

      // Recent Orders Table
      const recentTableBody = document.getElementById('dashboard-recent-orders-tbody');
      if (data.recent_orders && data.recent_orders.length > 0) {
        recentTableBody.innerHTML = data.recent_orders.map(o => `
          <tr data-order-id="${o.order_id}">
            <td><strong>${o.order_id}</strong></td>
            <td>${o.customer}</td>
            <td>₹${o.amount.toLocaleString('en-IN')}</td>
            <td><span class="badge ${o.payment === 'Paid' ? 'badge-paid' : 'badge-cod'}">${o.payment}</span></td>
            <td><span class="badge ${o.dispatch_state === 'DISPATCHED' ? 'badge-dispatched' : 'badge-placed'}">${o.dispatch_state}</span></td>
            <td>${o.created_at}</td>
          </tr>
        `).join('');

        recentTableBody.querySelectorAll('tr').forEach(row => {
          row.addEventListener('click', () => openOrderDetails(row.dataset.orderId));
        });
      } else {
        recentTableBody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 24px;">No orders yet</td></tr>`;
      }

    } catch (err) {
      console.error('Error loading dashboard:', err);
      showToast('Failed to load dashboard data', 'danger');
    }
  }

  // Quick Action Buttons
  document.getElementById('btn-dashboard-new-order')?.addEventListener('click', () => switchTab('new-order'));
  document.getElementById('btn-dashboard-view-all-orders')?.addEventListener('click', () => switchTab('orders'));

  // ---------------- 2. NEW ORDER PAGE ----------------
  async function initNewOrderPage() {
    await refreshGlobalSettings();
    if (Object.keys(state.locations).length === 0) {
      try {
        const res = await api.getLocations();
        state.locations = res.locations;
      } catch (e) {
        console.warn('Locations error:', e);
      }
    }

    // Populate State Select
    const stateSelect = document.getElementById('new-order-state');
    const districtSelect = document.getElementById('new-order-district');
    stateSelect.innerHTML = '<option value="">-- Select State --</option>';
    Object.keys(state.locations).sort().forEach(st => {
      stateSelect.innerHTML += `<option value="${st}">${st}</option>`;
    });

    // Default to Tamil Nadu
    if (state.locations['Tamil Nadu']) {
      stateSelect.value = 'Tamil Nadu';
      populateDistricts('Tamil Nadu', 'Chennai');
    }

    stateSelect.onchange = () => {
      populateDistricts(stateSelect.value);
      recalcNewOrderPricing();
    };

    districtSelect.onchange = () => {
      recalcNewOrderPricing();
    };

    // Phone Unique Check (Rule 11)
    const phoneInput = document.getElementById('new-order-phone');
    const phoneError = document.getElementById('new-order-phone-error');
    phoneInput.onblur = async () => {
      const val = phoneInput.value.trim();
      if (val.length >= 10) {
        try {
          const check = await api.checkPhone(val);
          if (check.exists) {
            phoneError.textContent = check.message;
            phoneError.classList.add('show');
            phoneInput.classList.add('is-invalid');
          } else {
            phoneError.classList.remove('show');
            phoneInput.classList.remove('is-invalid');
          }
        } catch (e) {
          console.error(e);
        }
      }
    };

    phoneInput.oninput = () => {
      phoneError.classList.remove('show');
      phoneInput.classList.remove('is-invalid');
    };

    // Flavour Counters
    ['Tomato', 'Cheese', 'Sour Cream', 'Peri Peri'].forEach(flv => {
      const input = document.getElementById(`qty-${flv.toLowerCase().replace(' ', '-')}`);
      if (input) {
        input.value = state.newOrderState.flavours[flv] || 0;
        input.oninput = () => {
          state.newOrderState.flavours[flv] = Math.max(0, parseInt(input.value) || 0);
          recalcNewOrderPricing();
        };
      }
    });

    // Manual delivery fee edit listener
    const deliveryFeeInput = document.getElementById('new-order-delivery-fee');
    deliveryFeeInput.oninput = () => {
      state.newOrderState.deliveryFee = parseFloat(deliveryFeeInput.value) || 0;
      updateFinalPricingDisplay();
    };

    recalcNewOrderPricing();
  }

  function populateDistricts(selectedState, defaultDistrict = null) {
    const districtSelect = document.getElementById('new-order-district');
    districtSelect.innerHTML = '<option value="">-- Select District --</option>';
    const districts = state.locations[selectedState] || [];
    districts.sort().forEach(d => {
      districtSelect.innerHTML += `<option value="${d}">${d}</option>`;
    });
    if (defaultDistrict && districts.includes(defaultDistrict)) {
      districtSelect.value = defaultDistrict;
    }
  }

  // ---------------- Delivery Fee Calculation Rules ----------------
  const SOUTH_INDIA_STATES = new Set(['karnataka', 'kerala', 'andhra pradesh', 'telangana', 'puducherry']);
  const DELIVERY_RATES = {
    'Chennai': { tier1: 40.0, tier2: 42.0, tier3: 45.0, excess: 20.0 },
    'Tamil Nadu': { tier1: 65.0, tier2: 65.0, tier3: 70.0, excess: 30.0 },
    'South India': { tier1: 75.0, tier2: 78.0, tier3: 80.0, excess: 35.0 },
    'North/East/West': { tier1: 100.0, tier2: 150.0, tier3: 230.0, excess: 80.0 }
  };

  function computeDeliveryFeeClient(stateVal, distVal, totalBottles) {
    const st = (stateVal || '').trim().toLowerCase();
    const dist = (distVal || '').trim().toLowerCase();

    if (!st || !dist || totalBottles <= 0) {
      return {
        fee: 0,
        weightGrams: totalBottles > 0 ? totalBottles * 110 : 0,
        weightDisplay: totalBottles * 110 >= 1000 ? `${(totalBottles * 110 / 1000).toFixed(2)}kg` : `${totalBottles * 110}g`,
        zone: 'Unknown',
        slab: 'None',
        notes: (!st || !dist) ? 'Select state and district to calculate' : 'Select at least 1 bottle to calculate'
      };
    }

    const weightGrams = totalBottles * 110;
    const weightDisplay = weightGrams >= 1000 ? `${(weightGrams / 1000).toFixed(2)}kg` : `${weightGrams}g`;

    let zone = 'North/East/West';
    if (st === 'tamil nadu' && dist === 'chennai') {
      zone = 'Chennai';
    } else if (st === 'tamil nadu') {
      zone = 'Tamil Nadu';
    } else if (SOUTH_INDIA_STATES.has(st)) {
      zone = 'South India';
    }

    const rates = DELIVERY_RATES[zone] || DELIVERY_RATES['North/East/West'];
    let fee = 0;
    let slab = '';
    let notes = '';

    if (weightGrams <= 250) {
      fee = rates.tier1;
      slab = 'Up to 250g';
      notes = `${zone} (<=250g)`;
    } else if (weightGrams <= 500) {
      fee = rates.tier2;
      slab = '250g–500g';
      notes = `${zone} (251g–500g)`;
    } else if (weightGrams <= 1000) {
      fee = rates.tier3;
      slab = '500g–1kg';
      notes = `${zone} (501g–1kg)`;
    } else {
      const excessGrams = weightGrams - 1000;
      const excessUnits = Math.ceil(excessGrams / 500);
      const surcharge = excessUnits * rates.excess;
      fee = rates.tier3 + surcharge;
      slab = `> 1kg (${weightDisplay})`;
      notes = `${zone} 1kg base (₹${rates.tier3}) + ₹${surcharge} excess (${excessUnits} x 500g slab)`;
    }

    return {
      fee,
      weightGrams,
      weightDisplay,
      zone,
      slab,
      notes
    };
  }

  // Adjust flavour quantity button helper
  window.adjustFlavourQty = (flavourName, delta) => {
    const id = `qty-${flavourName.toLowerCase().replace(' ', '-')}`;
    const input = document.getElementById(id);
    if (!input) return;
    let val = Math.max(0, (parseInt(input.value) || 0) + delta);
    input.value = val;
    state.newOrderState.flavours[flavourName] = val;
    recalcNewOrderPricing();
  };

  function recalcNewOrderPricing() {
    const stateVal = document.getElementById('new-order-state').value;
    const distVal = document.getElementById('new-order-district').value;
    const totalBottles = Object.values(state.newOrderState.flavours).reduce((a, b) => a + b, 0);

    const calc = computeDeliveryFeeClient(stateVal, distVal, totalBottles);

    document.getElementById('new-order-bottles-count').textContent = totalBottles;
    document.getElementById('new-order-weight-display').textContent = calc.weightDisplay;

    const unitPrice = state.settings.bottle_price || 149;
    const productAmount = totalBottles * unitPrice;
    document.getElementById('new-order-product-amount').textContent = `₹${productAmount.toLocaleString('en-IN')}`;

    const feeInput = document.getElementById('new-order-delivery-fee');
    const noteEl = document.getElementById('new-order-delivery-note');

    if (totalBottles > 0 && stateVal && distVal) {
      feeInput.value = calc.fee;
      state.newOrderState.deliveryCalculated = calc.fee;
      state.newOrderState.deliveryFee = calc.fee;
      state.newOrderState.deliveryNotes = calc.notes;
      noteEl.textContent = `Zone: ${calc.zone} | Slab: ${calc.slab} (${calc.notes})`;
    } else {
      feeInput.value = 0;
      state.newOrderState.deliveryCalculated = 0;
      state.newOrderState.deliveryFee = 0;
      state.newOrderState.deliveryNotes = '';
      if (!stateVal || !distVal) {
        noteEl.textContent = 'Select state and district to calculate';
      } else {
        noteEl.textContent = 'Select at least 1 bottle to calculate';
      }
    }

    updateFinalPricingDisplay();
  }

  function updateFinalPricingDisplay() {
    const totalBottles = Object.values(state.newOrderState.flavours).reduce((a, b) => a + b, 0);
    const unitPrice = state.settings.bottle_price || 149;
    const productAmount = totalBottles * unitPrice;
    const feeInput = document.getElementById('new-order-delivery-fee');
    const deliveryFee = feeInput && feeInput.value !== '' ? (parseFloat(feeInput.value) || 0) : 0;
    const finalAmount = productAmount + deliveryFee;

    document.getElementById('new-order-final-amount').textContent = `₹${finalAmount.toLocaleString('en-IN')}`;
  }

  // Create Order Submission (Rule 20)
  document.getElementById('form-new-order').addEventListener('submit', async (e) => {
    e.preventDefault();
    const phoneError = document.getElementById('new-order-phone-error');
    phoneError.classList.remove('show');

    const customerName = document.getElementById('new-order-customer').value.trim();
    const phone = document.getElementById('new-order-phone').value.trim();
    const address = document.getElementById('new-order-address').value.trim();
    const pinCode = document.getElementById('new-order-pincode').value.trim();
    const stateVal = document.getElementById('new-order-state').value.trim();
    const distVal = document.getElementById('new-order-district').value.trim();
    const payment = document.getElementById('new-order-payment').value;
    const deliveryFee = parseFloat(document.getElementById('new-order-delivery-fee').value) || 0;

    const items = Object.entries(state.newOrderState.flavours)
      .filter(([_, qty]) => qty > 0)
      .map(([flavour, quantity]) => ({ flavour, quantity }));

    if (items.length === 0) {
      showToast('Please add at least 1 bottle to the order', 'warning');
      return;
    }

    const payload = {
      customer_name: customerName,
      phone,
      address,
      pin_code: pinCode,
      state: stateVal,
      district: distVal,
      payment,
      delivery_fee: deliveryFee,
      items
    };

    try {
      const res = await api.createOrder(payload);
      showToast(`Order ${res.order_id} created successfully!`);

      // Reset form to blank (Requirement 20: "After successful creation, the New Order screen must become blank/reset and ready for another order")
      document.getElementById('form-new-order').reset();
      state.newOrderState.flavours = { 'Tomato': 0, 'Cheese': 0, 'Sour Cream': 0, 'Peri Peri': 0 };
      ['Tomato', 'Cheese', 'Sour Cream', 'Peri Peri'].forEach(flv => {
        const id = `qty-${flv.toLowerCase().replace(' ', '-')}`;
        const input = document.getElementById(id);
        if (input) input.value = 0;
      });
      document.getElementById('new-order-delivery-fee').value = 0;
      populateDistricts('Tamil Nadu', 'Chennai');
      recalcNewOrderPricing();

    } catch (err) {
      if (err.message && err.message.includes('associated with Order ID')) {
        phoneError.textContent = err.message;
        phoneError.classList.add('show');
        document.getElementById('new-order-phone').classList.add('is-invalid');
      } else {
        showToast(err.message || 'Failed to create order', 'danger');
      }
    }
  });

  // Reset form handler
  document.getElementById('form-new-order').addEventListener('reset', () => {
    state.newOrderState.flavours = { 'Tomato': 0, 'Cheese': 0, 'Sour Cream': 0, 'Peri Peri': 0 };
    ['Tomato', 'Cheese', 'Sour Cream', 'Peri Peri'].forEach(flv => {
      const id = `qty-${flv.toLowerCase().replace(' ', '-')}`;
      const input = document.getElementById(id);
      if (input) input.value = 0;
    });
    document.getElementById('new-order-delivery-fee').value = 0;
    setTimeout(() => {
      populateDistricts('Tamil Nadu', 'Chennai');
      recalcNewOrderPricing();
    }, 20);
  });

  // ---------------- 3. ORDERS PAGE ----------------
  async function loadOrders() {
    try {
      const data = await api.getOrders(state.currentOrderFilter);
      state.orders = data.orders;
      state.availableDistricts = data.available_districts;

      // Update district filter dropdown
      const distFilter = document.getElementById('filter-order-district');
      const currDist = state.currentOrderFilter.district;
      distFilter.innerHTML = '<option value="All">All Districts</option>';
      state.availableDistricts.forEach(d => {
        distFilter.innerHTML += `<option value="${d}" ${d === currDist ? 'selected' : ''}>${d}</option>`;
      });

      renderOrdersTable();
    } catch (err) {
      console.error('Error loading orders:', err);
      showToast('Failed to load orders', 'danger');
    }
  }

  function renderOrdersTable() {
    const tbody = document.getElementById('orders-table-tbody');
    const orders = state.orders;

    if (!orders || orders.length === 0) {
      tbody.innerHTML = `<tr><td colspan="16" style="text-align:center; padding: 40px; color: var(--text-secondary);">No orders match the selected filters.</td></tr>`;
      return;
    }

    // Exact Column Order (Requirement 30):
    // 1. Order ID
    // 2. Date
    // 3. Customer
    // 4. Phone
    // 5. District
    // 6. State
    // 7. Bottles
    // 8. Weight
    // 9. Product
    // 10. Delivery
    // 11. Final
    // 12. Payment
    // 13. DISPATCHED / PLACED
    // 14. CREATED BY
    // 15. EDITED BY
    // 16. THREE-DOT MENU
    tbody.innerHTML = orders.map(o => {
      const isDispatched = o.dispatch === 'DISPATCHED';
      return `
        <tr data-order-id="${o.order_id}">
          <td><strong>${o.order_id}</strong></td>
          <td>${o.date.split(' ')[0]}</td>
          <td>${o.customer}</td>
          <td>${o.phone}</td>
          <td>${o.district}</td>
          <td>${o.state}</td>
          <td><strong>${o.bottles}</strong></td>
          <td>${o.weight}</td>
          <td>₹${o.product.toLocaleString('en-IN')}</td>
          <td>₹${o.delivery.toLocaleString('en-IN')}</td>
          <td><strong>₹${o.final.toLocaleString('en-IN')}</strong></td>
          <td><span class="badge ${o.payment === 'Paid' ? 'badge-paid' : 'badge-cod'}">${o.payment}</span></td>
          <td>
            <button class="btn-dispatch-toggle ${isDispatched ? 'is-dispatched' : 'is-placed'}" 
                    data-toggle-id="${o.order_id}" 
                    title="Click to toggle dispatch status">
              ${o.dispatch}
            </button>
          </td>
          <td><span style="font-size:12px; color:var(--text-secondary);">${o.created_by}</span></td>
          <td><span style="font-size:12px; color:var(--text-secondary);">${o.edited_by}</span></td>
          <td>
            <div class="three-dot-menu-wrapper">
              <button class="btn-three-dot" data-menu-id="${o.order_id}">⋮</button>
              <div class="three-dot-dropdown" id="dropdown-${o.order_id}">
                <div class="three-dot-item" data-action="edit" data-order-id="${o.order_id}">✏️ Edit Order</div>
                <div class="three-dot-item text-danger" data-action="delete" data-order-id="${o.order_id}">🗑️ Delete Order</div>
              </div>
            </div>
          </td>
        </tr>
      `;
    }).join('');

    // Row click: opens details (Requirement 36)
    tbody.querySelectorAll('tr').forEach(row => {
      row.addEventListener('click', (e) => {
        // Prevent opening if clicked on dispatch toggle or 3-dot menu
        if (e.target.closest('.btn-dispatch-toggle') || e.target.closest('.three-dot-menu-wrapper')) {
          return;
        }
        openOrderDetails(row.dataset.orderId);
      });
    });

    // Dispatch Toggle click listener (Requirement 34 & 35)
    tbody.querySelectorAll('.btn-dispatch-toggle').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const oid = btn.dataset.toggleId;
        try {
          const res = await api.toggleDispatch(oid);
          showToast(`Order ${oid} status: ${res.dispatch_state}`);
          await loadOrders();
        } catch (err) {
          showToast(err.message || 'Failed to update dispatch', 'danger');
        }
      });
    });

    // Three Dot Menu listeners (Requirement 37)
    tbody.querySelectorAll('.btn-three-dot').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const oid = btn.dataset.menuId;
        // Close other open menus
        document.querySelectorAll('.three-dot-dropdown.show').forEach(m => {
          if (m.id !== `dropdown-${oid}`) m.classList.remove('show');
        });
        const dropdown = document.getElementById(`dropdown-${oid}`);
        if (dropdown) dropdown.classList.toggle('show');
      });
    });

    // Dropdown Action items
    tbody.querySelectorAll('.three-dot-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        const action = item.dataset.action;
        const oid = item.dataset.orderId;
        const dropdown = item.closest('.three-dot-dropdown');
        if (dropdown) dropdown.classList.remove('show');

        if (action === 'edit') {
          openEditOrderModal(oid);
        } else if (action === 'delete') {
          openDeleteOrderModal(oid);
        }
      });
    });
  }

  // Close dropdowns on outside click
  document.addEventListener('click', () => {
    document.querySelectorAll('.three-dot-dropdown.show').forEach(m => m.classList.remove('show'));
  });

  // Filter & Search Controls
  document.getElementById('search-orders-input').addEventListener('input', (e) => {
    state.currentOrderFilter.search = e.target.value;
    loadOrders();
  });

  document.getElementById('filter-order-payment').addEventListener('change', (e) => {
    state.currentOrderFilter.payment = e.target.value;
    loadOrders();
  });

  document.getElementById('filter-order-dispatch').addEventListener('change', (e) => {
    state.currentOrderFilter.dispatch = e.target.value;
    loadOrders();
  });

  document.getElementById('filter-order-district').addEventListener('change', (e) => {
    state.currentOrderFilter.district = e.target.value;
    loadOrders();
  });

  document.getElementById('filter-order-date').addEventListener('change', (e) => {
    state.currentOrderFilter.date_filter = e.target.value;
    loadOrders();
  });

  document.getElementById('filter-order-sort').addEventListener('change', (e) => {
    state.currentOrderFilter.sort_by = e.target.value;
    loadOrders();
  });

  // Order CSV Export (Requirement 42: Exports currently displayed/filtered/sorted order results)
  document.getElementById('btn-export-orders-csv').addEventListener('click', () => {
    if (!state.orders || state.orders.length === 0) {
      showToast('No orders to export', 'warning');
      return;
    }

    const headers = [
      'Order ID', 'Date', 'Customer', 'Phone', 'District', 'State',
      'Bottles', 'Weight', 'Product', 'Delivery', 'Final', 'Payment',
      'Dispatch', 'Created By', 'Edited By'
    ];

    const rows = state.orders.map(o => [
      `"${o.order_id}"`,
      `"${o.date}"`,
      `"${o.customer.replace(/"/g, '""')}"`,
      `"${o.phone}"`,
      `"${o.district}"`,
      `"${o.state}"`,
      o.bottles,
      `"${o.weight}"`,
      o.product,
      o.delivery,
      o.final,
      `"${o.payment}"`,
      `"${o.dispatch}"`,
      `"${o.created_by}"`,
      `"${o.edited_by}"`
    ]);

    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    link.setAttribute('download', `POPCONE_Orders_Export_${timestamp}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast('Orders exported to CSV successfully');
  });

  // ---------------- 4. ORDER DETAILS MODAL (Second Reference Image Styled) ----------------
  const orderDetailsModal = document.getElementById('modal-order-details');

  async function openOrderDetails(orderId) {
    try {
      const res = await api.getOrder(orderId);
      const o = res.order;

      document.getElementById('detail-order-id').textContent = o.order_id;
      document.getElementById('detail-order-date').textContent = o.date;
      document.getElementById('detail-customer-name').textContent = o.customer;
      document.getElementById('detail-customer-phone').textContent = o.phone;
      document.getElementById('detail-customer-address').textContent = o.address;
      document.getElementById('detail-customer-location').textContent = `${o.district}, ${o.state} - ${o.pin_code}`;

      document.getElementById('detail-total-bottles').textContent = o.total_bottles;
      document.getElementById('detail-total-weight').textContent = o.total_weight;
      document.getElementById('detail-product-amount').textContent = `₹${o.product_amount.toLocaleString('en-IN')}`;
      document.getElementById('detail-delivery-fee').textContent = `₹${o.delivery_fee.toLocaleString('en-IN')}`;
      document.getElementById('detail-final-amount').textContent = `₹${o.final_amount.toLocaleString('en-IN')}`;
      document.getElementById('detail-payment-method').textContent = o.payment;
      document.getElementById('detail-created-info').textContent = `${o.created_by} (${o.created_at})`;
      document.getElementById('detail-edited-info').textContent = `${o.edited_by} (${o.edited_at})`;

      const dispatchBadge = document.getElementById('detail-dispatch-badge');
      dispatchBadge.textContent = o.dispatch_state;
      dispatchBadge.className = `badge ${o.dispatch_state === 'DISPATCHED' ? 'badge-dispatched' : 'badge-placed'}`;

      // Ordered Products: ONLY ordered flavours (> 0 quantity) (Requirement 13 & 36)
      const productsTbody = document.getElementById('detail-products-tbody');
      productsTbody.innerHTML = o.items.map(it => `
        <tr>
          <td><strong>${it.flavour}</strong></td>
          <td>${it.quantity}</td>
          <td>₹${it.unit_price}</td>
          <td><strong>₹${it.line_amount}</strong></td>
        </tr>
      `).join('');

      // Dispatch Toggle button in Details
      const toggleBtn = document.getElementById('btn-detail-toggle-dispatch');
      toggleBtn.textContent = o.dispatch_state === 'DISPATCHED' ? 'Mark as PLACED' : 'Mark as DISPATCHED';
      toggleBtn.onclick = async () => {
        try {
          await api.toggleDispatch(o.order_id);
          showToast(`Order ${o.order_id} dispatch updated`);
          await openOrderDetails(o.order_id);
          await loadOrders();
        } catch (e) {
          showToast(e.message, 'danger');
        }
      };

      // Actions in details
      document.getElementById('btn-detail-edit').onclick = () => {
        orderDetailsModal.classList.remove('show');
        openEditOrderModal(o.order_id);
      };

      document.getElementById('btn-detail-delete').onclick = () => {
        orderDetailsModal.classList.remove('show');
        openDeleteOrderModal(o.order_id);
      };

      orderDetailsModal.classList.add('show');
    } catch (err) {
      showToast(err.message || 'Failed to load order details', 'danger');
    }
  }

  document.getElementById('btn-close-order-details').addEventListener('click', () => {
    orderDetailsModal.classList.remove('show');
  });

  // ---------------- 5. EDIT ORDER MODAL (Requirement 38) ----------------
  const editOrderModal = document.getElementById('modal-edit-order');
  let currentEditingOrder = null;

  async function openEditOrderModal(orderId) {
    try {
      const res = await api.getOrder(orderId);
      currentEditingOrder = res.order;
      const o = res.order;

      document.getElementById('edit-order-id-display').textContent = o.order_id;
      document.getElementById('edit-customer-name').value = o.customer;
      document.getElementById('edit-phone').value = o.phone;
      document.getElementById('edit-address').value = o.address;
      document.getElementById('edit-pincode').value = o.pin_code;
      document.getElementById('edit-delivery-fee').value = o.delivery_fee;
      document.getElementById('edit-payment').value = o.payment;

      // Populate States & Districts
      const stSelect = document.getElementById('edit-state');
      const distSelect = document.getElementById('edit-district');
      stSelect.innerHTML = '';
      Object.keys(state.locations).sort().forEach(st => {
        stSelect.innerHTML += `<option value="${st}" ${st === o.state ? 'selected' : ''}>${st}</option>`;
      });

      const distList = state.locations[o.state] || [];
      distSelect.innerHTML = '';
      distList.sort().forEach(d => {
        distSelect.innerHTML += `<option value="${d}" ${d === o.district ? 'selected' : ''}>${d}</option>`;
      });

      stSelect.onchange = () => {
        const newDists = state.locations[stSelect.value] || [];
        distSelect.innerHTML = '';
        newDists.sort().forEach(d => {
          distSelect.innerHTML += `<option value="${d}">${d}</option>`;
        });
        recalcEditOrderPricing();
      };

      distSelect.onchange = () => recalcEditOrderPricing();

      // Flavour Quantities
      const itemsMap = {};
      o.items.forEach(it => { itemsMap[it.flavour] = it.quantity; });
      ['Tomato', 'Cheese', 'Sour Cream', 'Peri Peri'].forEach(flv => {
        const input = document.getElementById(`edit-qty-${flv.toLowerCase().replace(' ', '-')}`);
        if (input) {
          input.value = itemsMap[flv] || 0;
          input.oninput = () => recalcEditOrderPricing();
        }
      });

      document.getElementById('edit-delivery-fee').oninput = () => recalcEditOrderPricing();

      recalcEditOrderPricing();
      editOrderModal.classList.add('show');
    } catch (err) {
      showToast(err.message || 'Failed to open edit modal', 'danger');
    }
  }

  function recalcEditOrderPricing() {
    if (!currentEditingOrder) return;
    let totalBottles = 0;
    ['Tomato', 'Cheese', 'Sour Cream', 'Peri Peri'].forEach(flv => {
      const input = document.getElementById(`edit-qty-${flv.toLowerCase().replace(' ', '-')}`);
      if (input) totalBottles += Math.max(0, parseInt(input.value) || 0);
    });

    const weightGrams = totalBottles * 110;
    const weightDisplay = weightGrams >= 1000 ? `${(weightGrams / 1000).toFixed(2)}kg` : `${weightGrams}g`;

    document.getElementById('edit-total-bottles').textContent = totalBottles;
    document.getElementById('edit-total-weight').textContent = weightDisplay;

    // Maintain historical unit price!
    const histPrice = currentEditingOrder.unit_price;
    const productAmount = totalBottles * histPrice;
    const deliveryFee = parseFloat(document.getElementById('edit-delivery-fee').value) || 0;
    const finalAmount = productAmount + deliveryFee;

    document.getElementById('edit-product-amount').textContent = `₹${productAmount.toLocaleString('en-IN')}`;
    document.getElementById('edit-final-amount').textContent = `₹${finalAmount.toLocaleString('en-IN')}`;
  }

  window.adjustEditFlavourQty = (flavourName, delta) => {
    const id = `edit-qty-${flavourName.toLowerCase().replace(' ', '-')}`;
    const input = document.getElementById(id);
    if (!input) return;
    input.value = Math.max(0, (parseInt(input.value) || 0) + delta);
    recalcEditOrderPricing();
  };

  document.getElementById('btn-close-edit-order').addEventListener('click', () => {
    editOrderModal.classList.remove('show');
  });

  document.getElementById('form-edit-order').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!currentEditingOrder) return;
    const oid = currentEditingOrder.order_id;

    const items = ['Tomato', 'Cheese', 'Sour Cream', 'Peri Peri'].map(flv => {
      const input = document.getElementById(`edit-qty-${flv.toLowerCase().replace(' ', '-')}`);
      return { flavour: flv, quantity: Math.max(0, parseInt(input.value) || 0) };
    }).filter(it => it.quantity > 0);

    if (items.length === 0) {
      showToast('Order must contain at least 1 bottle', 'warning');
      return;
    }

    const payload = {
      customer_name: document.getElementById('edit-customer-name').value.trim(),
      phone: document.getElementById('edit-phone').value.trim(),
      address: document.getElementById('edit-address').value.trim(),
      pin_code: document.getElementById('edit-pincode').value.trim(),
      state: document.getElementById('edit-state').value.trim(),
      district: document.getElementById('edit-district').value.trim(),
      payment: document.getElementById('edit-payment').value,
      delivery_fee: parseFloat(document.getElementById('edit-delivery-fee').value) || 0,
      items
    };

    try {
      await api.editOrder(oid, payload);
      showToast(`Order ${oid} updated successfully!`);
      editOrderModal.classList.remove('show');
      await loadOrders();
    } catch (err) {
      showToast(err.message || 'Failed to update order', 'danger');
    }
  });

  // ---------------- 6. DELETE ORDER MODAL (Requirement 39) ----------------
  const deleteOrderModal = document.getElementById('modal-delete-order');
  let pendingDeleteOrderId = null;

  function openDeleteOrderModal(orderId) {
    pendingDeleteOrderId = orderId;
    document.getElementById('delete-order-id-display').textContent = orderId;
    deleteOrderModal.classList.add('show');
  }

  document.getElementById('btn-cancel-delete-order').addEventListener('click', () => {
    deleteOrderModal.classList.remove('show');
  });

  document.getElementById('btn-confirm-delete-order').addEventListener('click', async () => {
    if (!pendingDeleteOrderId) return;
    try {
      await api.deleteOrder(pendingDeleteOrderId);
      showToast(`Order ${pendingDeleteOrderId} deleted and stock restored`);
      deleteOrderModal.classList.remove('show');
      await loadOrders();
      if (state.activeTab === 'dashboard') loadDashboard();
    } catch (err) {
      showToast(err.message || 'Failed to delete order', 'danger');
    }
  });

  // ---------------- 7. INVENTORY PAGE ----------------
  async function loadInventory() {
    try {
      const data = await api.getInventory();
      const stockGrid = document.getElementById('inventory-stock-grid');
      
      // Stock Cards (Flavours: Tomato, Cheese, Sour Cream, Peri Peri)
      stockGrid.innerHTML = data.stocks.map(s => {
        const isLow = s.current_stock <= s.low_stock_threshold;
        return `
          <div class="stock-card ${isLow ? 'low-stock' : ''}">
            <div class="stock-card-flavour">${s.flavour}</div>
            <div>
              <span class="stock-card-qty">${s.current_stock}</span>
              <span class="stock-card-unit">bottles</span>
            </div>
            <div class="stock-card-status ${isLow ? 'danger' : 'safe'}">
              ${isLow ? '⚠️ Low Stock (≤ 20)' : '✅ In Stock'}
            </div>
          </div>
        `;
      }).join('');

      // Movements Table (Columns: When, Flavour, Type, Change, Reference, Created By)
      const movementsTbody = document.getElementById('inventory-movements-tbody');
      if (data.movements && data.movements.length > 0) {
        movementsTbody.innerHTML = data.movements.map(m => {
          const isPos = m.change > 0;
          const changeBadge = isPos 
            ? `<span style="color:var(--success-green); font-weight:700;">+${m.change}</span>` 
            : `<span style="color:var(--danger-red); font-weight:700;">${m.change}</span>`;
          return `
            <tr>
              <td>${m.when}</td>
              <td><strong>${m.flavour}</strong></td>
              <td><span class="badge ${m.type === 'Stock Added' ? 'badge-paid' : m.type === 'Sold' ? 'badge-placed' : 'badge-cod'}">${m.type}</span></td>
              <td>${changeBadge}</td>
              <td>${m.reference}</td>
              <td>${m.created_by}</td>
            </tr>
          `;
        }).join('');
      } else {
        movementsTbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 24px;">No movements recorded yet</td></tr>`;
      }

    } catch (err) {
      console.error('Error loading inventory:', err);
      showToast('Failed to load inventory', 'danger');
    }
  }

  // Stock Movement Modal (Stock Added / Adjustment) - Admin Only
  const stockMovementModal = document.getElementById('modal-stock-movement');
  document.getElementById('btn-open-stock-movement')?.addEventListener('click', () => {
    document.getElementById('form-stock-movement').reset();
    stockMovementModal.classList.add('show');
  });

  document.getElementById('btn-close-stock-movement').addEventListener('click', () => {
    stockMovementModal.classList.remove('show');
  });

  document.getElementById('form-stock-movement').addEventListener('submit', async (e) => {
    e.preventDefault();
    const flavour = document.getElementById('movement-flavour').value;
    const type = document.getElementById('movement-type').value;
    const quantity = parseInt(document.getElementById('movement-quantity').value);
    const reference = document.getElementById('movement-reference').value.trim() || 'Manual stock update';

    try {
      await api.addOrAdjustStock({ flavour, movement_type: type, quantity, reference });
      showToast(`Updated ${flavour} stock`);
      stockMovementModal.classList.remove('show');
      await loadInventory();
    } catch (err) {
      showToast(err.message || 'Failed to update stock', 'danger');
    }
  });

  // Reset Inventory Modal - Admin Only (Requirement 25)
  const resetStockModal = document.getElementById('modal-reset-stock');
  document.getElementById('btn-open-reset-stock')?.addEventListener('click', () => {
    resetStockModal.classList.add('show');
  });

  document.getElementById('btn-cancel-reset-stock').addEventListener('click', () => {
    resetStockModal.classList.remove('show');
  });

  document.getElementById('btn-confirm-reset-stock').addEventListener('click', async () => {
    try {
      await api.resetInventory();
      showToast('All flavour stock quantities set to 0');
      resetStockModal.classList.remove('show');
      await loadInventory();
    } catch (err) {
      showToast(err.message || 'Failed to reset inventory', 'danger');
    }
  });

  // ---------------- 8. ANALYTICS PAGE (NO separate Reports page!) ----------------
  async function loadAnalytics() {
    try {
      const year = state.analyticsYear;
      const data = await api.getAnalytics(year);

      // Populate year selector
      const yearSelect = document.getElementById('analytics-year-select');
      yearSelect.innerHTML = data.available_years.map(y => 
        `<option value="${y}" ${y === year ? 'selected' : ''}>${y}</option>`
      ).join('');

      yearSelect.onchange = () => {
        state.analyticsYear = parseInt(yearSelect.value);
        loadAnalytics();
      };

      // 1. Sales Analytics Overview
      const ov = data.overview;
      document.getElementById('analytics-total-revenue').textContent = `₹${ov.total_revenue.toLocaleString('en-IN')}`;
      document.getElementById('analytics-total-bottles').textContent = ov.total_bottles;
      document.getElementById('analytics-total-orders').textContent = ov.total_orders;
      document.getElementById('analytics-most-purchased').textContent = ov.most_purchased_flavour !== 'None' 
        ? `${ov.most_purchased_flavour} (${ov.most_purchased_bottles} bottles)` 
        : 'None';

      // 2. Weekly Report Table
      const weeklyTbody = document.getElementById('analytics-weekly-tbody');
      const weeklyData = data.weekly_report;
      if (weeklyData && weeklyData.length > 0) {
        weeklyTbody.innerHTML = weeklyData.map(w => `
          <tr>
            <td><strong>${w.week_label}</strong></td>
            <td>${w.tomato}</td>
            <td>${w.cheese}</td>
            <td>${w.sour_cream}</td>
            <td>${w.peri_peri}</td>
            <td><strong>${w.total_bottles}</strong></td>
            <td>₹${w.revenue.toLocaleString('en-IN')}</td>
            <td><strong>${w.most_purchased_flavour}</strong></td>
          </tr>
        `).join('');
      } else {
        weeklyTbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 24px;">No weekly data for ${year}</td></tr>`;
      }

      // 3. Monthly Report Table (All 12 Months: Jan to Dec)
      const monthlyTbody = document.getElementById('analytics-monthly-tbody');
      const monthlyData = data.monthly_report;
      monthlyTbody.innerHTML = monthlyData.map(m => `
        <tr>
          <td><strong>${m.month_name}</strong></td>
          <td>${m.tomato}</td>
          <td>${m.cheese}</td>
          <td>${m.sour_cream}</td>
          <td>${m.peri_peri}</td>
          <td><strong>${m.total_bottles}</strong></td>
          <td>₹${m.revenue.toLocaleString('en-IN')}</td>
          <td><strong>${m.most_purchased_flavour}</strong></td>
        </tr>
      `).join('');

      // 4. Annual Report Table (All months of year combined)
      const ann = data.annual_report;
      const annualTbody = document.getElementById('analytics-annual-tbody');
      annualTbody.innerHTML = `
        <tr style="background:#FFF9C4; font-weight:700;">
          <td><strong>${ann.year} TOTAL</strong></td>
          <td>${ann.tomato_bottles} (₹${ann.tomato_revenue.toLocaleString('en-IN')})</td>
          <td>${ann.cheese_bottles} (₹${ann.cheese_revenue.toLocaleString('en-IN')})</td>
          <td>${ann.sour_cream_bottles} (₹${ann.sour_cream_revenue.toLocaleString('en-IN')})</td>
          <td>${ann.peri_peri_bottles} (₹${ann.peri_peri_revenue.toLocaleString('en-IN')})</td>
          <td><strong>${ann.total_bottles}</strong></td>
          <td><strong style="color:var(--primary-blue); font-size:15px;">₹${ann.total_revenue.toLocaleString('en-IN')}</strong></td>
          <td><span class="badge badge-paid">${ann.most_purchased_flavour}</span></td>
        </tr>
      `;

      // Export Buttons (Requirement 50: Weekly, Monthly, Annual CSV)
      setupAnalyticsExports(data);

    } catch (err) {
      console.error('Error loading analytics:', err);
      showToast('Failed to load analytics data', 'danger');
    }
  }

  function setupAnalyticsExports(analyticsData) {
    // Weekly CSV Export
    document.getElementById('btn-export-weekly-csv').onclick = () => {
      const headers = ['Week', 'Tomato Bottles', 'Cheese Bottles', 'Sour Cream Bottles', 'Peri Peri Bottles', 'Total Bottles', 'Revenue', 'Most Purchased Flavour'];
      const rows = analyticsData.weekly_report.map(w => [
        `"${w.week_label}"`, w.tomato, w.cheese, w.sour_cream, w.peri_peri, w.total_bottles, w.revenue, `"${w.most_purchased_flavour}"`
      ]);
      downloadCSV('POPCONE_Weekly_Report.csv', headers, rows);
    };

    // Monthly CSV Export
    document.getElementById('btn-export-monthly-csv').onclick = () => {
      const headers = ['Month', 'Tomato Bottles', 'Cheese Bottles', 'Sour Cream Bottles', 'Peri Peri Bottles', 'Total Bottles', 'Revenue', 'Most Purchased Flavour'];
      const rows = analyticsData.monthly_report.map(m => [
        `"${m.month_name}"`, m.tomato, m.cheese, m.sour_cream, m.peri_peri, m.total_bottles, m.revenue, `"${m.most_purchased_flavour}"`
      ]);
      downloadCSV(`POPCONE_Monthly_Report_${state.analyticsYear}.csv`, headers, rows);
    };

    // Annual CSV Export
    document.getElementById('btn-export-annual-csv').onclick = () => {
      const ann = analyticsData.annual_report;
      const headers = ['Year', 'Tomato Bottles', 'Tomato Revenue', 'Cheese Bottles', 'Cheese Revenue', 'Sour Cream Bottles', 'Sour Cream Revenue', 'Peri Peri Bottles', 'Peri Peri Revenue', 'Total Bottles', 'Total Revenue', 'Most Purchased Flavour'];
      const rows = [[
        ann.year, ann.tomato_bottles, ann.tomato_revenue, ann.cheese_bottles, ann.cheese_revenue,
        ann.sour_cream_bottles, ann.sour_cream_revenue, ann.peri_peri_bottles, ann.peri_peri_revenue,
        ann.total_bottles, ann.total_revenue, `"${ann.most_purchased_flavour}"`
      ]];
      downloadCSV(`POPCONE_Annual_Report_${state.analyticsYear}.csv`, headers, rows);
    };
  }

  function downloadCSV(filename, headers, rows) {
    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast(`Exported ${filename}`);
  }

  // ---------------- Initial Setup on Page Load ----------------
  updateAuthUI();
});
