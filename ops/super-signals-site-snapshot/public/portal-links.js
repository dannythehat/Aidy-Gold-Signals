const VANTAGE_AFFILIATE_URL = 'https://vigco.co/la-com-inv/rVbJG9xZ';
const SMART_SIGNALS_USDC_WALLET = '3x2NNMLoNs7uNbTx424ueEhEkGP1n6eDdc5iTXU4iFTF';
const SMART_SIGNALS_USDC_NETWORK = 'Solana';

function wirePortalLinks() {
  document.querySelectorAll('a[href="#start"]').forEach((link) => {
    link.setAttribute('href', '/join.html?mode=signup#account');
  });
}

function canonicalHomepageOnboardingMarkup() {
  return `
    <div class="section-shell canonical-onboarding-shell">
      <div class="section-head canonical-onboarding-head">
        <p class="section-kicker">Join Smart Signals</p>
        <h2>Everything you need. No missing steps.</h2>
        <p class="section-lead">Check the evidence first, then create your Smart Signals account, open Vantage, connect MT5 and activate your €99/month membership.</p>
        <div class="canonical-onboarding-price"><strong>€99</strong><span>per month · USDC · Solana</span></div>
      </div>

      <div class="canonical-onboarding-grid">
        <article class="canonical-step canonical-step--cyan" data-step="01">
          <span class="canonical-step__tag">Results</span>
          <h3>See our results.</h3>
          <p>Review the public daily and monthly performance record before you join.</p>
          <a class="canonical-step__button" href="/performance.html">View results →</a>
        </article>

        <article class="canonical-step canonical-step--green" data-step="02">
          <span class="canonical-step__tag">How we work</span>
          <h3>See how signals earn a place.</h3>
          <p>Understand how providers are tracked, audited and continuously reviewed.</p>
          <a class="canonical-step__button" href="/how-smart-signals-works.html">How Smart Signals works →</a>
        </article>

        <article class="canonical-step canonical-step--blue" data-step="03">
          <span class="canonical-step__tag">Your account</span>
          <h3>Create or log in.</h3>
          <p>One Smart Signals identity for both the website and trading app.</p>
          <div class="canonical-step__actions">
            <a class="canonical-step__button" href="/join.html?mode=signup#account">Sign up →</a>
            <a class="canonical-step__button canonical-step__button--secondary" href="/join.html?mode=login#account">Log in</a>
          </div>
        </article>

        <article class="canonical-step canonical-step--gold" data-step="04">
          <span class="canonical-step__tag">Vantage</span>
          <h3>Open your Vantage account.</h3>
          <p>Use the Smart Signals Vantage affiliate signup. Your trading funds stay with Vantage.</p>
          <a class="canonical-step__button canonical-step__button--gold" href="${VANTAGE_AFFILIATE_URL}" target="_blank" rel="sponsored noopener noreferrer">Sign up to Vantage →</a>
        </article>

        <article class="canonical-step canonical-step--violet" data-step="05">
          <span class="canonical-step__tag">MT5 + trading mode</span>
          <h3>Connect MT5, then choose Paper or Real.</h3>
          <p>Connect your Vantage MT5 first. Smart Signals then uses either your Paper account or Real account — never both at the same time.</p>
          <a class="canonical-step__button" href="/join.html#mt5">Connect MT5 →</a>
        </article>

        <article class="canonical-step canonical-step--payment" data-step="06">
          <span class="canonical-step__tag">Subscription</span>
          <h3>Activate Smart Signals.</h3>
          <p>€99/month paid in USDC on the <strong>Solana network only</strong>.</p>
          <button class="canonical-copy-row" type="button" data-canonical-copy="${SMART_SIGNALS_USDC_WALLET}" aria-label="Copy Smart Signals USDC wallet address">
            <span>USDC wallet</span><strong>${SMART_SIGNALS_USDC_WALLET}</strong><b>Copy</b>
          </button>
          <button class="canonical-copy-row canonical-copy-row--network" type="button" data-canonical-copy="${SMART_SIGNALS_USDC_NETWORK}" aria-label="Copy Solana network">
            <span>Network</span><strong>${SMART_SIGNALS_USDC_NETWORK}</strong><b>Copy</b>
          </button>
          <a class="canonical-step__button canonical-step__button--green" href="/join.html#subscription">Open payment setup →</a>
        </article>
      </div>

      <div class="canonical-onboarding-final">
        <div><span>Already started?</span><strong>Continue your setup or open your member account.</strong></div>
        <a href="/join.html">Open setup portal →</a>
      </div>
    </div>
  `;
}

