// POPCONE ORDER & SALES CRM - MAIN CLIENT APPLICATION
// Asset constants (simple and replaceable)
const APP_ICON_PATH = '/icon.png';
const APP_LOGO_PATH = '/logo.jpg';

document.addEventListener('DOMContentLoaded', async () => {
  // Global App State
  const state = {
    user: api.getUser(),
    activeTab: 'dashboard',
    locations: {},
    settings: { 
      original_bottle_price: 160, 
      bottle_price: 160, 
      discount_per_bottle: 11, 
      effective_bottle_price: 149, 
      low_stock_threshold: 20 
    },
    orders: [],
    availableDistricts: [],
    currentOrderFilter: {
      search: '',
      payment: 'All',
      dispatch: 'All',
      district: 'All',
      date_filter: 'All',
      date_from: '',
      date_to: '',
      sort_by: 'Newest'
    },
    analyticsMode: 'monthly', // 'weekly', 'monthly', 'annual'
    analyticsYear: new Date().getFullYear(),
    analyticsMonth: new Date().getMonth() + 1,
    analyticsData: null,
    newOrderState: {
      flavours: {
        'Tomato': 0,
        'Cheese': 0,
        'Sour Cream': 0,
        'Peri Peri': 0
      },
      comboSelected: null, // null | '2_BOTTLE' | '4_BOTTLE'
      deliveryFee: 0.0,
      deliveryCalculated: 0.0,
      deliveryNotes: '',
      isManualDeliveryFee: false
    }
  };

  // Toast Helper (Clean SVG Icons, NO Emojis)
  function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    const iconSvg = type === 'success' 
      ? `<svg class="icon-svg" style="color:var(--success-green);" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`
      : type === 'danger'
      ? `<svg class="icon-svg" style="color:var(--danger-red);" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="15" x2="9" y1="9" y2="15"/><line x1="9" x2="15" y1="9" y2="15"/></svg>`
      : `<svg class="icon-svg" style="color:var(--warning-amber);" viewBox="0 0 24 24"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg>`;
    toast.innerHTML = `<span>${iconSvg}</span> <span>${message}</span>`;
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

    // Requirement 22: User Display in Bottom-Left
    // For Ashish: Ashish \n ADMIN
    // For other members: Shriya / Vaishnavi / Harini / Suguna [no role label]
    const displayName = state.user.display_name || state.user.username.split('@')[0];
    document.getElementById('sidebar-user-name').textContent = displayName;
    const roleBadge = document.getElementById('sidebar-user-role');
    const isAdmin = state.user.role === 'ADMIN' || displayName.toLowerCase() === 'ashish';

    if (isAdmin) {
      roleBadge.textContent = 'ADMIN';
      roleBadge.style.display = 'inline-block';
      roleBadge.className = 'user-role-badge role-admin';
    } else {
      roleBadge.style.display = 'none';
      roleBadge.textContent = '';
    }

    // Requirement 4: Only Ashish can modify inventory, add stock, adjust stock, reset stock, change bottle price
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

    // Header title
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

  // ---------------- Professional Settings Modal (Requirements 1, 3, 12) ----------------
  const settingsModal = document.getElementById('modal-settings');
  const btnOpenSettings = document.getElementById('btn-open-settings');
  const btnCloseSettings = document.getElementById('btn-close-settings');

  async function openSettingsModal() {
    const isAdmin = state.user && (state.user.role === 'ADMIN' || (state.user.display_name || '').toLowerCase() === 'ashish' || (state.user.username || '').toLowerCase().startsWith('ashish'));

    // Toggle role visibility inside settings
    document.querySelectorAll('.admin-only').forEach(el => el.style.display = isAdmin ? '' : 'none');
    document.querySelectorAll('.member-only').forEach(el => el.style.display = isAdmin ? 'none' : '');

    await refreshGlobalSettings();

    // Fill settings inputs
    const discountInput = document.getElementById('setting-discount-input');
    if (discountInput) {
      discountInput.value = state.settings.discount_per_bottle !== undefined ? state.settings.discount_per_bottle : 11;
    }
    const memberDiscountDisplay = document.getElementById('member-discount-display');
    if (memberDiscountDisplay) {
      memberDiscountDisplay.textContent = state.settings.discount_per_bottle !== undefined ? state.settings.discount_per_bottle : 11;
    }
    const effectiveDisplay = document.getElementById('setting-effective-price-display');
    if (effectiveDisplay) {
      effectiveDisplay.textContent = `₹${state.settings.effective_bottle_price || (160 - (state.settings.discount_per_bottle || 11))}`;
    }

    // Populate Admin User Password dropdown
    if (isAdmin) {
      try {
        const usersData = await api.getUsers();
        const userSelect = document.getElementById('admin-select-user');
        if (userSelect && usersData.users) {
          userSelect.innerHTML = usersData.users.map(u => 
            `<option value="${u.username}">${u.display_name} (${u.role})</option>`
          ).join('');
        }
      } catch (err) {
        console.error('Failed to load users for settings:', err);
      }
      const pwdInput = document.getElementById('admin-input-new-password');
      if (pwdInput) pwdInput.value = '';
      const pwdStatus = document.getElementById('admin-pwd-status');
      if (pwdStatus) {
        pwdStatus.style.display = 'none';
        pwdStatus.textContent = '';
      }
    }

    settingsModal?.classList.add('show');
  }

  btnOpenSettings?.addEventListener('click', openSettingsModal);
  btnCloseSettings?.addEventListener('click', () => settingsModal?.classList.remove('show'));

  // Discount Form submit (Admin only, Requirement 3)
  document.getElementById('form-setting-discount')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const discountVal = parseFloat(document.getElementById('setting-discount-input').value);
    const feedback = document.getElementById('discount-setting-feedback');
    try {
      const res = await api.updateDiscount(discountVal);
      showToast(`Discount per bottle updated to ₹${res.discount_per_bottle}`);
      await refreshGlobalSettings();
      const effEl = document.getElementById('setting-effective-price-display');
      if (effEl) effEl.textContent = `₹${res.effective_bottle_price}`;
      if (feedback) {
        feedback.textContent = `Saved: ₹${res.discount_per_bottle}/bottle discount applied.`;
        feedback.style.color = 'var(--success-green)';
        feedback.style.display = 'block';
        setTimeout(() => { feedback.style.display = 'none'; }, 3000);
      }
      if (state.activeTab === 'new-order') recalcNewOrderPricing();
    } catch (err) {
      showToast(err.message || 'Failed to update discount', 'danger');
      if (feedback) {
        feedback.textContent = err.message || 'Failed to update discount';
        feedback.style.color = 'var(--danger-red)';
        feedback.style.display = 'block';
      }
    }
  });

  // Admin User Password Form submit (Admin only, Requirement 12)
  document.getElementById('form-admin-user-password')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const targetUsername = document.getElementById('admin-select-user').value;
    const newPassword = document.getElementById('admin-input-new-password').value;
    const statusBox = document.getElementById('admin-pwd-status');

    try {
      const res = await api.adminChangePassword(targetUsername, newPassword);
      showToast(res.message || `Password updated for ${targetUsername}`);
      document.getElementById('admin-input-new-password').value = '';
      if (statusBox) {
        statusBox.textContent = `Success: New password configured for ${targetUsername}!`;
        statusBox.style.color = 'var(--success-green)';
        statusBox.style.display = 'block';
        setTimeout(() => { statusBox.style.display = 'none'; }, 4000);
      }
    } catch (err) {
      showToast(err.message || 'Failed to update password', 'danger');
      if (statusBox) {
        statusBox.textContent = err.message || 'Failed to set password';
        statusBox.style.color = 'var(--danger-red)';
        statusBox.style.display = 'block';
      }
    }
  });

  async function refreshGlobalSettings() {
    try {
      const res = await api.getSettings();
      state.settings = {
        ...state.settings,
        ...res
      };
      // Original bottle price is fixed at 160 (Requirement 2)
      document.querySelectorAll('.current-bottle-price-display').forEach(el => {
        el.textContent = `₹160`;
      });
      // Effective bottle price
      document.querySelectorAll('.effective-price-display').forEach(el => {
        el.textContent = `₹${res.effective_bottle_price || (160 - (res.discount_per_bottle || 11))}`;
      });
      // Header discount badge
      document.querySelectorAll('.header-discount-badge').forEach(el => {
        el.textContent = `Discount: -₹${res.discount_per_bottle !== undefined ? res.discount_per_bottle : 11}/bottle`;
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

      // KPI Cards
      document.getElementById('kpi-total-revenue').textContent = `₹${kpis.total_revenue.toLocaleString('en-IN')}`;
      document.getElementById('kpi-total-orders').textContent = kpis.total_orders;
      document.getElementById('kpi-bottles-sold').textContent = kpis.bottles_sold;
      document.getElementById('kpi-paid-orders').textContent = kpis.paid_orders;
      document.getElementById('kpi-cod-orders').textContent = kpis.cod_orders;

      // Top Selling Flavour (Requirement 8)
      const mostFlv = data.most_purchased_flavour;
      const mostFlvEl = document.getElementById('dashboard-most-flavour');
      if (mostFlvEl) {
        mostFlvEl.textContent = (mostFlv && mostFlv.name !== 'None' && mostFlv.bottles > 0)
          ? `${mostFlv.name} (${mostFlv.bottles} bottles)`
          : 'None';
      }

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
        recentTableBody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 28px; color: var(--text-secondary);">No orders recorded yet</td></tr>`;
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

    // Default to Tamil Nadu & Chennai
    if (state.locations['Tamil Nadu']) {
      stateSelect.value = 'Tamil Nadu';
      populateDistricts('Tamil Nadu', 'Chennai');
    }

    stateSelect.onchange = () => {
      populateDistricts(stateSelect.value);
      if (!state.newOrderState.isManualDeliveryFee) {
        recalcNewOrderPricing();
      } else {
        updateFinalPricingDisplay();
      }
    };

    districtSelect.onchange = () => {
      if (!state.newOrderState.isManualDeliveryFee) {
        recalcNewOrderPricing();
      } else {
        updateFinalPricingDisplay();
      }
    };

    // Phone Unique Check
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

    // Automatic Indian PIN Code Lookup (Requirement 9)
    const pincodeInput = document.getElementById('new-order-pincode');
    const pincodeSpinner = document.getElementById('pincode-spinner');
    const pincodeFeedback = document.getElementById('pincode-feedback');
    let lastLookedUpPincode = '';
    let pincodeLookupSeq = 0;

    pincodeInput.oninput = async () => {
      const pin = pincodeInput.value.trim();
      pincodeFeedback.style.display = 'none';
      pincodeFeedback.className = 'pincode-feedback';

      if (pin.length === 6 && /^\d{6}$/.test(pin)) {
        if (pin === lastLookedUpPincode) return;
        const currentSeq = ++pincodeLookupSeq;
        pincodeSpinner.style.display = 'inline';

        try {
          const res = await api.lookupPincode(pin);
          if (currentSeq !== pincodeLookupSeq) return; // Ignore stale response
          pincodeSpinner.style.display = 'none';

          if (res && res.status === 'success' && res.state) {
            lastLookedUpPincode = pin;
            // Match State
            let matchedState = null;
            for (let opt of stateSelect.options) {
              if (opt.value.toLowerCase() === res.state.toLowerCase()) {
                matchedState = opt.value;
                break;
              }
            }
            if (matchedState) {
              stateSelect.value = matchedState;
              populateDistricts(matchedState, res.district);
              // Match District
              if (res.district) {
                for (let opt of districtSelect.options) {
                  if (opt.value.toLowerCase() === res.district.toLowerCase()) {
                    districtSelect.value = opt.value;
                    break;
                  }
                }
              }
              pincodeFeedback.textContent = `Auto-detected: ${districtSelect.value || res.district}, ${matchedState}`;
              pincodeFeedback.className = 'pincode-feedback success';
              pincodeFeedback.style.display = 'block';

              // Reset manual override and recalculate shipping
              state.newOrderState.isManualDeliveryFee = false;
              recalcNewOrderPricing();
            } else {
              pincodeFeedback.textContent = `Detected State: ${res.state}. Please choose your district manually.`;
              pincodeFeedback.className = 'pincode-feedback success';
              pincodeFeedback.style.display = 'block';
            }
          } else {
            pincodeFeedback.textContent = 'Postal information not found for this PIN code. Please select State & District manually.';
            pincodeFeedback.className = 'pincode-feedback error';
            pincodeFeedback.style.display = 'block';
          }
        } catch (err) {
          if (currentSeq !== pincodeLookupSeq) return;
          pincodeSpinner.style.display = 'none';
          pincodeFeedback.textContent = 'Postal lookup unavailable. Please enter State & District manually.';
          pincodeFeedback.className = 'pincode-feedback error';
          pincodeFeedback.style.display = 'block';
        }
      } else {
        lastLookedUpPincode = '';
      }
    };

    // Flavour Counter inputs
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

    // Optional Combo Offer Buttons (Requirement 4)
    const btnCombo2 = document.getElementById('btn-combo-2');
    const btnCombo4 = document.getElementById('btn-combo-4');

    btnCombo2?.addEventListener('click', () => {
      if (state.newOrderState.comboSelected === '2_BOTTLE') {
        state.newOrderState.comboSelected = null;
      } else {
        state.newOrderState.comboSelected = '2_BOTTLE';
      }
      recalcNewOrderPricing();
    });

    btnCombo4?.addEventListener('click', () => {
      if (state.newOrderState.comboSelected === '4_BOTTLE') {
        state.newOrderState.comboSelected = null;
      } else {
        state.newOrderState.comboSelected = '4_BOTTLE';
      }
      recalcNewOrderPricing();
    });

    // Manual delivery fee edit listener
    const deliveryFeeInput = document.getElementById('new-order-delivery-fee');
    deliveryFeeInput.oninput = () => {
      state.newOrderState.isManualDeliveryFee = true;
      state.newOrderState.deliveryFee = parseFloat(deliveryFeeInput.value) || 0;
      const noteEl = document.getElementById('new-order-delivery-note');
      noteEl.textContent = `Manual rate applied (Standard calculated: ₹${state.newOrderState.deliveryCalculated})`;
      recalcNewOrderPricing();
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

  // ---------------- Delivery Fee Calculation Rules (Requirement 8 & 10) ----------------
  const SOUTH_INDIA_STATES = new Set(['karnataka', 'kerala', 'andhra pradesh', 'telangana', 'puducherry']);
  const DELIVERY_RATES = {
    'Chennai': { tier1: 40.0, tier2: 42.0, tier3: 45.0, excess: 20.0 },
    'Tamil Nadu': { tier1: 65.0, tier2: 65.0, tier3: 70.0, excess: 30.0 },
    'South India': { tier1: 75.0, tier2: 78.0, tier3: 80.0, excess: 35.0 },
    'North/East/West': { tier1: 100.0, tier2: 150.0, tier3: 230.0, excess: 80.0 }
  };

  function computeDeliveryFeeClient(stateVal, distVal, totalBottles, applicableProductAmount = 0) {
    const st = (stateVal || '').trim().toLowerCase();
    const dist = (distVal || '').trim().toLowerCase();

    // Standard bottle weight: strictly 100g per bottle (Requirement 5)
    const weightGrams = totalBottles > 0 ? totalBottles * 100 : 0;
    let weightDisplay = '0g';
    if (weightGrams >= 1000) {
      weightDisplay = (weightGrams % 1000 === 0) 
        ? `${weightGrams / 1000}kg` 
        : `${(weightGrams / 1000).toFixed(2).replace(/\.?0+$/, '')}kg`;
    } else {
      weightDisplay = `${weightGrams}g`;
    }

    if (!st || !dist || totalBottles <= 0) {
      return {
        fee: 0,
        weightGrams,
        weightDisplay,
        zone: 'Unknown',
        slab: 'None',
        notes: (!st || !dist) ? 'Select state and district to calculate' : 'Select at least 1 bottle to calculate',
        isFree: false
      };
    }

    // Free delivery rule: STRICTLY applicable product amount > 800.0 (Requirement 8)
    if (applicableProductAmount > 800.0) {
      return {
        fee: 0,
        weightGrams,
        weightDisplay,
        zone: 'All India',
        slab: 'Free Delivery',
        notes: 'Free Delivery (Applicable product amount > ₹800)',
        isFree: true
      };
    }

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
      notes,
      isFree: false
    };
  }

  // Adjust flavour quantity button helper (Requirement 6)
  window.adjustFlavourQty = (flavourName, delta) => {
    const id = `qty-${flavourName.toLowerCase().replace(' ', '-')}`;
    const input = document.getElementById(id);
    if (!input) return;
    let val = Math.max(0, (parseInt(input.value) || 0) + delta);
    input.value = val;
    state.newOrderState.flavours[flavourName] = val;
    recalcNewOrderPricing();
  };

  // Authoritative Reactive New Order Pricing Recalculation (Requirements 2, 3, 4, 7, 8)
  function recalcNewOrderPricing() {
    const stateVal = document.getElementById('new-order-state').value;
    const distVal = document.getElementById('new-order-district').value;
    const totalBottles = Object.values(state.newOrderState.flavours).reduce((a, b) => a + b, 0);

    // Requirement 2: Fixed original bottle price ₹160
    const originalUnitPrice = 160.0;
    const discountPerBottle = (state.settings.discount_per_bottle !== undefined) 
      ? Number(state.settings.discount_per_bottle) 
      : 11.0;

    // Formulas:
    // Original Product Amount = Total Bottle Quantity * ₹160
    // Total Discount = Total Bottle Quantity * Discount Per Bottle
    // Discounted Product Amount = Original Product Amount - Total Discount
    const originalAmount = totalBottles * originalUnitPrice;
    const totalDiscount = totalBottles * discountPerBottle;
    const normalDiscountedAmount = originalAmount - totalDiscount;

    // Requirement 4: Optional Combo Offers (2 bottles for ₹289, 4 bottles for ₹559)
    const comboContainer = document.getElementById('combo-offers-container');
    const btnCombo2 = document.getElementById('btn-combo-2');
    const btnCombo4 = document.getElementById('btn-combo-4');

    if (totalBottles === 2) {
      if (comboContainer) comboContainer.style.display = 'block';
      if (btnCombo2) btnCombo2.style.display = 'inline-flex';
      if (btnCombo4) btnCombo4.style.display = 'none';
      if (state.newOrderState.comboSelected === '4_BOTTLE') {
        state.newOrderState.comboSelected = null;
      }
      if (btnCombo2) btnCombo2.classList.toggle('active', state.newOrderState.comboSelected === '2_BOTTLE');
    } else if (totalBottles === 4) {
      if (comboContainer) comboContainer.style.display = 'block';
      if (btnCombo4) btnCombo4.style.display = 'inline-flex';
      if (btnCombo2) btnCombo2.style.display = 'none';
      if (state.newOrderState.comboSelected === '2_BOTTLE') {
        state.newOrderState.comboSelected = null;
      }
      if (btnCombo4) btnCombo4.classList.toggle('active', state.newOrderState.comboSelected === '4_BOTTLE');
    } else {
      if (comboContainer) comboContainer.style.display = 'none';
      if (btnCombo2) btnCombo2.style.display = 'none';
      if (btnCombo4) btnCombo4.style.display = 'none';
      state.newOrderState.comboSelected = null;
      if (btnCombo2) btnCombo2.classList.remove('active');
      if (btnCombo4) btnCombo4.classList.remove('active');
    }

    let isComboApplied = false;
    let comboType = null;
    let applicableProductAmount = normalDiscountedAmount;

    if (state.newOrderState.comboSelected === '2_BOTTLE' && totalBottles === 2) {
      applicableProductAmount = 289.0;
      isComboApplied = true;
      comboType = '2_BOTTLE';
    } else if (state.newOrderState.comboSelected === '4_BOTTLE' && totalBottles === 4) {
      applicableProductAmount = 559.0;
      isComboApplied = true;
      comboType = '4_BOTTLE';
    }

    const calc = computeDeliveryFeeClient(stateVal, distVal, totalBottles, applicableProductAmount);

    // Update Blue Bill Summary Card (Requirement 7)
    // 1. Total number of bottles
    document.getElementById('new-order-bottles-count').textContent = totalBottles;
    // 2. Total consignment weight
    document.getElementById('new-order-weight-display').textContent = calc.weightDisplay;
    // 3. Original product amount
    document.getElementById('new-order-original-amount').textContent = `₹${originalAmount.toLocaleString('en-IN')}`;
    // 4. Discount per bottle
    document.getElementById('new-order-discount-per-bottle').textContent = `-₹${discountPerBottle}`;
    // 5. Total discount amount
    document.getElementById('new-order-total-discount').textContent = `-₹${totalDiscount.toLocaleString('en-IN')}`;
    // 6. Discounted / Applicable product amount
    document.getElementById('new-order-discounted-product-amount').textContent = `₹${applicableProductAmount.toLocaleString('en-IN')}`;

    // 7. Selected combo offer
    const rowSelectedCombo = document.getElementById('row-selected-combo');
    const comboDisplay = document.getElementById('new-order-selected-combo-display');
    if (isComboApplied) {
      if (rowSelectedCombo) rowSelectedCombo.style.display = 'flex';
      if (comboDisplay) {
        comboDisplay.textContent = (comboType === '2_BOTTLE' ? '2 Bottles for ₹289' : '4 Bottles for ₹559');
      }
    } else {
      if (rowSelectedCombo) rowSelectedCombo.style.display = 'none';
    }

    // 8. Delivery fee & Free Delivery (Requirement 8)
    const feeInput = document.getElementById('new-order-delivery-fee');
    const noteEl = document.getElementById('new-order-delivery-note');
    const freeDeliveryBadge = document.getElementById('new-order-free-delivery-badge');

    if (calc.isFree) {
      // Mandatory free delivery: overrides and disables manual fee input
      feeInput.value = 0;
      feeInput.disabled = true;
      state.newOrderState.deliveryFee = 0;
      state.newOrderState.deliveryCalculated = 0;
      if (freeDeliveryBadge) freeDeliveryBadge.style.display = 'inline-block';
      if (noteEl) noteEl.textContent = 'FREE DELIVERY APPLIED (Product amount exceeds ₹800)';
    } else {
      feeInput.disabled = false;
      if (freeDeliveryBadge) freeDeliveryBadge.style.display = 'none';
      if (totalBottles > 0 && stateVal && distVal) {
        state.newOrderState.deliveryCalculated = calc.fee;
        if (!state.newOrderState.isManualDeliveryFee) {
          feeInput.value = calc.fee;
          state.newOrderState.deliveryFee = calc.fee;
          state.newOrderState.deliveryNotes = calc.notes;
          if (noteEl) noteEl.textContent = `Zone: ${calc.zone} | Slab: ${calc.slab} (${calc.notes})`;
        } else {
          state.newOrderState.deliveryFee = parseFloat(feeInput.value) || 0;
          if (noteEl) noteEl.textContent = `Manual rate: ₹${feeInput.value} (Standard calculated: ₹${calc.fee})`;
        }
      } else {
        state.newOrderState.deliveryCalculated = 0;
        if (!state.newOrderState.isManualDeliveryFee) {
          feeInput.value = 0;
          state.newOrderState.deliveryFee = 0;
          state.newOrderState.deliveryNotes = '';
          if (noteEl) {
            noteEl.textContent = (!stateVal || !distVal) 
              ? 'Select state and district to calculate' 
              : 'Select at least 1 bottle to calculate';
          }
        }
      }
    }

    // 9. Final payable amount
    const deliveryFee = parseFloat(feeInput.value) || 0;
    const finalAmount = applicableProductAmount + deliveryFee;
    document.getElementById('new-order-final-amount').textContent = `₹${finalAmount.toLocaleString('en-IN')}`;
  }

  function updateFinalPricingDisplay() {
    recalcNewOrderPricing();
  }

  // Create Order Submission (Requirements 4, 8, 13)
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
      apply_combo: !!state.newOrderState.comboSelected,
      items
    };

    try {
      const res = await api.createOrder(payload);
      showToast(`Order ${res.order_id} created successfully!`);

      // Reset form to blank
      document.getElementById('form-new-order').reset();
      state.newOrderState.flavours = { 'Tomato': 0, 'Cheese': 0, 'Sour Cream': 0, 'Peri Peri': 0 };
      state.newOrderState.comboSelected = null;
      state.newOrderState.isManualDeliveryFee = false;
      ['Tomato', 'Cheese', 'Sour Cream', 'Peri Peri'].forEach(flv => {
        const id = `qty-${flv.toLowerCase().replace(' ', '-')}`;
        const input = document.getElementById(id);
        if (input) input.value = 0;
      });
      document.getElementById('new-order-delivery-fee').value = 0;
      document.getElementById('pincode-feedback').style.display = 'none';
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
    state.newOrderState.comboSelected = null;
    state.newOrderState.isManualDeliveryFee = false;
    ['Tomato', 'Cheese', 'Sour Cream', 'Peri Peri'].forEach(flv => {
      const id = `qty-${flv.toLowerCase().replace(' ', '-')}`;
      const input = document.getElementById(id);
      if (input) input.value = 0;
    });
    document.getElementById('new-order-delivery-fee').value = 0;
    const pinFb = document.getElementById('pincode-feedback');
    if (pinFb) pinFb.style.display = 'none';
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
      tbody.innerHTML = `<tr><td colspan="14" style="text-align:center; padding: 40px; color: var(--text-secondary);">No orders match the selected filters.</td></tr>`;
      return;
    }

    // Requirement 13: Do NOT display Created By and Edited By as visible columns in the main table!
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
          <td style="text-align: right;">
            <div class="three-dot-menu-wrapper">
              <button class="btn-three-dot" data-menu-id="${o.order_id}" title="Order Actions">
                <svg class="icon-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg>
              </button>
              <div class="three-dot-dropdown" id="dropdown-${o.order_id}">
                <div class="three-dot-item" data-action="edit" data-order-id="${o.order_id}">
                  <svg class="icon-svg" viewBox="0 0 24 24"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/></svg>
                  <span>Edit Order</span>
                </div>
                <div class="three-dot-item text-danger" data-action="delete" data-order-id="${o.order_id}">
                  <svg class="icon-svg" viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>
                  <span>Delete Order</span>
                </div>
              </div>
            </div>
          </td>
        </tr>
      `;
    }).join('');

    // Row click: opens details (Requirement 14)
    tbody.querySelectorAll('tr').forEach(row => {
      row.addEventListener('click', (e) => {
        // Prevent opening if clicked on dispatch toggle or 3-dot menu
        if (e.target.closest('.btn-dispatch-toggle') || e.target.closest('.three-dot-menu-wrapper')) {
          return;
        }
        openOrderDetails(row.dataset.orderId);
      });
    });

    // Dispatch Toggle click listener (Requirement 16)
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

    // Three Dot Menu listeners (Requirement 15)
    tbody.querySelectorAll('.btn-three-dot').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const oid = btn.dataset.menuId;
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

  // Date Presets & Custom Range (Requirement 12)
  const dateFilterSelect = document.getElementById('filter-order-date');
  const customDateContainer = document.getElementById('custom-date-container');
  const dateFromInput = document.getElementById('filter-date-from');
  const dateToInput = document.getElementById('filter-date-to');

  dateFilterSelect.addEventListener('change', (e) => {
    const val = e.target.value;
    state.currentOrderFilter.date_filter = val;
    if (val === 'Custom') {
      customDateContainer.style.display = 'inline-flex';
    } else {
      customDateContainer.style.display = 'none';
      state.currentOrderFilter.date_from = '';
      state.currentOrderFilter.date_to = '';
    }
    loadOrders();
  });

  dateFromInput?.addEventListener('change', (e) => {
    state.currentOrderFilter.date_from = e.target.value;
    loadOrders();
  });

  dateToInput?.addEventListener('change', (e) => {
    state.currentOrderFilter.date_to = e.target.value;
    loadOrders();
  });

  document.getElementById('filter-order-sort').addEventListener('change', (e) => {
    state.currentOrderFilter.sort_by = e.target.value;
    loadOrders();
  });

  // Order CSV Export
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

    downloadCSV(`POPCONE_Orders_Export_${new Date().toISOString().slice(0, 10)}.csv`, headers, rows);
  });

  // ---------------- 4. ORDER DETAILS MODAL ----------------
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
      const prodAmtDisplay = o.is_combo 
        ? `₹${o.product_amount.toLocaleString('en-IN')} (${o.combo_type === '2_BOTTLE' ? '2-Bottle Combo' : '4-Bottle Combo'})`
        : (o.total_discount > 0 
          ? `₹${o.product_amount.toLocaleString('en-IN')} (Discount: -₹${o.total_discount})`
          : `₹${o.product_amount.toLocaleString('en-IN')}`);
      document.getElementById('detail-product-amount').textContent = prodAmtDisplay;
      document.getElementById('detail-delivery-fee').textContent = o.delivery_fee === 0 ? '₹0 (Free Delivery)' : `₹${o.delivery_fee.toLocaleString('en-IN')}`;
      document.getElementById('detail-final-amount').textContent = `₹${o.final_amount.toLocaleString('en-IN')}`;
      document.getElementById('detail-payment-method').textContent = o.payment;

      // Requirement 13 & 14: Inside Order Details card, show small but noticeable audit information
      document.getElementById('detail-created-info').textContent = `${o.created_by} (${o.created_at})`;
      document.getElementById('detail-edited-info').textContent = `${o.edited_by} (${o.edited_at})`;

      const dispatchBadge = document.getElementById('detail-dispatch-badge');
      dispatchBadge.textContent = o.dispatch_state;
      dispatchBadge.className = `badge ${o.dispatch_state === 'DISPATCHED' ? 'badge-dispatched' : 'badge-placed'}`;

      // Ordered Products: ONLY ordered flavours (> 0 quantity)
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

  // ---------------- 5. EDIT ORDER MODAL ----------------
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

    const weightGrams = totalBottles * 100;
    let weightDisplay = '0g';
    if (weightGrams >= 1000) {
      weightDisplay = (weightGrams % 1000 === 0) 
        ? `${weightGrams / 1000}kg` 
        : `${(weightGrams / 1000).toFixed(2).replace(/\.?0+$/, '')}kg`;
    } else {
      weightDisplay = `${weightGrams}g`;
    }

    document.getElementById('edit-total-bottles').textContent = totalBottles;
    document.getElementById('edit-total-weight').textContent = weightDisplay;

    // Requirement 20: Maintain historical unit price
    const histPrice = currentEditingOrder.unit_price;
    const productAmount = totalBottles * histPrice;
    const feeInput = document.getElementById('edit-delivery-fee');

    let deliveryFee = 0;
    if (productAmount > 800.0) {
      feeInput.value = 0;
      feeInput.disabled = true;
      deliveryFee = 0;
    } else {
      feeInput.disabled = false;
      deliveryFee = parseFloat(feeInput.value) || 0;
    }
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

  // ---------------- 6. DELETE ORDER MODAL (Requirement 15) ----------------
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
      if (state.activeTab === 'analytics') loadAnalytics();
    } catch (err) {
      showToast(err.message || 'Failed to delete order', 'danger');
    }
  });

  // ---------------- 7. INVENTORY PAGE ----------------
  async function loadInventory() {
    try {
      const data = await api.getInventory();
      const stockGrid = document.getElementById('inventory-stock-grid');
      
      // Stock Cards (Requirement 6: 0 stock on reset, low stock <= 20)
      stockGrid.innerHTML = data.stocks.map(s => {
        const isLow = s.current_stock <= s.low_stock_threshold;
        const statusHtml = isLow
          ? `<span class="stock-card-status danger"><svg class="icon-svg" style="width:14px;height:14px;" viewBox="0 0 24 24"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg> Low Stock (&le; 20)</span>`
          : `<span class="stock-card-status safe"><svg class="icon-svg" style="width:14px;height:14px;" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg> In Stock</span>`;

        return `
          <div class="stock-card ${isLow ? 'low-stock' : ''}">
            <div class="stock-card-flavour">${s.flavour}</div>
            <div>
              <span class="stock-card-qty">${s.current_stock}</span>
              <span class="stock-card-unit">bottles</span>
            </div>
            ${statusHtml}
          </div>
        `;
      }).join('');

      // Requirement 5: Do NOT display "Moved By" in the inventory history!
      // Columns: Date/Time, Flavour, Type, Change, Reference
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
            </tr>
          `;
        }).join('');
      } else {
        movementsTbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 28px; color: var(--text-secondary);">No movements recorded yet</td></tr>`;
      }

    } catch (err) {
      console.error('Error loading inventory:', err);
      showToast('Failed to load inventory', 'danger');
    }
  }

  // Stock Movement Modal (Stock Added / Adjustment) - Admin (Ashish) Only
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

  // Reset Inventory Modal - Admin (Ashish) Only
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

  // ---------------- 8. ANALYTICS PAGE (Requirement 10 & 11) ----------------
  // Mode switcher listeners
  ['weekly', 'monthly', 'annual'].forEach(mode => {
    document.getElementById(`btn-analytics-mode-${mode}`)?.addEventListener('click', () => {
      setAnalyticsMode(mode);
    });
  });

  function setAnalyticsMode(mode) {
    state.analyticsMode = mode;
    ['weekly', 'monthly', 'annual'].forEach(m => {
      const btn = document.getElementById(`btn-analytics-mode-${m}`);
      btn?.classList.toggle('active', m === mode);
      const sec = document.getElementById(`analytics-section-${m}`);
      if (sec) sec.style.display = m === mode ? 'block' : 'none';
    });

    // Toggle Month Selector visibility
    const monthWrapper = document.getElementById('analytics-month-select-wrapper');
    if (monthWrapper) monthWrapper.style.display = mode === 'monthly' ? 'flex' : 'none';

    // Update CSV export button label
    updateAnalyticsExportLabel();

    // Re-render UI for new mode
    renderAnalyticsView();
  }

  function updateAnalyticsExportLabel() {
    const label = document.getElementById('btn-export-analytics-csv-label');
    if (!label) return;
    if (state.analyticsMode === 'monthly') {
      const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      label.textContent = `Export ${monthNames[state.analyticsMonth - 1]} ${state.analyticsYear} CSV`;
    } else if (state.analyticsMode === 'annual') {
      label.textContent = `Export ${state.analyticsYear} Annual CSV`;
    } else {
      label.textContent = `Export Weekly CSV (${state.analyticsYear})`;
    }
  }

  // Month selector listener
  document.getElementById('analytics-month-select')?.addEventListener('change', (e) => {
    state.analyticsMonth = parseInt(e.target.value);
    updateAnalyticsExportLabel();
    renderAnalyticsView();
  });

  async function loadAnalytics() {
    try {
      const year = state.analyticsYear;
      const data = await api.getAnalytics(year, state.analyticsMonth);
      state.analyticsData = data;

      // Populate year selector
      const yearSelect = document.getElementById('analytics-year-select');
      yearSelect.innerHTML = data.available_years.map(y => 
        `<option value="${y}" ${y === year ? 'selected' : ''}>${y}</option>`
      ).join('');

      yearSelect.onchange = () => {
        state.analyticsYear = parseInt(yearSelect.value);
        updateAnalyticsExportLabel();
        loadAnalytics();
      };

      const monthSelect = document.getElementById('analytics-month-select');
      if (monthSelect) monthSelect.value = state.analyticsMonth;

      updateAnalyticsExportLabel();
      renderAnalyticsView();

    } catch (err) {
      console.error('Error loading analytics:', err);
      showToast('Failed to load analytics data', 'danger');
    }
  }

  function renderAnalyticsView() {
    const data = state.analyticsData;
    if (!data) return;

    const mode = state.analyticsMode;
    const monthIdx = state.analyticsMonth;
    const selectedMonth = data.monthly_report.find(m => m.month_num === monthIdx) || {
      month_name: 'Month', total_orders: 0, total_bottles: 0, revenue: 0,
      tomato: 0, tomato_revenue: 0, cheese: 0, cheese_revenue: 0,
      sour_cream: 0, sour_cream_revenue: 0, peri_peri: 0, peri_peri_revenue: 0,
      most_purchased_flavour: 'None'
    };

    // Update Top KPIs depending on Active Mode
    if (mode === 'monthly') {
      document.getElementById('analytics-kpi-revenue-label').textContent = `${selectedMonth.month_name} Revenue`;
      document.getElementById('analytics-kpi-revenue-subtext').textContent = `${selectedMonth.month_name} ${state.analyticsYear}`;
      document.getElementById('analytics-total-revenue').textContent = `₹${selectedMonth.revenue.toLocaleString('en-IN')}`;
      document.getElementById('analytics-total-bottles').textContent = selectedMonth.total_bottles;
      document.getElementById('analytics-total-orders').textContent = selectedMonth.total_orders;
      document.getElementById('analytics-most-purchased').textContent = selectedMonth.most_purchased_flavour !== 'None'
        ? selectedMonth.most_purchased_flavour
        : 'None';
    } else if (mode === 'annual') {
      const ann = data.annual_report;
      document.getElementById('analytics-kpi-revenue-label').textContent = 'Annual Revenue';
      document.getElementById('analytics-kpi-revenue-subtext').textContent = `Full Year ${state.analyticsYear}`;
      document.getElementById('analytics-total-revenue').textContent = `₹${ann.total_revenue.toLocaleString('en-IN')}`;
      document.getElementById('analytics-total-bottles').textContent = ann.total_bottles;
      document.getElementById('analytics-total-orders').textContent = ann.total_orders;
      document.getElementById('analytics-most-purchased').textContent = ann.most_purchased_flavour !== 'None'
        ? ann.most_purchased_flavour
        : 'None';
    } else {
      // Weekly mode
      const totalWeeklyRev = data.weekly_report.reduce((acc, w) => acc + w.revenue, 0);
      const totalWeeklyBottles = data.weekly_report.reduce((acc, w) => acc + w.total_bottles, 0);
      document.getElementById('analytics-kpi-revenue-label').textContent = 'Weekly Cumulative Revenue';
      document.getElementById('analytics-kpi-revenue-subtext').textContent = `Weeks in ${state.analyticsYear}`;
      document.getElementById('analytics-total-revenue').textContent = `₹${totalWeeklyRev.toLocaleString('en-IN')}`;
      document.getElementById('analytics-total-bottles').textContent = totalWeeklyBottles;
      document.getElementById('analytics-total-orders').textContent = data.overview.total_orders;
      document.getElementById('analytics-most-purchased').textContent = data.overview.most_purchased_flavour !== 'None'
        ? data.overview.most_purchased_flavour
        : 'None';
    }

    // 1. Monthly Section Content
    document.getElementById('analytics-month-detail-title').textContent = `${selectedMonth.month_name} ${state.analyticsYear} - Flavour Sales`;
    const mFlavourTbody = document.getElementById('analytics-selected-month-flavour-tbody');
    const mTotBottles = selectedMonth.total_bottles || 1;
    const flavours = [
      { name: 'Tomato', qty: selectedMonth.tomato, rev: selectedMonth.tomato_revenue },
      { name: 'Cheese', qty: selectedMonth.cheese, rev: selectedMonth.cheese_revenue },
      { name: 'Sour Cream', qty: selectedMonth.sour_cream, rev: selectedMonth.sour_cream_revenue },
      { name: 'Peri Peri', qty: selectedMonth.peri_peri, rev: selectedMonth.peri_peri_revenue }
    ];

    mFlavourTbody.innerHTML = flavours.map(f => {
      const share = selectedMonth.total_bottles > 0 ? Math.round((f.qty / mTotBottles) * 100) : 0;
      return `
        <tr>
          <td><strong>${f.name}</strong></td>
          <td>${f.qty}</td>
          <td>₹${f.rev.toLocaleString('en-IN')}</td>
          <td>${share}%</td>
        </tr>
      `;
    }).join('') + `
      <tr style="background:#F8FAFC; font-weight:700;">
        <td>TOTAL</td>
        <td>${selectedMonth.total_bottles}</td>
        <td>₹${selectedMonth.revenue.toLocaleString('en-IN')}</td>
        <td>100%</td>
      </tr>
    `;

    // 12-month table
    const monthlyTbody = document.getElementById('analytics-monthly-tbody');
    monthlyTbody.innerHTML = data.monthly_report.map(m => {
      const isSelected = m.month_num === state.analyticsMonth;
      return `
        <tr style="${isSelected ? 'background: #EFF6FF; font-weight: 700;' : ''}" data-month-select="${m.month_num}">
          <td><strong>${m.month_name}</strong> ${isSelected ? '<span class="badge badge-paid">Selected</span>' : ''}</td>
          <td>${m.total_orders}</td>
          <td>${m.tomato}</td>
          <td>${m.cheese}</td>
          <td>${m.sour_cream}</td>
          <td>${m.peri_peri}</td>
          <td><strong>${m.total_bottles}</strong></td>
          <td>₹${m.revenue.toLocaleString('en-IN')}</td>
          <td><strong>${m.most_purchased_flavour}</strong></td>
        </tr>
      `;
    }).join('');

    // Allow clicking a row in 12-month table to select that month
    monthlyTbody.querySelectorAll('tr').forEach(row => {
      row.style.cursor = 'pointer';
      row.addEventListener('click', () => {
        const mNum = parseInt(row.dataset.monthSelect);
        if (mNum) {
          state.analyticsMonth = mNum;
          const monthSelect = document.getElementById('analytics-month-select');
          if (monthSelect) monthSelect.value = mNum;
          updateAnalyticsExportLabel();
          renderAnalyticsView();
        }
      });
    });

    // 2. Weekly Section Content
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
      weeklyTbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 28px; color:var(--text-secondary);">No weekly data recorded for ${state.analyticsYear}</td></tr>`;
    }

    // 3. Annual Section Content
    const ann = data.annual_report;
    const annualTbody = document.getElementById('analytics-annual-tbody');
    annualTbody.innerHTML = `
      <tr style="background:#FFF9C4; font-weight:700;">
        <td><strong>${ann.year} TOTAL</strong></td>
        <td>${ann.total_orders}</td>
        <td>${ann.tomato_bottles} (₹${ann.tomato_revenue.toLocaleString('en-IN')})</td>
        <td>${ann.cheese_bottles} (₹${ann.cheese_revenue.toLocaleString('en-IN')})</td>
        <td>${ann.sour_cream_bottles} (₹${ann.sour_cream_revenue.toLocaleString('en-IN')})</td>
        <td>${ann.peri_peri_bottles} (₹${ann.peri_peri_revenue.toLocaleString('en-IN')})</td>
        <td><strong>${ann.total_bottles}</strong></td>
        <td><strong style="color:var(--primary-blue); font-size:15px;">₹${ann.total_revenue.toLocaleString('en-IN')}</strong></td>
        <td><span class="badge badge-paid">${ann.most_purchased_flavour}</span></td>
      </tr>
    `;
  }

  // Unified CSV Export for active analytics view (Requirement 11)
  document.getElementById('btn-export-analytics-csv')?.addEventListener('click', () => {
    const data = state.analyticsData;
    if (!data) return;

    if (state.analyticsMode === 'monthly') {
      const monthIdx = state.analyticsMonth;
      const m = data.monthly_report.find(x => x.month_num === monthIdx);
      if (!m) return;
      const headers = ['Month', 'Year', 'Total Orders', 'Tomato Bottles', 'Tomato Revenue', 'Cheese Bottles', 'Cheese Revenue', 'Sour Cream Bottles', 'Sour Cream Revenue', 'Peri Peri Bottles', 'Peri Peri Revenue', 'Total Bottles', 'Total Revenue', 'Top Flavour'];
      const rows = [[
        `"${m.month_name}"`, state.analyticsYear, m.total_orders,
        m.tomato, m.tomato_revenue, m.cheese, m.cheese_revenue,
        m.sour_cream, m.sour_cream_revenue, m.peri_peri, m.peri_peri_revenue,
        m.total_bottles, m.revenue, `"${m.most_purchased_flavour}"`
      ]];
      downloadCSV(`POPCONE_${m.month_name}_${state.analyticsYear}_Report.csv`, headers, rows);
    } else if (state.analyticsMode === 'annual') {
      const ann = data.annual_report;
      const headers = ['Year', 'Total Orders', 'Tomato Bottles', 'Tomato Revenue', 'Cheese Bottles', 'Cheese Revenue', 'Sour Cream Bottles', 'Sour Cream Revenue', 'Peri Peri Bottles', 'Peri Peri Revenue', 'Total Bottles', 'Total Revenue', 'Top Flavour'];
      const rows = [[
        ann.year, ann.total_orders,
        ann.tomato_bottles, ann.tomato_revenue, ann.cheese_bottles, ann.cheese_revenue,
        ann.sour_cream_bottles, ann.sour_cream_revenue, ann.peri_peri_bottles, ann.peri_peri_revenue,
        ann.total_bottles, ann.total_revenue, `"${ann.most_purchased_flavour}"`
      ]];
      downloadCSV(`POPCONE_Annual_Report_${state.analyticsYear}.csv`, headers, rows);
    } else {
      // Weekly export
      const headers = ['Week', 'Tomato Bottles', 'Tomato Revenue', 'Cheese Bottles', 'Cheese Revenue', 'Sour Cream Bottles', 'Sour Cream Revenue', 'Peri Peri Bottles', 'Peri Peri Revenue', 'Total Bottles', 'Total Revenue', 'Top Flavour'];
      const rows = data.weekly_report.map(w => [
        `"${w.week_label}"`, w.tomato, w.tomato_revenue, w.cheese, w.cheese_revenue,
        w.sour_cream, w.sour_cream_revenue, w.peri_peri, w.peri_peri_revenue,
        w.total_bottles, w.revenue, `"${w.most_purchased_flavour}"`
      ]);
      downloadCSV(`POPCONE_Weekly_Report_${state.analyticsYear}.csv`, headers, rows);
    }
  });

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

  // Initial Setup on Page Load
  updateAuthUI();
});
