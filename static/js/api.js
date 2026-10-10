// POPCONE API Client
const API_BASE = '/api';

const api = {
  getToken() {
    return localStorage.getItem('popcone_token');
  },

  setToken(token) {
    if (token) {
      localStorage.setItem('popcone_token', token);
    } else {
      localStorage.removeItem('popcone_token');
    }
  },

  getUser() {
    const raw = localStorage.getItem('popcone_user');
    try {
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  },

  setUser(user) {
    if (user) {
      localStorage.setItem('popcone_user', JSON.stringify(user));
    } else {
      localStorage.removeItem('popcone_user');
    }
  },

  async request(endpoint, options = {}) {
    const headers = options.headers || {};
    const token = this.getToken();

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(options.body);
    }

    options.headers = headers;

    try {
      const response = await fetch(`${API_BASE}${endpoint}`, options);
      if (response.status === 401) {
        // Expired or unauthorized
        this.setToken(null);
        this.setUser(null);
        window.dispatchEvent(new CustomEvent('auth-changed', { detail: { loggedIn: false } }));
        throw new Error('Session expired or unauthorized');
      }

      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || data.message || `Request failed with status ${response.status}`);
      }
      return data;
    } catch (err) {
      throw err;
    }
  },

  // Auth
  async login(username, password) {
    const res = await this.request('/auth/login', {
      method: 'POST',
      body: { username, password }
    });
    this.setToken(res.token);
    this.setUser(res.user);
    window.dispatchEvent(new CustomEvent('auth-changed', { detail: { loggedIn: true, user: res.user } }));
    return res;
  },

  async logout() {
    try {
      await this.request('/auth/logout', { method: 'POST' });
    } catch (e) {
      console.warn('Logout API failed:', e);
    }
    this.setToken(null);
    this.setUser(null);
    window.dispatchEvent(new CustomEvent('auth-changed', { detail: { loggedIn: false } }));
  },

  async getMe() {
    return this.request('/auth/me');
  },

  async getUsers() {
    return this.request('/users');
  },

  async changePassword(currentPassword, newPassword, confirmPassword) {
    return this.request('/auth/change-password', {
      method: 'POST',
      body: {
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword
      }
    });
  },

  // Settings
  async getSettings() {
    return this.request('/settings');
  },

  async updateDiscount(discount) {
    return this.request('/settings/discount', {
      method: 'POST',
      body: { discount_per_bottle: parseFloat(discount) }
    });
  },

  async adminChangePassword(targetUser, newPassword) {
    const isNum = typeof targetUser === 'number' || (/^\d+$/.test(String(targetUser)));
    const body = isNum
      ? { user_id: parseInt(targetUser, 10), new_password: newPassword }
      : { username: String(targetUser), new_password: newPassword };
    return this.request('/settings/user-password', {
      method: 'POST',
      body
    });
  },

  async updateBottlePrice(price) {
    return this.request('/settings/bottle-price', {
      method: 'POST',
      body: { bottle_price: parseFloat(price) }
    });
  },

  // Locations, Shipping & Postal Lookup
  async getLocations() {
    return this.request('/locations');
  },

  async lookupPincode(pincode) {
    return this.request(`/pincode/${encodeURIComponent(pincode)}`);
  },

  async calculateDelivery(state, district, totalBottles, productAmount = null) {
    return this.request('/calculate-delivery', {
      method: 'POST',
      body: { state, district, total_bottles: totalBottles, product_amount: productAmount }
    });
  },

  // Dashboard
  async getDashboardStats() {
    return this.request('/dashboard/stats');
  },

  // Orders
  async checkPhone(phone, excludeOrderId = null) {
    const params = new URLSearchParams({ phone });
    if (excludeOrderId) params.append('exclude_order_id', excludeOrderId);
    return this.request(`/orders/check-phone?${params.toString()}`);
  },

  async getOrders(params = {}) {
    const query = new URLSearchParams();
    if (params.search) query.append('search', params.search);
    if (params.payment) query.append('payment', params.payment);
    if (params.dispatch) query.append('dispatch', params.dispatch);
    if (params.district) query.append('district', params.district);
    if (params.date_filter) query.append('date_filter', params.date_filter);
    if (params.date_from) query.append('date_from', params.date_from);
    if (params.date_to) query.append('date_to', params.date_to);
    if (params.sort_by) query.append('sort_by', params.sort_by);
    return this.request(`/orders?${query.toString()}`);
  },

  async getOrder(orderId) {
    return this.request(`/orders/${encodeURIComponent(orderId)}`);
  },

  async createOrder(orderData) {
    return this.request('/orders', {
      method: 'POST',
      body: orderData
    });
  },

  async editOrder(orderId, orderData) {
    return this.request(`/orders/${encodeURIComponent(orderId)}`, {
      method: 'PUT',
      body: orderData
    });
  },

  async deleteOrder(orderId) {
    return this.request(`/orders/${encodeURIComponent(orderId)}`, {
      method: 'DELETE'
    });
  },

  async toggleDispatch(orderId) {
    return this.request(`/orders/${encodeURIComponent(orderId)}/dispatch`, {
      method: 'POST'
    });
  },

  // Inventory
  async getInventory() {
    return this.request('/inventory');
  },

  async addOrAdjustStock(data) {
    return this.request('/inventory/stock-movement', {
      method: 'POST',
      body: data
    });
  },

  async resetInventory() {
    return this.request('/inventory/reset', {
      method: 'POST'
    });
  },

  // Analytics
  async getAnalytics(year, month = null) {
    const query = new URLSearchParams();
    if (year) query.append('year', year);
    if (month) query.append('month', month);
    const qs = query.toString();
    return this.request(`/analytics${qs ? '?' + qs : ''}`);
  }
};