function syncHomepageOnboarding() {
  if (window.location.pathname !== '/' && window.location.pathname !== '/index.html') return;
  const onboarding = document.querySelector('#onboarding');
  if (!onboarding || onboarding.dataset.canonicalHomeOnboarding === 'true') return;
  onboarding.dataset.canonicalHomeOnboarding = 'true';
  onboarding.classList.add('canonical-home-onboarding');
  onboarding.innerHTML = canonicalHomepageOnboardingMarkup();
}

function replaceLegacyPlaceholdersEverywhere() {
  document.querySelectorAll('.onboarding-placeholder').forEach((box) => {
    const label = (box.querySelector('span')?.textContent || '').trim().toLowerCase();
    const value = box.querySelector('strong');
    if (!value) return;

    if (label.includes('vantage') && label.includes('signup')) {
      value.textContent = 'SMART SIGNALS VANTAGE LINK READY';
      box.dataset.canonicalDetail = 'vantage';
    } else if (label.includes('usdc') && (label.includes('address') || label.includes('wallet'))) {
      value.textContent = SMART_SIGNALS_USDC_WALLET;
      box.dataset.canonicalDetail = 'wallet';
    } else if (label.includes('network')) {
      value.textContent = 'SOLANA ONLY';
      box.dataset.canonicalDetail = 'network';
    }
  });

  document.querySelectorAll('.onboarding-button--pending, .pending-action').forEach((item) => {
    const text = (item.textContent || '').trim().toLowerCase();
    if (text.includes('vantage') && (text.includes('coming') || text.includes('link'))) {
      const link = document.createElement('a');
      link.className = item.className.replace('onboarding-button--pending', '').trim() || 'onboarding-button';
      link.href = VANTAGE_AFFILIATE_URL;
      link.target = '_blank';
      link.rel = 'sponsored noopener noreferrer';
      link.textContent = 'Sign up to Vantage →';
      item.replaceWith(link);
    } else if (text.includes('connection guide coming')) {
      const link = document.createElement('a');
      link.className = item.className.replace('onboarding-button--pending', '').trim() || 'onboarding-button';
      link.href = '/join.html#mt5';
      link.textContent = 'Connect MT5 →';
      item.replaceWith(link);
    }
  });
}

async function copyCanonicalValue(button) {
  const value = button.dataset.canonicalCopy || '';
  if (!value) return;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
    } else {
      const textarea = document.createElement('textarea');
      textarea.value = value;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      textarea.remove();
    }
    const badge = button.querySelector('b');
    if (badge) {
      const old = badge.textContent;
      badge.textContent = 'Copied ✓';
      window.setTimeout(() => { badge.textContent = old || 'Copy'; }, 1500);
    }
  } catch {
    // The value remains visible and can still be selected manually.
  }
}

function wireCanonicalCopyButtons() {
  document.querySelectorAll('[data-canonical-copy]').forEach((button) => {
    if (button.dataset.copyWired === 'true') return;
    button.dataset.copyWired = 'true';
    button.addEventListener('click', () => copyCanonicalValue(button));
  });
}

