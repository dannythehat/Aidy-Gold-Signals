const VANTAGE_AFFILIATE_URL = 'https://vigco.co/la-com-inv/rVbJG9xZ';

function ensureStylesheet(href) {
  if (document.querySelector(`link[href^="${href}"]`)) return;
  const style = document.createElement('link');
  style.rel = 'stylesheet';
  style.href = href;
  document.head.appendChild(style);
}

function ensureScript(src) {
  if (document.querySelector(`script[src^="${src}"]`)) return;
  const script = document.createElement('script');
  script.src = src;
  script.defer = true;
  document.head.appendChild(script);
}

function ensureAccountFlowAssets() {
  ensureStylesheet('/join-depth.css?v=20260830-premium1');
  ensureStylesheet('/join-mt5.css');
  ensureStylesheet('/join-mobile-fix.css?v=20260830-launch2');
  ensureStylesheet('/launch-depth.css?v=20260830-launch2');
  ensureStylesheet('/premium-v2.css?v=20260830-premium1');
  ensureScript('/join-flow-v3.js');
  ensureScript('/launch-fixes.js?v=20260830-launch2');
}

async function wireMemberAreaLink() {
  try {
    const response = await fetch('/account-api/auth/me', {
      credentials: 'include',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return;

    const actions = document.querySelector('.join-header__actions');
    if (!actions || actions.querySelector('a[href="/account.html"]')) return;

    const link = document.createElement('a');
    link.href = '/account.html';
    link.className = 'member-area-link';
    link.textContent = 'My Smart Signals';
    actions.insertBefore(link, actions.querySelector('a[href="/"]'));
  } catch {
    // The onboarding page remains usable even if the account check is unavailable.
  }
}

function fallbackCopy(text) {
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  const ok = document.execCommand('copy');
  textarea.remove();
  return ok;
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return true;
  }
  return fallbackCopy(text);
}

function showPaymentNotice(message) {
  const notice = document.querySelector('[data-payment-copy-notice]');
  if (!notice) return;
  notice.textContent = `✓ ${message}`;
  notice.classList.add('is-visible');
  window.clearTimeout(showPaymentNotice.timer);
  showPaymentNotice.timer = window.setTimeout(() => notice.classList.remove('is-visible'), 2200);
}

function wireCopyButtons() {
  document.querySelectorAll('[data-copy-value]').forEach((button) => {
    if (button.dataset.copyWired === 'true') return;
    button.dataset.copyWired = 'true';
    button.addEventListener('click', async () => {
      const value = button.dataset.copyValue || '';
      const label = button.dataset.copyLabel || 'Copied';
      try {
        await copyText(value);
        button.classList.add('is-copied');
        showPaymentNotice(label);
        window.setTimeout(() => button.classList.remove('is-copied'), 1300);
      } catch {
        showPaymentNotice('Press and hold the detail to copy');
      }
    });
  });
}

function wireVantageAffiliate() {
  const action = document.querySelector('.vantage-action');
  if (!action || action.dataset.vantageWired === 'true') return;
  action.dataset.vantageWired = 'true';

  action.classList.add('vantage-action--brand-card');
  action.innerHTML = `
    <div class="vantage-signup-intro">
      <span>DON'T HAVE VANTAGE YET?</span>
      <strong>Open your Vantage account through Smart Signals.</strong>
      <p>Use our official Vantage signup link, then come back here to connect your MT5 account.</p>
    </div>
    <a class="vantage-brand-card" href="${VANTAGE_AFFILIATE_URL}" target="_blank" rel="sponsored noopener noreferrer" aria-label="Sign up to Vantage through Smart Signals">
      <img src="/assets/vantage/vantage-signup.svg" alt="Vantage" />
      <span class="vantage-brand-card__cta">SIGN UP HERE <b>→</b></span>
    </a>
  `;

  const readyStatus = document.querySelector('.ready-checklist > div:nth-child(2) strong');
  if (readyStatus) readyStatus.textContent = 'Signup link ready';
}

ensureAccountFlowAssets();
wireVantageAffiliate();
wireCopyButtons();
wireMemberAreaLink();