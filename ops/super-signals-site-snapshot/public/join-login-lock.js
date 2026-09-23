(() => {
  if (window.__smartSignalsJoinLockActive) return;
  window.__smartSignalsJoinLockActive = true;

  const params = new URLSearchParams(location.search);
  if (params.get('manage') === '1' || params.get('manage') === 'true') return;

  const API = '/account-api';
  const privileged = new Set(['owner', 'admin', 'trading_admin']);
  const nativeFetch = window.fetch.bind(window);
  let redirecting = false;
  let resolving = false;

  const style = document.createElement('style');
  style.textContent = `html.ss-member-resolving body>*{visibility:hidden!important}html.ss-member-resolving body::before{content:'Opening your account…';visibility:visible!important;position:fixed;inset:0;display:grid;place-items:center;background:#041019;color:#f7fbff;font:700 20px/1.3 Inter,system-ui,sans-serif;z-index:2147483647}`;
  document.head.appendChild(style);

  function beginResolution() {
    resolving = true;
    document.documentElement.classList.add('ss-member-resolving');
  }

  function endResolution() {
    resolving = false;
    document.documentElement.classList.remove('ss-member-resolving');
  }

  function goAccount() {
    if (redirecting) return;
    redirecting = true;
    beginResolution();
    location.replace('/account');
  }

  async function json(path) {
    const response = await nativeFetch(`${API}${path}`, {
      credentials: 'include',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return { status: response.status, body: null };
    return { status: response.status, body: await response.json().catch(() => null) };
  }

  async function redirectIfComplete(identity, { maskWhileChecking = false } = {}) {
    if (!identity) {
      if (maskWhileChecking) endResolution();
      return false;
    }

    const role = String(identity.role || '').toLowerCase();
    if (privileged.has(role)) {
      goAccount();
      return true;
    }

    if (maskWhileChecking) beginResolution();
    try {
      const [dashboard, subscription] = await Promise.all([
        json('/account/mt5/dashboard'),
        json('/account/mt5/subscription'),
      ]);
      const connected = dashboard.body?.connection?.status === 'connected'
        || Boolean(dashboard.body?.account)
        || Boolean(dashboard.body?.configured);
      if (connected && Boolean(subscription.body?.active)) {
        goAccount();
        return true;
      }
      return false;
    } finally {
      if (!redirecting && maskWhileChecking) endResolution();
    }
  }

  window.fetch = async (...args) => {
    const response = await nativeFetch(...args);
    try {
      const input = args[0];
      const requestUrl = typeof input === 'string' ? input : input?.url;
      const options = args[1] || {};
      const method = String(options.method || (typeof input !== 'string' ? input?.method : 'GET') || 'GET').toUpperCase();
      const pathname = new URL(requestUrl, location.href).pathname;
      if (method === 'POST' && pathname === '/account-api/auth/login' && response.ok) {
        const identity = await response.clone().json().catch(() => null);
        void redirectIfComplete(identity, { maskWhileChecking: true });
      }
    } catch {
      if (resolving && !redirecting) endResolution();
    }
    return response;
  };

  beginResolution();
  void json('/auth/me')
    .then(result => redirectIfComplete(result.body, { maskWhileChecking: true }))
    .catch(() => endResolution());
})();