function ensureHomepageAuthControls() {
  const navCta = document.querySelector('.site-header .nav-cta');
  if (navCta && !document.querySelector('.home-auth-actions')) {
    const wrap = document.createElement('div');
    wrap.className = 'home-auth-actions';
    wrap.setAttribute('aria-label', 'Smart Signals account access');
    wrap.innerHTML = `
      <a class="home-auth-login" href="/join.html?mode=login#account">Log in</a>
      <a class="home-auth-signup" href="/join.html?mode=signup#account">Sign up</a>
      <a class="home-auth-account" href="/account.html" hidden>My account</a>
    `;
    navCta.replaceWith(wrap);
  }

  const header = document.querySelector('.site-header .nav-shell');
  const menuToggle = header?.querySelector('.menu-toggle');
  if (header && menuToggle && !header.querySelector('.mobile-header-auth')) {
    const mobileHeaderAuth = document.createElement('div');
    mobileHeaderAuth.className = 'mobile-header-auth';
    mobileHeaderAuth.setAttribute('aria-label', 'Smart Signals account access');
    mobileHeaderAuth.innerHTML = `
      <a class="mobile-header-login" href="/join.html?mode=login#account">Log in</a>
      <a class="mobile-header-signup" href="/join.html?mode=signup#account">Sign up</a>
      <a class="mobile-header-account" href="/account.html" hidden>My account</a>
    `;
    header.insertBefore(mobileHeaderAuth, menuToggle);
  }

  const mobileCta = document.querySelector('#mobile-menu .mobile-cta');
  if (mobileCta && !document.querySelector('#mobile-menu .mobile-auth-login')) {
    const fragment = document.createDocumentFragment();
    const login = document.createElement('a');
    login.className = 'mobile-auth-login';
    login.href = '/join.html?mode=login#account';
    login.textContent = 'Log in';

    const signup = document.createElement('a');
    signup.className = 'mobile-auth-signup';
    signup.href = '/join.html?mode=signup#account';
    signup.textContent = 'Sign up';

    const account = document.createElement('a');
    account.className = 'mobile-auth-account';
    account.href = '/account.html';
    account.textContent = 'My account';
    account.hidden = true;

    fragment.append(login, signup, account);
    mobileCta.replaceWith(fragment);
  }
}

function setMemberEntryState(signedIn) {
  document.querySelectorAll('.home-auth-login, .home-auth-signup, .mobile-auth-login, .mobile-auth-signup, .mobile-header-login, .mobile-header-signup').forEach((link) => {
    link.hidden = signedIn;
  });
  document.querySelectorAll('.home-auth-account, .mobile-auth-account, .mobile-header-account').forEach((link) => {
    link.hidden = !signedIn;
  });
}

async function wireSignedInMemberLinks() {
  ensureHomepageAuthControls();
  try {
    const response = await fetch('/account-api/auth/me', {
      credentials: 'include',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
    const signedIn = response.ok;
    setMemberEntryState(signedIn);

    if (!signedIn) return;

    const finalPrimary = document.querySelector('.final-cta a.button-primary, #start a.button-primary');
    if (finalPrimary instanceof HTMLAnchorElement) {
      finalPrimary.href = '/account.html';
      finalPrimary.textContent = 'Open My Smart Signals';
    }
  } catch {
    setMemberEntryState(false);
  }
}

function applyJoinAuthMode() {
  if (!/^\/join(?:\.html)?$/.test(window.location.pathname)) return;
  const mode = new URLSearchParams(window.location.search).get('mode');
  if (mode !== 'login' && mode !== 'signup') return;
  const target = document.querySelector(`[data-auth-tab="${mode}"]`);
  if (target instanceof HTMLButtonElement) target.click();
}

function bootPortalLinks() {
  wirePortalLinks();
  replaceLegacyPlaceholdersEverywhere();
  syncHomepageOnboarding();
  wireCanonicalCopyButtons();
  ensureHomepageAuthControls();
  applyJoinAuthMode();
  wireSignedInMemberLinks();
}

bootPortalLinks();
window.addEventListener('DOMContentLoaded', bootPortalLinks, { once: true });

window.setTimeout(() => {
  wirePortalLinks();
  replaceLegacyPlaceholdersEverywhere();
  syncHomepageOnboarding();
  wireCanonicalCopyButtons();
  ensureHomepageAuthControls();
  applyJoinAuthMode();
}, 150);

window.setTimeout(() => {
  replaceLegacyPlaceholdersEverywhere();
  syncHomepageOnboarding();
  wireCanonicalCopyButtons();
  ensureHomepageAuthControls();
}, 600);

if (window.location.pathname === '/' || window.location.pathname === '/index.html') {
  const observer = new MutationObserver(() => {
    replaceLegacyPlaceholdersEverywhere();
    syncHomepageOnboarding();
    wireCanonicalCopyButtons();
    ensureHomepageAuthControls();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  window.setTimeout(() => observer.disconnect(), 4000);
}
