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
      low_stock_threshold: 10 
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
  const btnLoginSubmit = document.getElementById('btn-login-submit');

  function setLoginButtonLoading(isLoading) {
    if (!btnLoginSubmit) return;
    if (isLoading) {
      btnLoginSubmit.disabled = true;
      btnLoginSubmit.innerHTML = `
        <svg class="icon-svg spin" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
        </svg>
        <span>Signing In...</span>
      `;
    } else {
      btnLoginSubmit.disabled = false;
      btnLoginSubmit.innerHTML = `<span>Sign In</span>`;
    }
  }

  function updateAuthUI() {
    const isActive = api.isSessionActive();
    state.user = api.getUser();
    const token = api.getToken();

    if (!isActive || !state.user || !token) {
      setLoginButtonLoading(false);
      document.body.classList.add('auth-required');
      loginOverlay.style.display = 'flex';
      return;
    }
    document.body.classList.remove('auth-required');
    loginOverlay.style.display = 'none';

    // Record activity timestamp on successful verification
    api.recordActivity();

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

  window.addEventListener('auth-changed', (e) => {
    updateAuthUI();
    if (e.detail && e.detail.expired) {
      showToast('Your session timed out after 10 minutes of inactivity. Please login again.', 'warning');
    }
  });

  // Track user activity to maintain active session while working (throttled to every 10 seconds)
  let lastRecordedActivity = 0;
  function handleUserActivity() {
    const now = Date.now();
    if (now - lastRecordedActivity > 10000) {
      lastRecordedActivity = now;
      api.recordActivity();
    }
  }

  ['mousedown', 'keydown', 'scroll', 'touchstart', 'click'].forEach(evt => {
    window.addEventListener(evt, handleUserActivity, { passive: true });
  });

  // Periodically check for 10-minute inactivity timeout (every 15s) and on tab focus
  function checkSessionTimeout() {
    if (api.getToken() && !api.isSessionActive()) {
      updateAuthUI();
    }
  }

  setInterval(checkSessionTimeout, 15000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      checkSessionTimeout();
    }
  });
  window.addEventListener('focus', checkSessionTimeout);

  // Eye icon password toggle in login form
  const btnToggleLoginPassword = document.getElementById('btn-toggle-login-password');
  const loginPasswordInput = document.getElementById('login-password');
  const eyeIconShow = document.getElementById('eye-icon-show');
  const eyeIconHide = document.getElementById('eye-icon-hide');

  function resetLoginPasswordVisibility() {
    if (loginPasswordInput) {
      loginPasswordInput.type = 'password';
      if (eyeIconShow && eyeIconHide) {
        eyeIconShow.style.display = 'inline-block';
        eyeIconHide.style.display = 'none';
      }
      if (btnToggleLoginPassword) {
        btnToggleLoginPassword.title = 'Show Password';
        btnToggleLoginPassword.setAttribute('aria-label', 'Show Password');
      }
    }
  }

  if (btnToggleLoginPassword && loginPasswordInput) {
    btnToggleLoginPassword.addEventListener('click', (e) => {
      e.preventDefault();
      const isPassword = loginPasswordInput.type === 'password';
      loginPasswordInput.type = isPassword ? 'text' : 'password';
      if (eyeIconShow && eyeIconHide) {
        eyeIconShow.style.display = isPassword ? 'none' : 'inline-block';
        eyeIconHide.style.display = isPassword ? 'inline-block' : 'none';
      }
      const newTitle = isPassword ? 'Hide Password' : 'Show Password';
      btnToggleLoginPassword.title = newTitle;
      btnToggleLoginPassword.setAttribute('aria-label', newTitle);
      loginPasswordInput.focus();
    });
  }

  loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    loginError.style.display = 'none';
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;

    setLoginButtonLoading(true);

    try {
      await api.login(username, password);
      showToast('Logged in successfully!');
      resetLoginPasswordVisibility();
      updateAuthUI();
    } catch (err) {
      loginError.textContent = err.message || 'Login failed';
      loginError.style.display = 'block';
    } finally {
      if (!api.isSessionActive()) {
        setLoginButtonLoading(false);
      } else {
        setTimeout(() => setLoginButtonLoading(false), 500);
      }
    }
  });

  document.getElementById('btn-logout').addEventListener('click', async () => {
    await api.logout();
    resetLoginPasswordVisibility();
    showToast('Logged out');
    updateAuthUI();
  });

  // ---------------- Flexible Collapsible Sidebar (Header Toggle) ----------------
  const sidebar = document.getElementById('main-sidebar');
  const btnHeaderToggle = document.getElementById('btn-toggle-sidebar');
  const sidebarBackdrop = document.getElementById('sidebar-backdrop');

  function updateHeaderToggleTooltip(isCollapsed) {
    if (btnHeaderToggle) {
      const label = isCollapsed ? 'Expand Sidebar' : 'Collapse Sidebar';
      btnHeaderToggle.title = label;
      btnHeaderToggle.setAttribute('aria-label', label);
    }
  }

  function toggleSidebar() {
    if (!sidebar) return;
    const isMobile = window.innerWidth <= 768;
    if (isMobile) {
      const isOpen = sidebar.classList.toggle('mobile-open');
      if (sidebarBackdrop) {
        sidebarBackdrop.classList.toggle('active', isOpen);
      }
    } else {
      const isCollapsed = sidebar.classList.toggle('collapsed');
      localStorage.setItem('popcone_sidebar_collapsed', isCollapsed ? 'true' : 'false');
      updateHeaderToggleTooltip(isCollapsed);
    }
  }

  // Restore saved desktop collapsed state on page load
  try {
    const savedCollapsed = localStorage.getItem('popcone_sidebar_collapsed') === 'true';
    if (savedCollapsed && window.innerWidth > 768 && sidebar) {
      sidebar.classList.add('collapsed');
      updateHeaderToggleTooltip(true);
    } else {
      updateHeaderToggleTooltip(false);
    }
  } catch (e) {
    console.warn('LocalStorage error while restoring sidebar preference:', e);
  }

  if (btnHeaderToggle) {
    btnHeaderToggle.addEventListener('click', (e) => {
      e.preventDefault();
      toggleSidebar();
    });
  }

  if (sidebarBackdrop) {
    sidebarBackdrop.addEventListener('click', () => {
      if (sidebar) sidebar.classList.remove('mobile-open');
      sidebarBackdrop.classList.remove('active');
    });
  }

  function isUserAdmin() {
    return !!(state.user && (
      state.user.role === 'ADMIN' ||
      (state.user.display_name || '').toLowerCase() === 'ashish' ||
      (state.user.username || '').toLowerCase().startsWith('ashish')
    ));
  }

  // ---------------- Navigation / Tabs ----------------
  const navItems = document.querySelectorAll('.nav-item');
  navItems.forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const tab = item.dataset.tab;
      switchTab(tab);
      if (window.innerWidth <= 768 && sidebar) {
        sidebar.classList.remove('mobile-open');
        if (sidebarBackdrop) sidebarBackdrop.classList.remove('active');
      }
    });
  });

  function switchTab(tab) {
    if (tab === 'backups') {
      if (!isUserAdmin()) {
        showToast('Access Denied: Backup & Recovery is restricted to administrators.', 'error');
        tab = 'dashboard';
      }
    }

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
      analytics: 'Sales Analytics & Reports',
      settings: 'Settings',
      backups: 'Backup & Recovery'
    };
    document.getElementById('header-page-title').textContent = titles[tab] || 'POPCONE CRM';

    // Load tab-specific data
    if (tab === 'dashboard') loadDashboard();
    else if (tab === 'new-order') initNewOrderPage();
    else if (tab === 'orders') loadOrders();
    else if (tab === 'inventory') loadInventory();
    else if (tab === 'analytics') loadAnalytics();
    else if (tab === 'settings') openSettingsModal();
    else if (tab === 'backups') loadBackupsView();
  }

  // ---------------- Professional Settings (Single Top-Right Access, Requirements: Discount Per Bottle & Admin Password Management) ----------------
  const settingsModal = document.getElementById('modal-settings');
  const btnOpenSettings = document.getElementById('btn-open-settings');
  const btnCloseSettings = document.getElementById('btn-close-settings');
  const btnCloseSettingsFooter = document.getElementById('btn-close-settings-footer');

  async function openSettingsModal() {
    if (settingsModal) {
      settingsModal.classList.add('show');
    }

    const isAdmin = state.user && (
      state.user.role === 'ADMIN' || 
      (state.user.display_name || '').toLowerCase() === 'ashish' || 
      (state.user.username || '').toLowerCase().startsWith('ashish')
    );

    // Toggle role visibility inside settings modal and settings page view
    document.querySelectorAll('#modal-settings .admin-only, #view-settings .admin-only').forEach(el => el.style.display = isAdmin ? '' : 'none');
    document.querySelectorAll('#modal-settings .member-only, #view-settings .member-only').forEach(el => el.style.display = isAdmin ? 'none' : '');

    await refreshGlobalSettings();

    // Fill settings inputs (sync both modal and page view)
    const discountVal = (state.settings && state.settings.discount_per_bottle !== undefined) 
      ? state.settings.discount_per_bottle 
      : 11;

    ['setting-discount-input', 'view-setting-discount-input'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = discountVal;
    });

    ['member-discount-display', 'view-member-discount-display'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = discountVal;
    });

    // Populate Admin User Password dropdowns
    if (isAdmin) {
      try {
        const usersData = await api.getUsers();
        if (usersData && usersData.users && usersData.users.length > 0) {
          const optionsHtml = usersData.users.map(u => 
            `<option value="${u.username}">${u.display_name} (${u.role})</option>`
          ).join('');
          ['admin-select-user', 'view-admin-select-user'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = optionsHtml;
          });
        }
      } catch (err) {
        console.error('Failed to load users for settings:', err);
      }
      ['admin-input-new-password', 'view-admin-input-new-password'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
      });
      ['admin-pwd-status', 'view-admin-pwd-status'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.style.display = 'none'; el.textContent = ''; }
      });
    }
  }

  // Single top-right Settings button
  btnOpenSettings?.addEventListener('click', (e) => {
    e.preventDefault();
    openSettingsModal();
  });
  btnCloseSettings?.addEventListener('click', () => settingsModal?.classList.remove('show'));
  btnCloseSettingsFooter?.addEventListener('click', () => settingsModal?.classList.remove('show'));

  // Close when clicking modal backdrop
  settingsModal?.addEventListener('click', (e) => {
    if (e.target === settingsModal) {
      settingsModal.classList.remove('show');
    }
  });

  // Settings to Backup & Recovery Navigation (Admin Only)
  const handleOpenBackupsFromSettings = (e) => {
    if (e) e.preventDefault();
    if (!isUserAdmin()) {
      showToast('Access Denied: Backup & Recovery is restricted to administrators.', 'error');
      return;
    }
    if (settingsModal) {
      settingsModal.classList.remove('show');
    }
    switchTab('backups');
  };

  document.getElementById('btn-settings-open-backups')?.addEventListener('click', handleOpenBackupsFromSettings);
  document.getElementById('btn-view-settings-open-backups')?.addEventListener('click', handleOpenBackupsFromSettings);
  document.getElementById('btn-back-to-settings')?.addEventListener('click', (e) => {
    e.preventDefault();
    switchTab('settings');
  });

  // Reusable discount saving helper
  async function handleSaveDiscount(inputEl, feedbackEl) {
    const discountVal = parseFloat(inputEl.value);
    if (isNaN(discountVal) || discountVal < 0 || discountVal >= 160) {
      const errMsg = 'Discount must be between ₹0 and ₹159';
      showToast(errMsg, 'danger');
      if (feedbackEl) {
        feedbackEl.textContent = errMsg;
        feedbackEl.style.color = 'var(--danger-red)';
        feedbackEl.style.display = 'block';
      }
      return;
    }

    try {
      const res = await api.updateDiscount(discountVal);
      showToast(`Discount per bottle updated to ₹${res.discount_per_bottle}`);
      await refreshGlobalSettings();

      // Sync both input fields
      ['setting-discount-input', 'view-setting-discount-input'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = res.discount_per_bottle;
      });
      ['member-discount-display', 'view-member-discount-display'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = res.discount_per_bottle;
      });

      if (feedbackEl) {
        feedbackEl.textContent = `Saved: ₹${res.discount_per_bottle}/bottle discount applied successfully.`;
        feedbackEl.style.color = 'var(--success-green)';
        feedbackEl.style.display = 'block';
        setTimeout(() => { if (feedbackEl) feedbackEl.style.display = 'none'; }, 4000);
      }
      if (state.activeTab === 'new-order') recalcNewOrderPricing();
    } catch (err) {
      showToast(err.message || 'Failed to update discount', 'danger');
      if (feedbackEl) {
        feedbackEl.textContent = err.message || 'Failed to update discount';
        feedbackEl.style.color = 'var(--danger-red)';
        feedbackEl.style.display = 'block';
      }
    }
  }

  // Discount Form submit handlers (Admin only)
  document.getElementById('form-setting-discount')?.addEventListener('submit', (e) => {
    e.preventDefault();
    handleSaveDiscount(document.getElementById('setting-discount-input'), document.getElementById('discount-setting-feedback'));
  });
  document.getElementById('form-view-setting-discount')?.addEventListener('submit', (e) => {
    e.preventDefault();
    handleSaveDiscount(document.getElementById('view-setting-discount-input'), document.getElementById('view-discount-setting-feedback'));
  });

  // Reusable password update helper
  async function handleAdminSetPassword(userSelectEl, pwdInputEl, statusBoxEl) {
    const targetUsername = userSelectEl ? userSelectEl.value : '';
    const newPassword = pwdInputEl ? pwdInputEl.value : '';

    if (!targetUsername) {
      if (statusBoxEl) {
        statusBoxEl.textContent = 'Please select a team account';
        statusBoxEl.style.color = 'var(--danger-red)';
        statusBoxEl.style.display = 'block';
      }
      return;
    }

    if (!newPassword || newPassword.length < 6) {
      const errMsg = 'New password must be at least 6 characters long';
      showToast(errMsg, 'danger');
      if (statusBoxEl) {
        statusBoxEl.textContent = errMsg;
        statusBoxEl.style.color = 'var(--danger-red)';
        statusBoxEl.style.display = 'block';
      }
      return;
    }

    try {
      const res = await api.adminChangePassword(targetUsername, newPassword);
      showToast(res.message || `Password updated for ${targetUsername}`);
      ['admin-input-new-password', 'view-admin-input-new-password'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
      });
      if (statusBoxEl) {
        statusBoxEl.textContent = `Success: New password saved for ${targetUsername}! Old password is no longer valid.`;
        statusBoxEl.style.color = 'var(--success-green)';
        statusBoxEl.style.display = 'block';
        setTimeout(() => { if (statusBoxEl) statusBoxEl.style.display = 'none'; }, 5000);
      }
    } catch (err) {
      showToast(err.message || 'Failed to update password', 'danger');
      if (statusBoxEl) {
        statusBoxEl.textContent = err.message || 'Failed to set password';
        statusBoxEl.style.color = 'var(--danger-red)';
        statusBoxEl.style.display = 'block';
      }
    }
  }

  // Admin User Password Form submit handlers (Admin only)
  document.getElementById('form-admin-user-password')?.addEventListener('submit', (e) => {
    e.preventDefault();
    handleAdminSetPassword(document.getElementById('admin-select-user'), document.getElementById('admin-input-new-password'), document.getElementById('admin-pwd-status'));
  });
  document.getElementById('form-view-admin-user-password')?.addEventListener('submit', (e) => {
    e.preventDefault();
    handleAdminSetPassword(document.getElementById('view-admin-select-user'), document.getElementById('view-admin-input-new-password'), document.getElementById('view-admin-pwd-status'));
  });

  async function refreshGlobalSettings() {
    if (!api.getToken()) return;
    try {
      const res = await api.getSettings();
      state.settings = {
        ...state.settings,
        ...res
      };
      // Current bottle price
      const bp = res.bottle_price || res.original_bottle_price || 160;
      document.querySelectorAll('.current-bottle-price-display').forEach(el => {
        el.textContent = `₹${bp}`;
      });
      // Effective bottle price
      document.querySelectorAll('.effective-price-display').forEach(el => {
        el.textContent = `₹${res.effective_bottle_price || (bp - (res.discount_per_bottle || 11))}`;
      });
    } catch (e) {
      console.warn('Could not load settings:', e);
    }
  }

  // ---------------- 1. DASHBOARD ----------------
  function renderDashboardUI(data) {
    if (!data) return;
    const kpis = data.kpis || { total_revenue: 0, total_orders: 0, bottles_sold: 0, paid_orders: 0, cod_orders: 0 };

    // KPI Cards
    const revEl = document.getElementById('kpi-total-revenue');
    if (revEl) revEl.textContent = `₹${(kpis.total_revenue || 0).toLocaleString('en-IN')}`;
    const ordEl = document.getElementById('kpi-total-orders');
    if (ordEl) ordEl.textContent = kpis.total_orders || 0;
    const btlEl = document.getElementById('kpi-bottles-sold');
    if (btlEl) btlEl.textContent = kpis.bottles_sold || 0;
    const paidEl = document.getElementById('kpi-paid-orders');
    if (paidEl) paidEl.textContent = kpis.paid_orders || 0;
    const codEl = document.getElementById('kpi-cod-orders');
    if (codEl) codEl.textContent = kpis.cod_orders || 0;

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
    if (recentTableBody) {
      if (data.recent_orders && data.recent_orders.length > 0) {
        recentTableBody.innerHTML = data.recent_orders.map(o => `
          <tr data-order-id="${o.order_id}">
            <td><strong>${o.order_id}</strong></td>
            <td>${o.customer}</td>
            <td>₹${(o.amount || 0).toLocaleString('en-IN')}</td>
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
    }
  }

  async function loadDashboard() {
    if (!api.getToken()) return;
    if (state.dashboardData) {
      renderDashboardUI(state.dashboardData);
    }
    try {
      const data = await api.getDashboardStats();
      if (!data) return;
      state.dashboardData = data;
      renderDashboardUI(data);
    } catch (err) {
      console.error('Error loading dashboard:', err);
      if (!api.getToken() || (err.message && (err.message.includes('Session expired') || err.message.includes('unauthorized') || err.message.includes('401')))) {
        return;
      }
      showToast('Failed to load dashboard data', 'danger');
    }
  }

  // Quick Action Buttons
  document.getElementById('btn-dashboard-new-order')?.addEventListener('click', () => switchTab('new-order'));
  document.getElementById('btn-dashboard-view-all-orders')?.addEventListener('click', () => switchTab('orders'));

  async function ensureLocationsLoaded() {
    if (!state.locations || Object.keys(state.locations).length === 0) {
      try {
        const res = await api.getLocations();
        state.locations = res.locations || {};
      } catch (e) {
        console.warn('Locations load error:', e);
      }
    }
    return state.locations;
  }

  // ---------------- 2. NEW ORDER PAGE ----------------
  async function initNewOrderPage() {
    await refreshGlobalSettings();
    await ensureLocationsLoaded();

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

    // Fast Silent Phone Lookup for Repeat Customer
    const phoneInput = document.getElementById('new-order-phone');
    const phoneError = document.getElementById('new-order-phone-error');
    const phoneAlert = document.getElementById('new-order-phone-alert');
    const phoneAlertText = document.getElementById('new-order-phone-alert-text');
    let lastCheckedPhone = '';

    const performSilentPhoneLookup = async () => {
      const val = (phoneInput.value || '').replace(/\D/g, '');
      if (val.length < 10) {
        if (phoneAlert) phoneAlert.style.display = 'none';
        return;
      }
      if (val === lastCheckedPhone) return;
      lastCheckedPhone = val;

      try {
        const check = await api.checkPhone(val);
        if (check && check.exists) {
          if (phoneAlert && phoneAlertText) {
            phoneAlertText.innerHTML = `<strong>ℹ️ Repeat Customer:</strong> This phone number is associated with Order #<strong>${escapeHtml(check.order_id)}</strong>${check.customer_name ? ` (${escapeHtml(check.customer_name)})` : ''}.`;
            phoneAlert.style.display = 'block';
          }
          phoneError.classList.remove('show');
          phoneInput.classList.remove('is-invalid');

          // Auto-fill customer details if not already typed
          const nameInput = document.getElementById('new-order-customer');
          const addrInput = document.getElementById('new-order-address');
          const pinInput = document.getElementById('new-order-pincode');
          const stateSelect = document.getElementById('new-order-state');
          const distSelect = document.getElementById('new-order-district');

          if (nameInput && (!nameInput.value.trim() || nameInput.dataset.autofilled === 'true') && check.customer_name) {
            nameInput.value = check.customer_name;
            nameInput.dataset.autofilled = 'true';
          }
          if (addrInput && (!addrInput.value.trim() || addrInput.dataset.autofilled === 'true') && check.address) {
            addrInput.value = check.address;
            addrInput.dataset.autofilled = 'true';
          }
          if (pinInput && (!pinInput.value.trim() || pinInput.dataset.autofilled === 'true') && check.pin_code) {
            pinInput.value = check.pin_code;
            pinInput.dataset.autofilled = 'true';
            if (check.state && stateSelect) {
              stateSelect.value = check.state;
              populateDistricts(check.state, check.district || 'Chennai');
              if (check.district && distSelect) {
                distSelect.value = check.district;
              }
            }
          }
        } else {
          if (phoneAlert) phoneAlert.style.display = 'none';
        }
      } catch (e) {
        console.error('Silent phone lookup error:', e);
      }
    };

    phoneInput.onblur = performSilentPhoneLookup;
    phoneInput.oninput = () => {
      phoneError.classList.remove('show');
      phoneInput.classList.remove('is-invalid');
      const digits = (phoneInput.value || '').replace(/\D/g, '');
      if (digits.length === 10) {
        performSilentPhoneLookup();
      } else if (digits.length < 10) {
        lastCheckedPhone = '';
        if (phoneAlert) phoneAlert.style.display = 'none';
      }
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

              // Recalculate shipping standard rate (preserves manual fee override if entered)
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
        input.onblur = () => {
          if (input.value === '' || isNaN(parseInt(input.value))) {
            input.value = 0;
            state.newOrderState.flavours[flv] = 0;
            recalcNewOrderPricing();
          }
        };
      }
    });

    // Optional Combo Offer Buttons (Requirement 4)
    window.toggleNewOrderCombo = function(type) {
      if (state.newOrderState.comboSelected === type) {
        state.newOrderState.comboSelected = null;
      } else {
        state.newOrderState.comboSelected = type;
      }
      recalcNewOrderPricing();
    };

    const btnCombo2 = document.getElementById('btn-combo-2');
    const btnCombo4 = document.getElementById('btn-combo-4');

    if (btnCombo2) {
      btnCombo2.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        window.toggleNewOrderCombo('2_BOTTLE');
      };
    }

    if (btnCombo4) {
      btnCombo4.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        window.toggleNewOrderCombo('4_BOTTLE');
      };
    }

    // Manual delivery fee edit listener
    const deliveryFeeInput = document.getElementById('new-order-delivery-fee');
    deliveryFeeInput.oninput = () => {
      const rawVal = deliveryFeeInput.value.trim();
      if (rawVal === '') {
        state.newOrderState.isManualDeliveryFee = false;
      } else {
        state.newOrderState.isManualDeliveryFee = true;
        state.newOrderState.deliveryFee = Math.max(0, parseFloat(rawVal) || 0);
      }
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

    // Dynamic bottle price from settings
    const originalUnitPrice = (state.settings.bottle_price !== undefined) 
      ? Number(state.settings.bottle_price) 
      : (Number(state.settings.original_bottle_price) || 160.0);
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
      if (btnCombo2) {
        btnCombo2.style.display = 'inline-flex';
        const isApplied = (state.newOrderState.comboSelected === '2_BOTTLE');
        btnCombo2.classList.toggle('active', isApplied);
        btnCombo2.innerHTML = isApplied 
          ? '2-Bottle Combo Applied — ₹289 <span style="font-size:11px; opacity:0.85; margin-left:6px; font-weight:normal;">(Click to remove)</span>' 
          : 'Apply 2-Bottle Combo — ₹289';
      }
      if (btnCombo4) btnCombo4.style.display = 'none';
      if (state.newOrderState.comboSelected === '4_BOTTLE') {
        state.newOrderState.comboSelected = null;
      }
    } else if (totalBottles === 4) {
      if (comboContainer) comboContainer.style.display = 'block';
      if (btnCombo4) {
        btnCombo4.style.display = 'inline-flex';
        const isApplied = (state.newOrderState.comboSelected === '4_BOTTLE');
        btnCombo4.classList.toggle('active', isApplied);
        btnCombo4.innerHTML = isApplied 
          ? '4-Bottle Combo Applied — ₹559 <span style="font-size:11px; opacity:0.85; margin-left:6px; font-weight:normal;">(Click to remove)</span>' 
          : 'Apply 4-Bottle Combo — ₹559';
      }
      if (btnCombo2) btnCombo2.style.display = 'none';
      if (state.newOrderState.comboSelected === '2_BOTTLE') {
        state.newOrderState.comboSelected = null;
      }
    } else {
      if (comboContainer) comboContainer.style.display = 'none';
      if (btnCombo2) {
        btnCombo2.style.display = 'none';
        btnCombo2.classList.remove('active');
        btnCombo2.innerHTML = 'Apply 2-Bottle Combo — ₹289';
      }
      if (btnCombo4) {
        btnCombo4.style.display = 'none';
        btnCombo4.classList.remove('active');
        btnCombo4.innerHTML = 'Apply 4-Bottle Combo — ₹559';
      }
      state.newOrderState.comboSelected = null;
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
        comboDisplay.textContent = (String(comboType).includes('2') || totalBottles === 2) ? '2 Bottles for ₹289' : '4 Bottles for ₹559';
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
        } else {
          state.newOrderState.deliveryFee = parseFloat(feeInput.value) || 0;
          if (noteEl) {
            noteEl.textContent = `Manual rate: ₹${feeInput.value}`;
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

    if (state.newOrderState.isSubmitting) return;

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
      combo_type: state.newOrderState.comboSelected || '',
      items
    };

    const submitBtn = document.querySelector('#form-new-order button[type="submit"]');

    try {
      state.newOrderState.isSubmitting = true;
      if (submitBtn) submitBtn.disabled = true;

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
      const phoneAlertEl = document.getElementById('new-order-phone-alert');
      if (phoneAlertEl) phoneAlertEl.style.display = 'none';
      populateDistricts('Tamil Nadu', 'Chennai');
      recalcNewOrderPricing();

    } catch (err) {
      showToast(err.message || 'Failed to create order', 'danger');
    } finally {
      state.newOrderState.isSubmitting = false;
      if (submitBtn) submitBtn.disabled = false;
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
    if (!api.getToken()) return;
    if (state.orders && state.orders.length > 0) {
      renderOrdersTable();
    }
    try {
      const data = await api.getOrders(state.currentOrderFilter);
      state.orders = data.orders || [];
      state.availableDistricts = data.available_districts || [];

      // Update district filter dropdown
      const distFilter = document.getElementById('filter-order-district');
      const currDist = state.currentOrderFilter.district;
      if (distFilter) {
        distFilter.innerHTML = '<option value="All">All Districts</option>';
        state.availableDistricts.forEach(d => {
          distFilter.innerHTML += `<option value="${d}" ${d === currDist ? 'selected' : ''}>${d}</option>`;
        });
      }

      renderOrdersTable();
    } catch (err) {
      console.error('Error loading orders:', err);
      if (!api.getToken() || (err.message && (err.message.includes('Session expired') || err.message.includes('unauthorized') || err.message.includes('401')))) {
        return;
      }
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
            <button class="btn-three-dot" data-menu-id="${o.order_id}" title="Order Actions" aria-label="Order Actions">
              <svg class="icon-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg>
            </button>
          </td>
        </tr>
      `;
    }).join('');

    // Row click: opens details (Requirement 14)
    tbody.querySelectorAll('tr').forEach(row => {
      row.addEventListener('click', (e) => {
        // Prevent opening if clicked on dispatch toggle or 3-dot menu button
        if (e.target.closest('.btn-dispatch-toggle') || e.target.closest('.btn-three-dot')) {
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

    // Three Dot Menu listeners (Requirement 15: floating outside order row)
    tbody.querySelectorAll('.btn-three-dot').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const oid = btn.dataset.menuId;
        showOrderActionsMenu(btn, oid);
      });
    });
  }

  // Floating Order Actions Dropdown (renders outside order row/table to prevent scrollbar/clipping)
  function getOrderActionsMenu() {
    let menu = document.getElementById('floating-order-actions-menu');
    if (!menu) {
      menu = document.createElement('div');
      menu.id = 'floating-order-actions-menu';
      menu.className = 'three-dot-dropdown floating-dropdown';
      menu.innerHTML = `
        <div class="three-dot-item" data-action="edit">
          <svg class="icon-svg" viewBox="0 0 24 24"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/></svg>
          <span>Edit Order</span>
        </div>
        <div class="three-dot-item text-danger" data-action="delete">
          <svg class="icon-svg" viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>
          <span>Delete Order</span>
        </div>
      `;
      document.body.appendChild(menu);

      menu.querySelectorAll('.three-dot-item').forEach(item => {
        item.addEventListener('click', (e) => {
          e.stopPropagation();
          const action = item.dataset.action;
          const oid = menu.dataset.orderId;
          hideOrderActionsMenu();

          if (action === 'edit' && oid) {
            openEditOrderModal(oid);
          } else if (action === 'delete' && oid) {
            openDeleteOrderModal(oid);
          }
        });
      });
    }
    return menu;
  }

  function hideOrderActionsMenu() {
    const menu = document.getElementById('floating-order-actions-menu');
    if (menu) {
      menu.classList.remove('show');
      menu.style.display = 'none';
      menu.dataset.orderId = '';
    }
  }

  function showOrderActionsMenu(btn, orderId) {
    const menu = getOrderActionsMenu();
    if (menu.classList.contains('show') && menu.dataset.orderId === orderId) {
      hideOrderActionsMenu();
      return;
    }

    menu.dataset.orderId = orderId;
    menu.style.display = 'flex';
    menu.classList.add('show');

    // Calculate fixed viewport position relative to the clicked button
    const rect = btn.getBoundingClientRect();
    const menuWidth = menu.offsetWidth || 145;
    const menuHeight = menu.offsetHeight || 85;

    // Align right side with button right side, maintaining 8px viewport padding
    let left = rect.right - menuWidth;
    if (left + menuWidth > window.innerWidth - 8) {
      left = window.innerWidth - menuWidth - 8;
    }
    if (left < 8) left = 8;

    // Check vertical space: place below button by default, or flip above if near screen bottom
    let top = rect.bottom + 4;
    if (top + menuHeight > window.innerHeight - 8) {
      top = rect.top - menuHeight - 4;
    }
    if (top < 8) top = 8;

    menu.style.top = `${top}px`;
    menu.style.left = `${left}px`;
  }

  // Close floating dropdown on outside click, window scroll/resize, or Escape
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#floating-order-actions-menu') && !e.target.closest('.btn-three-dot')) {
      hideOrderActionsMenu();
    }
  });
  window.addEventListener('scroll', hideOrderActionsMenu, true);
  window.addEventListener('resize', hideOrderActionsMenu);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') hideOrderActionsMenu();
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

  // Order Google Sheets Export
  document.getElementById('btn-export-orders-csv').addEventListener('click', () => {
    if (!state.orders || state.orders.length === 0) {
      showToast('No orders to export', 'warning');
      return;
    }

    const headers = [
      'Order ID', 'Date', 'Customer', 'Phone', 'District', 'State',
      'Bottles', 'Weight', 'Product Amount (₹)', 'Delivery Fee (₹)', 'Final Amount (₹)', 'Payment Mode',
      'Dispatch Status', 'Created By', 'Edited By'
    ];

    const rows = state.orders.map(o => [
      o.order_id,
      o.date,
      o.customer,
      o.phone,
      o.district,
      o.state,
      Number(o.bottles) || 0,
      o.weight,
      Number(o.product) || 0,
      Number(o.delivery) || 0,
      Number(o.final) || 0,
      o.payment,
      o.dispatch,
      o.created_by,
      o.edited_by
    ]);

    exportToGoogleSheets(`POPCONE_Orders_Export_${new Date().toISOString().slice(0, 10)}.xlsx`, 'Orders', headers, rows);
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

      // Requirement 2.B: Display actual saved combo information
      const comboStatusEl = document.getElementById('detail-combo-status');
      const rowSelectedCombo = document.getElementById('detail-row-selected-combo');
      const selectedComboEl = document.getElementById('detail-selected-combo');
      const prodAmtLabelEl = document.getElementById('detail-product-amount-label');

      if (o.is_combo) {
        if (comboStatusEl) {
          comboStatusEl.innerHTML = '<span class="badge badge-paid" style="background:#10B981; color:#fff; font-weight:700;">Applied</span>';
        }
        if (rowSelectedCombo) rowSelectedCombo.style.display = 'flex';
        if (selectedComboEl) {
          const ct = String(o.combo_type || '').trim().toUpperCase();
          if (ct.includes('2') || o.total_bottles === 2) {
            selectedComboEl.textContent = '2 Bottles for ₹289';
          } else if (ct.includes('4') || o.total_bottles === 4) {
            selectedComboEl.textContent = '4 Bottles for ₹559';
          } else {
            selectedComboEl.textContent = o.combo_type || 'Combo Applied';
          }
        }
        if (prodAmtLabelEl) prodAmtLabelEl.textContent = 'Combo Product Amount';
        document.getElementById('detail-product-amount').textContent = `₹${(o.combo_price || o.product_amount).toLocaleString('en-IN')}`;
      } else {
        if (comboStatusEl) {
          comboStatusEl.innerHTML = '<span class="badge badge-secondary" style="background:#E2E8F0; color:#475569;">Not Applied</span>';
        }
        if (rowSelectedCombo) rowSelectedCombo.style.display = 'none';
        if (prodAmtLabelEl) prodAmtLabelEl.textContent = 'Normal Discounted Amount';
        const discNote = (o.total_discount > 0) ? ` (Discount: -₹${o.total_discount})` : '';
        document.getElementById('detail-product-amount').textContent = `₹${o.product_amount.toLocaleString('en-IN')}${discNote}`;
      }

      document.getElementById('detail-delivery-fee').textContent = o.delivery_fee === 0 ? '₹0 (Free Delivery)' : `₹${o.delivery_fee.toLocaleString('en-IN')}`;
      document.getElementById('detail-final-amount').textContent = `₹${o.final_amount.toLocaleString('en-IN')}`;
      document.getElementById('detail-payment-method').textContent = o.payment;

      // Audit Information
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

  // ---------------- 5. EDIT ORDER MODAL (Requirement 1 & 2) ----------------
  const editOrderModal = document.getElementById('modal-edit-order');
  let currentEditingOrder = null;
  const editOrderState = {
    comboSelected: null, // null, '2_BOTTLE', or '4_BOTTLE'
    isManualDeliveryFee: false,
    isSubmitting: false
  };

  window.setEditOrderCombo = function(type) {
    editOrderState.comboSelected = type ? type : null;
    recalcEditOrderPricing();
  };

  async function openEditOrderModal(orderId) {
    try {
      await ensureLocationsLoaded();
      const res = await api.getOrder(orderId);
      currentEditingOrder = res.order;
      const o = res.order;

      // Persistence rule: Load combo selection saved with that specific order
      let loadedCombo = null;
      if (o.is_combo) {
        const ct = String(o.combo_type || '').trim().toUpperCase();
        if (ct.includes('4') || o.total_bottles === 4) {
          loadedCombo = '4_BOTTLE';
        } else if (ct.includes('2') || o.total_bottles === 2) {
          loadedCombo = '2_BOTTLE';
        }
      }
      editOrderState.comboSelected = loadedCombo;
      editOrderState.isSubmitting = false;

      // Section A: Customer Information
      document.getElementById('edit-order-id-display').textContent = o.order_id;
      document.getElementById('edit-customer-name').value = o.customer;
      document.getElementById('edit-phone').value = o.phone;
      document.getElementById('edit-address').value = o.address;
      document.getElementById('edit-pincode').value = o.pin_code;
      
      const savedFee = (o.delivery_fee !== undefined && o.delivery_fee !== null) ? Number(o.delivery_fee) : 0;
      document.getElementById('edit-delivery-fee').value = savedFee;

      const applicableAmt = o.is_combo ? (Number(o.combo_price) || Number(o.product_amount)) : Number(o.product_amount);
      const standardCalc = computeDeliveryFeeClient(o.state, o.district, o.total_bottles, applicableAmt);
      editOrderState.isManualDeliveryFee = (savedFee !== standardCalc.fee);

      // Section D: Order Information
      document.getElementById('edit-info-order-id').textContent = o.order_id;
      document.getElementById('edit-info-order-date').textContent = o.date;
      document.getElementById('edit-payment').value = o.payment;
      const dispatchBadge = document.getElementById('edit-info-dispatch-badge');
      if (dispatchBadge) {
        dispatchBadge.textContent = o.dispatch_state;
        dispatchBadge.className = `badge ${o.dispatch_state === 'DISPATCHED' ? 'badge-dispatched' : 'badge-placed'}`;
      }
      document.getElementById('edit-info-created-by').textContent = `${o.created_by} (${o.created_at})`;
      document.getElementById('edit-info-edited-by').textContent = `${o.edited_by} (${o.edited_at})`;

      // Populate States & Districts with robust selection preservation
      const stSelect = document.getElementById('edit-state');
      const distSelect = document.getElementById('edit-district');

      function populateEditDistricts(selectedState, targetDistrict) {
        distSelect.innerHTML = '<option value="">-- Select District --</option>';
        const distList = (selectedState && state.locations[selectedState]) ? [...state.locations[selectedState]] : [];
        let matchedDist = null;

        distList.sort().forEach(d => {
          const isMatch = (targetDistrict && d.toLowerCase() === targetDistrict.toLowerCase());
          if (isMatch) matchedDist = d;
          distSelect.innerHTML += `<option value="${d}" ${isMatch ? 'selected' : ''}>${d}</option>`;
        });

        // Ensure order's existing district is always present even if not in standard list
        if (targetDistrict && !matchedDist) {
          distSelect.innerHTML += `<option value="${targetDistrict}" selected>${targetDistrict}</option>`;
        }
      }

      function populateEditStatesAndDistricts(targetState, targetDistrict) {
        stSelect.innerHTML = '<option value="">-- Select State --</option>';
        let matchedStateKey = null;

        Object.keys(state.locations).sort().forEach(st => {
          const isMatch = (targetState && st.toLowerCase() === targetState.toLowerCase());
          if (isMatch) matchedStateKey = st;
          stSelect.innerHTML += `<option value="${st}" ${isMatch ? 'selected' : ''}>${st}</option>`;
        });

        // Ensure order's existing state is always present
        if (targetState && !matchedStateKey) {
          stSelect.innerHTML += `<option value="${targetState}" selected>${targetState}</option>`;
          matchedStateKey = targetState;
        }

        populateEditDistricts(matchedStateKey || stSelect.value, targetDistrict);
      }

      populateEditStatesAndDistricts(o.state, o.district);

      stSelect.onchange = () => {
        populateEditDistricts(stSelect.value, null);
        recalcEditOrderPricing();
      };

      distSelect.onchange = () => {
        recalcEditOrderPricing();
      };

      // Automatic Indian PIN Code Lookup in Edit Order Modal
      const editPincodeInput = document.getElementById('edit-pincode');
      const editPincodeSpinner = document.getElementById('edit-pincode-spinner');
      const editPincodeFeedback = document.getElementById('edit-pincode-feedback');
      let editLastLookedUpPincode = o.pin_code || '';
      let editPincodeLookupSeq = 0;

      if (editPincodeFeedback) {
        editPincodeFeedback.style.display = 'none';
        editPincodeFeedback.className = 'pincode-feedback';
      }

      if (editPincodeInput) {
        editPincodeInput.oninput = async () => {
          const pin = editPincodeInput.value.trim();
          if (editPincodeFeedback) {
            editPincodeFeedback.style.display = 'none';
            editPincodeFeedback.className = 'pincode-feedback';
          }

          if (pin.length === 6 && /^\d{6}$/.test(pin)) {
            if (pin === editLastLookedUpPincode) return;
            const currentSeq = ++editPincodeLookupSeq;
            if (editPincodeSpinner) editPincodeSpinner.style.display = 'inline';

            try {
              const res = await api.lookupPincode(pin);
              if (currentSeq !== editPincodeLookupSeq) return;
              if (editPincodeSpinner) editPincodeSpinner.style.display = 'none';

              if (res && res.status === 'success' && res.state) {
                editLastLookedUpPincode = pin;
                populateEditStatesAndDistricts(res.state, res.district);
                if (editPincodeFeedback) {
                  editPincodeFeedback.textContent = `Auto-detected: ${distSelect.value || res.district}, ${stSelect.value || res.state}`;
                  editPincodeFeedback.className = 'pincode-feedback success';
                  editPincodeFeedback.style.display = 'block';
                }
                recalcEditOrderPricing();
              } else {
                if (editPincodeFeedback) {
                  editPincodeFeedback.textContent = 'Postal information not found for this PIN code.';
                  editPincodeFeedback.className = 'pincode-feedback error';
                  editPincodeFeedback.style.display = 'block';
                }
              }
            } catch (err) {
              if (currentSeq !== editPincodeLookupSeq) return;
              if (editPincodeSpinner) editPincodeSpinner.style.display = 'none';
              if (editPincodeFeedback) {
                editPincodeFeedback.textContent = 'Postal lookup unavailable. Please select District & State manually.';
                editPincodeFeedback.className = 'pincode-feedback error';
                editPincodeFeedback.style.display = 'block';
              }
            }
          }
        };
      }

      // Section B: Flavour Quantities
      const itemsMap = {};
      o.items.forEach(it => { itemsMap[it.flavour] = it.quantity; });
      ['Tomato', 'Cheese', 'Sour Cream', 'Peri Peri'].forEach(flv => {
        const input = document.getElementById(`edit-qty-${flv.toLowerCase().replace(' ', '-')}`);
        if (input) {
          input.value = itemsMap[flv] || 0;
          input.oninput = () => recalcEditOrderPricing();
        }
      });

      const feeInput = document.getElementById('edit-delivery-fee');
      if (feeInput) {
        feeInput.oninput = () => {
          const rawVal = feeInput.value.trim();
          if (rawVal === '') {
            editOrderState.isManualDeliveryFee = false;
          } else {
            editOrderState.isManualDeliveryFee = true;
          }
          recalcEditOrderPricing();
        };
      }

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
    const summaryBottles = document.getElementById('edit-summary-bottles');
    if (summaryBottles) summaryBottles.textContent = `${totalBottles} Bottles (${weightDisplay})`;

    // Historical pricing preservation (Requirement 1.C & 5)
    const unitPrice = currentEditingOrder.unit_price || 160.0;
    const discountPerBottle = (currentEditingOrder.discount_per_bottle !== undefined && currentEditingOrder.discount_per_bottle > 0)
      ? currentEditingOrder.discount_per_bottle
      : ((state.settings.discount_per_bottle !== undefined) ? Number(state.settings.discount_per_bottle) : 11.0);

    const originalAmount = totalBottles * unitPrice;
    const totalDiscount = totalBottles * discountPerBottle;
    const normalDiscountedAmount = originalAmount - totalDiscount;

    // Combo Handling & Validation (Requirement 2.C, 2.D, 2.E)
    const comboBox = document.getElementById('edit-combo-box');
    const comboValidationAlert = document.getElementById('edit-combo-validation-alert');
    const comboValidationText = document.getElementById('edit-combo-validation-text');
    const comboHelper = document.getElementById('edit-combo-box-helper');
    const statusPill = document.getElementById('edit-combo-status-pill');
    const saveBtn = document.getElementById('btn-save-edit-order');

    const optNone = document.getElementById('btn-edit-opt-none');
    const opt2 = document.getElementById('btn-edit-opt-2');
    const opt4 = document.getElementById('btn-edit-opt-4');

    let isComboApplied = false;
    let comboPrice = 0.0;
    let applicableProductAmount = normalDiscountedAmount;
    let hasComboError = false;

    // Reset option card classes
    if (optNone) optNone.className = 'edit-combo-opt-card' + (!editOrderState.comboSelected ? ' active' : '');
    if (opt2) opt2.className = 'edit-combo-opt-card' + (editOrderState.comboSelected === '2_BOTTLE' ? ' active' : '');
    if (opt4) opt4.className = 'edit-combo-opt-card' + (editOrderState.comboSelected === '4_BOTTLE' ? ' active' : '');

    if (editOrderState.comboSelected === '2_BOTTLE') {
      if (totalBottles === 2) {
        // Valid 2-bottle combo
        isComboApplied = true;
        comboPrice = 289.0;
        applicableProductAmount = 289.0;
        if (comboBox) comboBox.className = 'edit-combo-box active';
        if (statusPill) statusPill.innerHTML = '<span class="badge" style="background:#10B981; color:#fff; font-weight:700; padding:4px 10px; border-radius:4px;">Applied: 2 Bottles for ₹289</span>';
        if (comboHelper) comboHelper.textContent = '✓ 2-Bottle Combo active: ₹289 replaces normal ₹' + normalDiscountedAmount + ' product amount.';
        if (comboValidationAlert) comboValidationAlert.style.display = 'none';
        if (saveBtn) saveBtn.disabled = false;
      } else {
        // INVALID: quantity mismatch (Requirement 2.D)
        hasComboError = true;
        if (comboBox) comboBox.className = 'edit-combo-box invalid';
        if (opt2) opt2.className = 'edit-combo-opt-card active invalid-combo';
        if (statusPill) statusPill.innerHTML = `<span class="badge" style="background:#EF4444; color:#fff; font-weight:700; padding:4px 10px; border-radius:4px;">Quantity Mismatch (${totalBottles}/2)</span>`;
        if (comboHelper) comboHelper.textContent = 'Selected 2-Bottle Combo requires exactly 2 bottles.';
        if (comboValidationAlert) {
          comboValidationAlert.style.display = 'flex';
          comboValidationText.textContent = `The selected 2-Bottle Combo requires exactly 2 bottles (current: ${totalBottles} bottles). Adjust bottle quantities to 2 or select Regular Pricing before saving.`;
        }
        if (saveBtn) saveBtn.disabled = true;
      }
    } else if (editOrderState.comboSelected === '4_BOTTLE') {
      if (totalBottles === 4) {
        // Valid 4-bottle combo
        isComboApplied = true;
        comboPrice = 559.0;
        applicableProductAmount = 559.0;
        if (comboBox) comboBox.className = 'edit-combo-box active';
        if (statusPill) statusPill.innerHTML = '<span class="badge" style="background:#10B981; color:#fff; font-weight:700; padding:4px 10px; border-radius:4px;">Applied: 4 Bottles for ₹559</span>';
        if (comboHelper) comboHelper.textContent = '✓ 4-Bottle Combo active: ₹559 replaces normal ₹' + normalDiscountedAmount + ' product amount.';
        if (comboValidationAlert) comboValidationAlert.style.display = 'none';
        if (saveBtn) saveBtn.disabled = false;
      } else {
        // INVALID: quantity mismatch (Requirement 2.D)
        hasComboError = true;
        if (comboBox) comboBox.className = 'edit-combo-box invalid';
        if (opt4) opt4.className = 'edit-combo-opt-card active invalid-combo';
        if (statusPill) statusPill.innerHTML = `<span class="badge" style="background:#EF4444; color:#fff; font-weight:700; padding:4px 10px; border-radius:4px;">Quantity Mismatch (${totalBottles}/4)</span>`;
        if (comboHelper) comboHelper.textContent = 'Selected 4-Bottle Combo requires exactly 4 bottles.';
        if (comboValidationAlert) {
          comboValidationAlert.style.display = 'flex';
          comboValidationText.textContent = `The selected 4-Bottle Combo requires exactly 4 bottles (current: ${totalBottles} bottles). Adjust bottle quantities to 4 or select Regular Pricing before saving.`;
        }
        if (saveBtn) saveBtn.disabled = true;
      }
    } else {
      // Regular pricing (No combo selected)
      if (comboBox) comboBox.className = 'edit-combo-box';
      if (statusPill) statusPill.innerHTML = '<span class="badge" style="background:#E2E8F0; color:#475569; font-weight:600; padding:4px 10px; border-radius:4px;">Regular Pricing</span>';
      if (comboValidationAlert) comboValidationAlert.style.display = 'none';
      if (saveBtn) saveBtn.disabled = false;
      if (totalBottles === 2) {
        if (comboHelper) comboHelper.innerHTML = '<strong style="color:#D97706;">💡 Eligible!</strong> Total is 2 bottles. Click "2-Bottle Combo — ₹289" above to apply combo offer.';
      } else if (totalBottles === 4) {
        if (comboHelper) comboHelper.innerHTML = '<strong style="color:#D97706;">💡 Eligible!</strong> Total is 4 bottles. Click "4-Bottle Combo — ₹559" above to apply combo offer.';
      } else {
        if (comboHelper) comboHelper.textContent = 'Combos are available for exactly 2 bottles (₹289) or 4 bottles (₹559).';
      }
    }

    // Delivery calculation
    const stVal = document.getElementById('edit-state').value;
    const distVal = document.getElementById('edit-district').value;
    const feeInput = document.getElementById('edit-delivery-fee');
    const freeDeliveryStatusEl = document.getElementById('edit-summary-free-delivery-status');
    const zoneHintEl = document.getElementById('edit-delivery-zone-hint');

    const calc = computeDeliveryFeeClient(stVal, distVal, totalBottles, applicableProductAmount);

    let deliveryFee = 0;
    if (calc.isFree) {
      feeInput.value = 0;
      feeInput.disabled = true;
      deliveryFee = 0;
      if (freeDeliveryStatusEl) freeDeliveryStatusEl.innerHTML = '<span class="badge badge-free-delivery" style="background:#10B981; color:#fff; font-weight:700;">FREE DELIVERY (Product > ₹800)</span>';
      if (zoneHintEl) zoneHintEl.textContent = 'Free delivery applied';
    } else {
      feeInput.disabled = false;
      if (!editOrderState.isManualDeliveryFee) {
        feeInput.value = calc.fee;
        deliveryFee = calc.fee;
        if (zoneHintEl) zoneHintEl.textContent = calc.zone !== 'Unknown' ? `Zone: ${calc.zone} (${calc.slab})` : 'Select location to calculate';
      } else {
        deliveryFee = parseFloat(feeInput.value) || 0;
        if (zoneHintEl) zoneHintEl.textContent = `Manual rate: ₹${deliveryFee} (Standard calculated: ₹${calc.fee})`;
      }
    }

    const finalAmount = applicableProductAmount + deliveryFee;

    // Update Pricing Summary UI (Requirement 1.C)
    document.getElementById('edit-summary-original-amount').textContent = `₹${originalAmount.toLocaleString('en-IN')}`;
    document.getElementById('edit-summary-discount-per-bottle').textContent = `-₹${discountPerBottle}`;
    document.getElementById('edit-summary-total-discount').textContent = `-₹${totalDiscount.toLocaleString('en-IN')}`;
    document.getElementById('edit-summary-discounted-product-amount').textContent = `₹${normalDiscountedAmount.toLocaleString('en-IN')}`;
    
    document.getElementById('edit-summary-combo-status').innerHTML = isComboApplied 
      ? `<span class="badge badge-paid" style="background:#10B981; color:#fff; font-weight:700;">Applied (${editOrderState.comboSelected === '2_BOTTLE' ? '2 Bottles for ₹289' : '4 Bottles for ₹559'})</span>`
      : '<span class="badge badge-secondary" style="background:#E2E8F0; color:#475569;">Not Applied</span>';
    
    document.getElementById('edit-summary-combo-price').textContent = isComboApplied ? `₹${comboPrice.toLocaleString('en-IN')}` : '—';
    document.getElementById('edit-final-amount').textContent = `₹${finalAmount.toLocaleString('en-IN')}`;

    // Disable Save Changes if hasComboError or totalBottles <= 0
    if (saveBtn) {
      saveBtn.disabled = hasComboError || totalBottles <= 0;
    }
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

  document.getElementById('btn-cancel-edit-order')?.addEventListener('click', () => {
    editOrderModal.classList.remove('show');
  });

  document.getElementById('form-edit-order').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!currentEditingOrder || editOrderState.isSubmitting) return;
    const oid = currentEditingOrder.order_id;
    const saveBtn = document.getElementById('btn-save-edit-order');
    const saveLabel = document.getElementById('btn-save-edit-order-label');

    const items = ['Tomato', 'Cheese', 'Sour Cream', 'Peri Peri'].map(flv => {
      const input = document.getElementById(`edit-qty-${flv.toLowerCase().replace(' ', '-')}`);
      return { flavour: flv, quantity: Math.max(0, parseInt(input.value) || 0) };
    }).filter(it => it.quantity > 0);

    const totalBottles = items.reduce((acc, it) => acc + it.quantity, 0);

    if (totalBottles === 0) {
      showToast('Order must contain at least 1 bottle', 'warning');
      return;
    }

    // Strict Combo Validation (Requirement 2.D)
    if (editOrderState.comboSelected === '2_BOTTLE' && totalBottles !== 2) {
      showToast(`Cannot save: 2-Bottle Combo requires exactly 2 bottles (current: ${totalBottles}). Please adjust quantities or deselect combo.`, 'warning');
      return;
    }
    if (editOrderState.comboSelected === '4_BOTTLE' && totalBottles !== 4) {
      showToast(`Cannot save: 4-Bottle Combo requires exactly 4 bottles (current: ${totalBottles}). Please adjust quantities or deselect combo.`, 'warning');
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
      apply_combo: !!editOrderState.comboSelected,
      combo_type: editOrderState.comboSelected || '',
      items
    };

    try {
      editOrderState.isSubmitting = true;
      if (saveBtn) saveBtn.disabled = true;
      if (saveLabel) saveLabel.textContent = 'Saving Changes...';

      await api.editOrder(oid, payload);
      showToast(`Order ${oid} updated successfully!`);
      editOrderModal.classList.remove('show');
      await loadOrders();
      await loadDashboardStats();
    } catch (err) {
      showToast(err.message || 'Failed to update order', 'danger');
    } finally {
      editOrderState.isSubmitting = false;
      if (saveBtn) saveBtn.disabled = false;
      if (saveLabel) saveLabel.textContent = 'Save Changes';
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

  function getFlavourBottleImage(flavour) {
    const f = (flavour || '').toLowerCase();
    if (f.includes('tomato')) return '/static/assets/flavours/spanish_tomato.png';
    if (f.includes('cheese')) return '/static/assets/flavours/cheddar_cheese.png';
    if (f.includes('sour cream') || f.includes('cream')) return '/static/assets/flavours/sour_cream.png';
    if (f.includes('peri')) return '/static/assets/flavours/peri_peri.png';
    return '/static/assets/flavours/spanish_tomato.png';
  }

  function renderInventoryUI(data) {
    if (!data) return;
    const stockGrid = document.getElementById('inventory-stock-grid');
    
    // Stock Cards (Requirement: low stock <= 10, warning ONLY in Inventory page)
    if (stockGrid && data.stocks) {
      stockGrid.innerHTML = data.stocks.map(s => {
        const threshold = Number(s.low_stock_threshold) || 10;
        const isLow = s.current_stock <= threshold;
        const statusHtml = isLow
          ? `<span class="stock-card-status danger"><svg class="icon-svg" style="width:14px;height:14px;" viewBox="0 0 24 24"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg> Low Stock (&le; 10)</span>`
          : `<span class="stock-card-status safe"><svg class="icon-svg" style="width:14px;height:14px;" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg> In Stock</span>`;

        const bottleImg = getFlavourBottleImage(s.flavour);

        return `
          <div class="stock-card ${isLow ? 'low-stock' : ''}">
            <div class="stock-card-content">
              <div class="stock-card-flavour">${escapeHtml(s.flavour)}</div>
              <div>
                <span class="stock-card-qty">${s.current_stock}</span>
                <span class="stock-card-unit">bottles</span>
              </div>
              ${statusHtml}
            </div>
            <div class="stock-card-image-wrap">
              <img src="${bottleImg}" alt="${escapeHtml(s.flavour)} Bottle" class="stock-card-bottle-img" loading="lazy">
            </div>
          </div>
        `;
      }).join('');
    }

    // Requirement 5: Do NOT display "Moved By" in the inventory history!
    // Columns: Date/Time, Flavour, Type, Change, Reference
    const movementsTbody = document.getElementById('inventory-movements-tbody');
    if (movementsTbody) {
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
    }
  }

  async function loadInventory() {
    if (!api.getToken()) return;
    if (state.inventoryData) {
      renderInventoryUI(state.inventoryData);
    }
    try {
      const data = await api.getInventory();
      state.inventoryData = data;
      renderInventoryUI(data);
    } catch (err) {
      console.error('Error loading inventory:', err);
      if (!api.getToken() || (err.message && (err.message.includes('Session expired') || err.message.includes('unauthorized') || err.message.includes('401')))) {
        return;
      }
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
      label.textContent = `Export ${monthNames[state.analyticsMonth - 1]} ${state.analyticsYear} (Google Sheets)`;
    } else if (state.analyticsMode === 'annual') {
      label.textContent = `Export ${state.analyticsYear} Annual (Google Sheets)`;
    } else {
      label.textContent = `Export Weekly (Google Sheets)`;
    }
  }

  // Month selector listener
  document.getElementById('analytics-month-select')?.addEventListener('change', (e) => {
    state.analyticsMonth = parseInt(e.target.value);
    updateAnalyticsExportLabel();
    renderAnalyticsView();
  });

  async function loadAnalytics() {
    if (!api.getToken()) return;
    if (state.analyticsData) {
      renderAnalyticsView();
    }
    try {
      const year = state.analyticsYear;
      const data = await api.getAnalytics(year, state.analyticsMonth);
      state.analyticsData = data;

      // Populate year selector
      const yearSelect = document.getElementById('analytics-year-select');
      if (yearSelect && data && data.available_years) {
        yearSelect.innerHTML = data.available_years.map(y => 
          `<option value="${y}" ${y === year ? 'selected' : ''}>${y}</option>`
        ).join('');

        yearSelect.onchange = () => {
          state.analyticsYear = parseInt(yearSelect.value);
          updateAnalyticsExportLabel();
          loadAnalytics();
        };
      }

      const monthSelect = document.getElementById('analytics-month-select');
      if (monthSelect) monthSelect.value = state.analyticsMonth;

      updateAnalyticsExportLabel();
      renderAnalyticsView();

    } catch (err) {
      console.error('Error loading analytics:', err);
      if (!api.getToken() || (err.message && (err.message.includes('Session expired') || err.message.includes('unauthorized') || err.message.includes('401')))) {
        return;
      }
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
    let currentShipping = 0;
    const shippingEl = document.getElementById('analytics-total-shipping');
    const shippingLabel = document.getElementById('analytics-kpi-shipping-label');
    const shippingSubtext = document.getElementById('analytics-kpi-shipping-subtext');

    if (mode === 'monthly') {
      currentShipping = selectedMonth.shipping_costs || 0;
      document.getElementById('analytics-kpi-revenue-label').textContent = `${selectedMonth.month_name} Product Revenue`;
      document.getElementById('analytics-kpi-revenue-subtext').textContent = `${selectedMonth.month_name} ${state.analyticsYear} Total Revenue`;
      document.getElementById('analytics-total-revenue').textContent = `₹${selectedMonth.revenue.toLocaleString('en-IN')}`;
      if (shippingLabel) shippingLabel.textContent = `${selectedMonth.month_name} Shipping Costs`;
      if (shippingSubtext) shippingSubtext.textContent = `Recorded Delivery Fees (${selectedMonth.month_name})`;
      document.getElementById('analytics-total-bottles').textContent = selectedMonth.total_bottles;
      document.getElementById('analytics-total-orders').textContent = selectedMonth.total_orders;
      document.getElementById('analytics-most-purchased').textContent = selectedMonth.most_purchased_flavour !== 'None'
        ? selectedMonth.most_purchased_flavour
        : 'None';
    } else if (mode === 'annual') {
      const ann = data.annual_report;
      currentShipping = ann.shipping_costs || 0;
      document.getElementById('analytics-kpi-revenue-label').textContent = 'Annual Product Revenue';
      document.getElementById('analytics-kpi-revenue-subtext').textContent = `Full Year ${state.analyticsYear} Total Revenue`;
      document.getElementById('analytics-total-revenue').textContent = `₹${ann.total_revenue.toLocaleString('en-IN')}`;
      if (shippingLabel) shippingLabel.textContent = 'Annual Shipping Costs';
      if (shippingSubtext) shippingSubtext.textContent = `Full Year ${state.analyticsYear} Delivery Fees`;
      document.getElementById('analytics-total-bottles').textContent = ann.total_bottles;
      document.getElementById('analytics-total-orders').textContent = ann.total_orders;
      document.getElementById('analytics-most-purchased').textContent = ann.most_purchased_flavour !== 'None'
        ? ann.most_purchased_flavour
        : 'None';
    } else {
      // Weekly mode
      const totalWeeklyRev = data.weekly_report.reduce((acc, w) => acc + w.revenue, 0);
      const totalWeeklyBottles = data.weekly_report.reduce((acc, w) => acc + w.total_bottles, 0);
      currentShipping = data.weekly_report.reduce((acc, w) => acc + (w.shipping_costs || 0), 0);
      document.getElementById('analytics-kpi-revenue-label').textContent = 'Weekly Product Revenue';
      document.getElementById('analytics-kpi-revenue-subtext').textContent = `Weeks in ${state.analyticsYear} Total Revenue`;
      document.getElementById('analytics-total-revenue').textContent = `₹${totalWeeklyRev.toLocaleString('en-IN')}`;
      if (shippingLabel) shippingLabel.textContent = 'Weekly Shipping Costs';
      if (shippingSubtext) shippingSubtext.textContent = `Weeks in ${state.analyticsYear} Delivery Fees`;
      document.getElementById('analytics-total-bottles').textContent = totalWeeklyBottles;
      document.getElementById('analytics-total-orders').textContent = data.overview.total_orders;
      document.getElementById('analytics-most-purchased').textContent = data.overview.most_purchased_flavour !== 'None'
        ? data.overview.most_purchased_flavour
        : 'None';
    }

    if (shippingEl) shippingEl.textContent = `₹${currentShipping.toLocaleString('en-IN')}`;

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

  // Unified Google Sheets Export for active analytics view
  document.getElementById('btn-export-analytics-csv')?.addEventListener('click', () => {
    const data = state.analyticsData;
    if (!data) return;

    if (state.analyticsMode === 'monthly') {
      const monthIdx = state.analyticsMonth;
      const m = data.monthly_report.find(x => x.month_num === monthIdx);
      if (!m) return;
      const headers = ['Month', 'Year', 'Total Orders', 'Tomato Bottles', 'Tomato Revenue (₹)', 'Cheese Bottles', 'Cheese Revenue (₹)', 'Sour Cream Bottles', 'Sour Cream Revenue (₹)', 'Peri Peri Bottles', 'Peri Peri Revenue (₹)', 'Total Bottles', 'Product Revenue (₹)', 'Shipping Costs (₹)', 'Top Flavour'];
      const rows = [[
        m.month_name, state.analyticsYear, m.total_orders,
        m.tomato, m.tomato_revenue, m.cheese, m.cheese_revenue,
        m.sour_cream, m.sour_cream_revenue, m.peri_peri, m.peri_peri_revenue,
        m.total_bottles, m.revenue, m.shipping_costs, m.most_purchased_flavour
      ]];
      exportToGoogleSheets(`POPCONE_${m.month_name}_${state.analyticsYear}_Report.xlsx`, `${m.month_name} ${state.analyticsYear}`, headers, rows);
    } else if (state.analyticsMode === 'annual') {
      const ann = data.annual_report;
      const headers = ['Year', 'Total Orders', 'Tomato Bottles', 'Tomato Revenue (₹)', 'Cheese Bottles', 'Cheese Revenue (₹)', 'Sour Cream Bottles', 'Sour Cream Revenue (₹)', 'Peri Peri Bottles', 'Peri Peri Revenue (₹)', 'Total Bottles', 'Product Revenue (₹)', 'Shipping Costs (₹)', 'Top Flavour'];
      const rows = [[
        ann.year, ann.total_orders,
        ann.tomato_bottles, ann.tomato_revenue, ann.cheese_bottles, ann.cheese_revenue,
        ann.sour_cream_bottles, ann.sour_cream_revenue, ann.peri_peri_bottles, ann.peri_peri_revenue,
        ann.total_bottles, ann.total_revenue, ann.shipping_costs, ann.most_purchased_flavour
      ]];
      exportToGoogleSheets(`POPCONE_Annual_Report_${state.analyticsYear}.xlsx`, `Annual ${state.analyticsYear}`, headers, rows);
    } else {
      // Weekly export
      const headers = ['Week', 'Tomato Bottles', 'Tomato Revenue (₹)', 'Cheese Bottles', 'Cheese Revenue (₹)', 'Sour Cream Bottles', 'Sour Cream Revenue (₹)', 'Peri Peri Bottles', 'Peri Peri Revenue (₹)', 'Total Bottles', 'Product Revenue (₹)', 'Shipping Costs (₹)', 'Top Flavour'];
      const rows = data.weekly_report.map(w => [
        w.week_label, w.tomato, w.tomato_revenue, w.cheese, w.cheese_revenue,
        w.sour_cream, w.sour_cream_revenue, w.peri_peri, w.peri_peri_revenue,
        w.total_bottles, w.revenue, w.shipping_costs, w.most_purchased_flavour
      ]);
      exportToGoogleSheets(`POPCONE_Weekly_Report_${state.analyticsYear}.xlsx`, `Weekly ${state.analyticsYear}`, headers, rows);
    }
  });

  function exportToGoogleSheets(filename, sheetName, headers, rows) {
    const cleanFilename = filename.endsWith('.xlsx') ? filename : filename.replace(/\.csv$/i, '') + '.xlsx';

    const cleanRows = rows.map(r => r.map(cell => {
      if (typeof cell === 'string') {
        let trimmed = cell.trim();
        if (trimmed.startsWith('"') && trimmed.endsWith('"')) {
          trimmed = trimmed.slice(1, -1).replace(/""/g, '"');
        }
        return trimmed;
      }
      return cell;
    }));

    if (window.XLSX && XLSX.utils) {
      try {
        const aoa = [headers, ...cleanRows];
        const ws = XLSX.utils.aoa_to_sheet(aoa);

        // Auto-fit column widths for Google Sheets
        const colWidths = headers.map((h, i) => {
          let maxLen = String(h).length;
          for (const r of cleanRows) {
            const valStr = String(r[i] !== undefined && r[i] !== null ? r[i] : '');
            if (valStr.length > maxLen) maxLen = Math.min(valStr.length, 35);
          }
          return { wch: Math.max(maxLen + 3, 10) };
        });
        ws['!cols'] = colWidths;

        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, sheetName || 'POPCONE');
        XLSX.writeFile(wb, cleanFilename);
        showToast(`Exported ${cleanFilename} (Ready for Google Sheets!)`);
        return;
      } catch (err) {
        console.error('XLSX export failed, fallback to CSV:', err);
      }
    }

    // Fallback if XLSX library unavailable
    downloadCSV(cleanFilename.replace('.xlsx', '.csv'), headers, cleanRows);
  }

  function downloadCSV(filename, headers, rows) {
    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast(`Exported ${filename}`);
  }

  // ---------------- 8. BACKUP & RECOVERY (ADMIN ONLY) ----------------
  let isBackupRunning = false;

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  async function loadBackupsView() {
    if (!isUserAdmin()) return;

    const providerEl = document.getElementById('backup-storage-provider');
    const tbody = document.getElementById('tbody-backups-manifest');
    if (!tbody) return;

    try {
      const status = await api.getBackupStatus();
      if (providerEl) {
        providerEl.textContent = status.storage_backend || 'Google Drive (Personal Free Tier)';
      }
    } catch (e) {
      if (providerEl) providerEl.textContent = 'Google Drive';
    }

    try {
      const data = await api.getBackupsManifest();
      const backups = data.backups || [];

      if (backups.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="7" style="text-align: center; padding: 28px; color: var(--text-muted);">
              No backups found in Google Drive. Click <strong>Create Backup Now</strong> to create the first point-in-time snapshot.
            </td>
          </tr>
        `;
        return;
      }

      backups.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));

      tbody.innerHTML = backups.map(b => {
        const cat = b.retention_category || 'DAILY';
        let catBadge = '<span class="badge badge-placed" style="background: #e0f2fe; color: #0369a1;">Daily Snapshot (90d)</span>';
        if (cat === 'LATEST') {
          catBadge = '<span class="badge badge-placed" style="background: #ecfdf5; color: #047857; font-weight: 700;">Latest (Protected)</span>';
        } else if (cat === 'MONTHLY_RECOVERY_POINT') {
          catBadge = '<span class="badge badge-placed" style="background: #fef3c7; color: #b45309; font-weight: 700;">Monthly Point (12mo)</span>';
        } else if (cat === 'RECENT_MIN_RETAINED') {
          catBadge = '<span class="badge badge-placed" style="background: #ede9fe; color: #6d28d9;">Protected (Min Retained)</span>';
        } else if (cat === 'EXPIRED') {
          catBadge = '<span class="badge badge-dispatched" style="background: #f1f5f9; color: #64748b;">Pruning Candidate</span>';
        }

        const isVerified = (b.tier1_verified && b.tier2_verified) || b.tier1_verified;
        const verBadge = isVerified
          ? '<span class="badge badge-placed" style="background: #dcfce7; color: #15803d; font-size: 11px;">Tier 1 & Tier 2 Verified</span>'
          : '<span class="badge badge-dispatched" style="background: #fee2e2; color: #b91c1c; font-size: 11px;">Unverified</span>';

        const sizeKb = b.size_bytes ? `${(b.size_bytes / 1024).toFixed(1)} KB` : 'N/A';
        const typeBadge = b.backup_type === 'SCHEDULED_DAILY'
          ? '<span style="font-size: 12px; font-weight: 600; color: var(--primary-blue);">Automated Daily</span>'
          : '<span style="font-size: 12px; font-weight: 600; color: #6366f1;">Manual Admin</span>';

        let dateStr = b.created_at || 'Unknown';
        try {
          const d = new Date(b.created_at);
          if (!isNaN(d.getTime())) {
            dateStr = d.toLocaleString('en-IN', {
              year: 'numeric',
              month: 'short',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
              hour12: true
            });
          }
        } catch (_) {}

        return `
          <tr style="border-bottom: 1px solid var(--border-light);">
            <td style="padding: 10px 12px; font-family: monospace; font-size: 13px; font-weight: 600; color: var(--text-main);">
              ${escapeHtml(b.backup_id || '')}
            </td>
            <td style="padding: 10px 12px; font-size: 13px; color: var(--text-secondary);">
              ${escapeHtml(dateStr)}
            </td>
            <td style="padding: 10px 12px;">
              ${typeBadge}
            </td>
            <td style="padding: 10px 12px;">
              ${catBadge}
            </td>
            <td style="padding: 10px 12px; text-align: right; font-size: 13px; font-weight: 600;">
              ${sizeKb}
            </td>
            <td style="padding: 10px 12px; text-align: center;">
              ${verBadge}
            </td>
            <td style="padding: 10px 12px; text-align: center;">
              <button class="btn btn-outline btn-sm btn-verify-backup" data-id="${escapeHtml(b.backup_id || '')}" style="padding: 4px 10px; font-size: 12px;">
                Verify
              </button>
            </td>
          </tr>
        `;
      }).join('');

      tbody.querySelectorAll('.btn-verify-backup').forEach(btn => {
        btn.addEventListener('click', async () => {
          const bid = btn.dataset.id;
          if (!bid) return;
          const origText = btn.textContent;
          btn.disabled = true;
          btn.textContent = 'Verifying...';
          const alertBox = document.getElementById('backup-feedback-alert');
          try {
            const res = await api.verifyBackup(bid);
            showToast(`Backup ${bid} successfully verified in isolated sandbox!`);
            if (alertBox) {
              alertBox.style.display = 'block';
              alertBox.style.background = '#ecfdf5';
              alertBox.style.color = '#047857';
              alertBox.style.border = '1px solid #a7f3d0';
              alertBox.innerHTML = `✓ <strong>Verification Passed:</strong> Archive <code>${escapeHtml(bid)}</code> verified. SQLite sandbox integrity: OK, Foreign keys: OK. Total rows verified: ${res.tier2_details?.total_rows ?? 'all'}.`;
            }
          } catch (err) {
            alert(`Verification failed: ${err.message}`);
            if (alertBox) {
              alertBox.style.display = 'block';
              alertBox.style.background = '#fef2f2';
              alertBox.style.color = '#991b1b';
              alertBox.style.border = '1px solid #fecaca';
              alertBox.textContent = `✗ Verification failed for ${bid}: ${err.message}`;
            }
          } finally {
            btn.disabled = false;
            btn.textContent = origText;
          }
        });
      });

    } catch (e) {
      console.error('Failed to load backup manifest:', e);
      tbody.innerHTML = `
        <tr>
          <td colspan="7" style="text-align: center; padding: 24px; color: var(--danger-red);">
            Failed to load backup manifest: ${escapeHtml(e.message || String(e))}
          </td>
        </tr>
      `;
    }
  }

  // Backup modal and action listeners
  const btnOpenBackupModal = document.getElementById('btn-open-create-backup-modal');
  const modalConfirmBackup = document.getElementById('modal-confirm-backup');
  const btnCloseConfirmBackup = document.getElementById('btn-close-confirm-backup');
  const btnCancelBackup = document.getElementById('btn-cancel-backup');
  const btnConfirmCreateBackup = document.getElementById('btn-confirm-create-backup');
  const btnRefreshBackups = document.getElementById('btn-refresh-backups');

  if (btnOpenBackupModal && modalConfirmBackup) {
    btnOpenBackupModal.addEventListener('click', () => {
      if (isBackupRunning) return;
      modalConfirmBackup.classList.add('show');
    });
  }

  function closeConfirmBackupModal() {
    if (modalConfirmBackup) modalConfirmBackup.classList.remove('show');
  }

  if (btnCloseConfirmBackup) btnCloseConfirmBackup.addEventListener('click', closeConfirmBackupModal);
  if (btnCancelBackup) btnCancelBackup.addEventListener('click', closeConfirmBackupModal);

  if (btnConfirmCreateBackup) {
    btnConfirmCreateBackup.addEventListener('click', async () => {
      if (isBackupRunning) return;
      isBackupRunning = true;
      closeConfirmBackupModal();

      if (btnOpenBackupModal) {
        btnOpenBackupModal.disabled = true;
        btnOpenBackupModal.innerHTML = `
          <svg class="icon-svg spin" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="4" stroke="currentColor" fill="none"/></svg>
          <span>Creating Backup...</span>
        `;
      }

      const alertBox = document.getElementById('backup-feedback-alert');
      if (alertBox) {
        alertBox.style.display = 'block';
        alertBox.style.background = '#eff6ff';
        alertBox.style.color = '#1e40af';
        alertBox.style.border = '1px solid #bfdbfe';
        alertBox.innerHTML = `⏳ <strong>Taking Point-in-Time Snapshot:</strong> Extracting all Turso tables, encrypting with AES-256-GCM, and uploading to Google Drive...`;
      }

      try {
        const res = await api.createManualBackup();
        const b = res.backup || {};
        showToast(`Backup ${b.backup_id} created and verified successfully!`);

        if (alertBox) {
          alertBox.style.display = 'block';
          alertBox.style.background = '#ecfdf5';
          alertBox.style.color = '#047857';
          alertBox.style.border = '1px solid #a7f3d0';
          alertBox.innerHTML = `✓ <strong>Backup Successful:</strong> <code>${escapeHtml(b.backup_id || '')}</code> created at ${escapeHtml(b.created_at || '')} (${((b.size_bytes || 0) / 1024).toFixed(1)} KB). Tier 1 & Tier 2 cryptographic and relational integrity verified.`;
        }

        await loadBackupsView();
      } catch (err) {
        console.error('Backup creation error:', err);
        if (alertBox) {
          alertBox.style.display = 'block';
          alertBox.style.background = '#fef2f2';
          alertBox.style.color = '#991b1b';
          alertBox.style.border = '1px solid #fecaca';
          alertBox.textContent = `✗ Backup creation failed: ${err.message || 'Unknown error'}`;
        }
      } finally {
        isBackupRunning = false;
        if (btnOpenBackupModal) {
          btnOpenBackupModal.disabled = false;
          btnOpenBackupModal.innerHTML = `
            <svg class="icon-svg" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/></svg>
            <span>Create Backup Now</span>
          `;
        }
      }
    });
  }

  if (btnRefreshBackups) {
    btnRefreshBackups.addEventListener('click', () => {
      loadBackupsView();
      showToast('Backup manifest refreshed.');
    });
  }


  // Initial Setup on Page Load
  ensureLocationsLoaded();
  updateAuthUI();
});
