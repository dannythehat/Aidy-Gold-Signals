(() => {
  const params = new URLSearchParams(window.location.search);
  if (params.get('manage') === '1' || params.get('manage') === 'true') return;

  const API = '/account-api';
  const privilegedRoles = new Set(['owner', 'admin', 'trading_admin']);
  let busy = false;
  let stopped = false;
  let timer = null;

  async function get(path) {
    const response = await fetch(`${API}${path}`, {
      credentials: 'include',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return null;
    return response.json().catch(() => null);
  }

  function connected(data) {
    return data?.connection?.status === 'connected' || Boolean(data?.account) || Boolean(data?.configured);
  }

  function goAccount() {
    stopped = true;
    if (timer) window.clearInterval(timer);
    window.location.replace('/account');
  }

  async function check() {
    if (busy || stopped) return;
    busy = true;
    try {
      const me = await get('/auth/me');
      if (!me) return;
      const role = String(me.role || '').toLowerCase();
      if (privilegedRoles.has(role)) {
        goAccount();
        return;
      }

      const [dashboard, subscription] = await Promise.all([
        get('/account/mt5/dashboard'),
        get('/account/mt5/subscription'),
      ]);
      if (connected(dashboard) && Boolean(subscription?.active)) goAccount();
    } catch {
      // A temporary API error must never be treated as a reason to show onboarding.
    } finally {
      busy = false;
    }
  }

  function checkSoon() {
    [50, 150, 350, 700, 1200, 2000].forEach(delay => window.setTimeout(check, delay));
  }

  check();
  timer = window.setInterval(() => {
    if (!document.hidden) check();
  }, 1500);

  document.addEventListener('submit', event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.matches('[data-login],[data-signup]')) checkSoon();
  }, true);

  document.addEventListener('click', event => {
    const target = event.target instanceof Element ? event.target.closest('button,a') : null;
    if (target?.closest('[data-login],[data-signup]')) checkSoon();
  }, true);

  window.addEventListener('focus', check);
  window.addEventListener('pageshow', check);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) check();
  });
})();