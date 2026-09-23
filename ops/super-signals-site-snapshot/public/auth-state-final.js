(() => {
  const loginSelectors = '.home-auth-login,.home-auth-signup,.mobile-auth-login,.mobile-auth-signup,.mobile-header-login,.mobile-header-signup';
  const accountSelectors = '.home-auth-account,.mobile-auth-account,.mobile-header-account';
  let checking = false;

  function setImportantDisplay(node, value) {
    if (!(node instanceof HTMLElement)) return;
    node.style.setProperty('display', value, 'important');
  }

  function applySignedInState(signedIn) {
    document.documentElement.dataset.smartSignalsSignedIn = signedIn ? 'true' : 'false';
    document.querySelectorAll(loginSelectors).forEach((node) => {
      node.hidden = signedIn;
      setImportantDisplay(node, signedIn ? 'none' : 'inline-flex');
    });
    document.querySelectorAll(accountSelectors).forEach((node) => {
      node.hidden = !signedIn;
      setImportantDisplay(node, signedIn ? 'inline-flex' : 'none');
    });
  }

  async function reconcileFromSession() {
    if (checking) return;
    checking = true;
    try {
      const response = await fetch('/account-api/auth/me', {
        credentials: 'include',
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      });
      if (response.status === 401 || response.status === 403) {
        applySignedInState(false);
      } else if (response.ok) {
        applySignedInState(true);
      }
    } catch {
      // A network failure must not visually log an authenticated member out.
    } finally {
      checking = false;
    }
  }

  const observer = new MutationObserver(() => {
    const signedIn = document.documentElement.dataset.smartSignalsSignedIn;
    if (signedIn === 'true') applySignedInState(true);
    if (signedIn === 'false') applySignedInState(false);
  });

  function boot() {
    observer.observe(document.documentElement, {subtree:true,childList:true});
    void reconcileFromSession();
    window.setTimeout(() => void reconcileFromSession(), 300);
    window.setTimeout(() => void reconcileFromSession(), 1200);
    window.setInterval(() => { if (!document.hidden) void reconcileFromSession(); }, 10000);
    window.addEventListener('focus', () => void reconcileFromSession());
    window.addEventListener('pageshow', () => void reconcileFromSession());
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void reconcileFromSession(); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true});
  else boot();
})();
