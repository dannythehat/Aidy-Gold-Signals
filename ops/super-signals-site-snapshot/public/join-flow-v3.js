(() => {
  const API_BASE = '/account-api';
  const VANTAGE_MT5_GUIDE = 'https://www.vantagemarkets.com/en-za/academy/how-to-log-in-to-metatrader-5/';
  const progressList = document.querySelector('[data-progress-list]');
  const vantageSection = document.querySelector('#vantage');
  const modeSection = document.querySelector('#accounts');
  const subscriptionSection = document.querySelector('#subscription');
  const readySection = document.querySelector('#ready');

  if (!progressList || !vantageSection || !modeSection || !subscriptionSection || !readySection) return;

  let connectedEnvironment = null;

  function addStylesheet() {
    if (document.querySelector('link[href="/join-mt5.css"]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/join-mt5.css';
    document.head.appendChild(link);
  }

  function rebuildProgress() {
    progressList.innerHTML = `
      <button class="progress-step" type="button" data-jump="account"><span>01</span><div><strong>Account</strong><small>Email + password</small></div><b data-progress="account">Start</b></button>
      <button class="progress-step" type="button" data-jump="vantage"><span>02</span><div><strong>Vantage</strong><small>Your broker</small></div><b data-progress="vantage">Next</b></button>
      <button class="progress-step" type="button" data-jump="mt5"><span>03</span><div><strong>Connect MT5</strong><small>Link trading account</small></div><b data-progress="mt5">Next</b></button>
      <button class="progress-step" type="button" data-jump="accounts"><span>04</span><div><strong>Trade mode</strong><small>Paper or real</small></div><b data-progress="accounts">Next</b></button>
      <button class="progress-step" type="button" data-jump="subscription"><span>05</span><div><strong>Subscription</strong><small>€99/month</small></div><b data-progress="subscription">Next</b></button>
      <button class="progress-step" type="button" data-jump="ready"><span>06</span><div><strong>Ready</strong><small>Open Smart Signals</small></div><b data-progress="ready">Finish</b></button>
    `;

    [...progressList.querySelectorAll('.progress-step')].forEach((step) => {
      step.addEventListener('click', () => document.getElementById(step.dataset.jump)?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    });
  }

  function renumberExistingSections() {
    const modeNumber = modeSection.querySelector('.setup-card__number');
    const subNumber = subscriptionSection.querySelector('.setup-card__number');
    const readyNumber = readySection.querySelector('.setup-card__number');
    if (modeNumber) modeNumber.textContent = '04';
    if (subNumber) subNumber.textContent = '05';
    if (readyNumber) readyNumber.textContent = '06';
    modeSection.classList.add('setup-card--mode');

    const modeKicker = modeSection.querySelector('.eyebrow');
    if (modeKicker) modeKicker.textContent = 'Choose which connected account trades';
    const modeTitle = modeSection.querySelector('h2');
    if (modeTitle) modeTitle.textContent = 'Paper or real. Only one can be active.';
    const modeLead = modeSection.querySelector('.setup-lead');
    if (modeLead) modeLead.innerHTML = 'Connect MT5 first. Then choose whether Smart Signals should trade the <strong>Paper</strong> or <strong>Real</strong> account. Turning one on always switches the other off.';

    const paperTitle = modeSection.querySelector('[data-account-choice="demo"] strong');
    const liveTitle = modeSection.querySelector('[data-account-choice="live"] strong');
    if (paperTitle) paperTitle.textContent = 'Use Paper Account';
    if (liveTitle) liveTitle.textContent = 'Use Real Trading Account';
  }

  function buildMt5Section() {
    const section = document.createElement('section');
    section.className = 'setup-card setup-card--mt5';
    section.id = 'mt5';
    section.dataset.stage = 'mt5';
    section.setAttribute('aria-labelledby', 'mt5-title');
    section.innerHTML = `
      <div class="setup-card__number">03</div>
      <div class="setup-card__head">
        <div>
          <p class="eyebrow">Connect your trading account</p>
          <h2 id="mt5-title">Connect MT5 first.</h2>
        </div>
        <span class="stage-state stage-state--blue" data-mt5-state>Checking account…</span>
      </div>
      <p class="setup-lead">MT5 is the trading account inside Vantage. If you already connected MT5 in the Smart Signals app, we will recognise it here automatically.</p>

      <div class="mt5-help-card">
        <div class="mt5-help-card__badge">MT5</div>
        <div>
          <strong>Where do I find my MT5 details?</strong>
          <p>Vantage provides your MT5 account number, password and exact server in your welcome email and inside the Vantage Client Portal.</p>
        </div>
        <a class="mt5-guide-link" href="${VANTAGE_MT5_GUIDE}" target="_blank" rel="noopener noreferrer">Vantage guide →</a>
      </div>

      <form class="mt5-connect-form" data-mt5-connect-form autocomplete="off">
        <label>MT5 account number<input name="login" inputmode="numeric" autocomplete="off" placeholder="e.g. 12345678" required /></label>
        <label>Exact Vantage server<input name="server" autocomplete="off" placeholder="Copy it exactly from Vantage" required /></label>
        <label>MT5 trading password<input name="password" type="password" autocomplete="off" placeholder="Your MT5 trading password" required /></label>
        <p class="mt5-connect-note">Only use this form if no MT5 account is already connected to your Smart Signals login. Your MT5 trading password is used to establish the connection and is not stored.</p>
        <button class="mt5-connect-action" type="submit">Connect my MT5 account</button>
      </form>

      <div class="mt5-connection-message" data-mt5-message role="status"></div>

      <div class="broker-balance-card" data-broker-balance>
        <div class="broker-balance-card__top"><span>Your connected MT5 account</span><strong data-broker-environment>Connected</strong></div>
        <div class="broker-balance-grid">
          <div><span>Balance</span><strong data-broker-balance-value>—</strong><small>Your broker balance</small></div>
          <div><span>Equity</span><strong data-broker-equity-value>—</strong><small>Balance including open trades</small></div>
        </div>
        <div class="broker-balance-meta"><span data-broker-login>MT5 connected</span><span data-broker-server>Vantage</span></div>
      </div>
    `;
    modeSection.parentNode.insertBefore(section, modeSection);
    return section;
  }

  function setMessage(text, tone = 'error') {
    const el = document.querySelector('[data-mt5-message]');
    if (!el) return;
    el.textContent = text;
    el.className = `mt5-connection-message is-visible is-${tone}`;
  }

  function clearMessage() {
    const el = document.querySelector('[data-mt5-message]');
    if (!el) return;
    el.textContent = '';
    el.className = 'mt5-connection-message';
  }

  function formatMoney(value, currency) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
    try {
      return new Intl.NumberFormat(undefined, { style: 'currency', currency: currency || 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value));
    } catch {
      return `${currency || '$'} ${Number(value).toFixed(2)}`;
    }
  }

  function markMt5Done(done) {
    const state = document.querySelector('[data-mt5-state]');
    if (state) {
      state.textContent = done ? 'Connected' : 'Not connected';
      state.classList.toggle('is-connected', done);
    }
    const progress = document.querySelector('[data-progress="mt5"]');
    const step = progress?.closest('.progress-step');
    if (progress) progress.textContent = done ? 'Done' : 'Next';
    if (step) step.classList.toggle('is-done', done);
    document.dispatchEvent(new CustomEvent('smart-signals-mt5-state', { detail: { connected: done, environment: connectedEnvironment } }));
  }

  function syncTradeModeFromConnectedAccount(environment) {
    const normalized = environment === 'demo' ? 'demo' : environment === 'live' ? 'live' : null;
    if (!normalized) return;

    const matchingButton = modeSection.querySelector(`[data-account-choice="${normalized}"]`);
    const otherButton = modeSection.querySelector(`[data-account-choice="${normalized === 'demo' ? 'live' : 'demo'}"]`);

    if (matchingButton) {
      matchingButton.disabled = false;
      matchingButton.click();
      matchingButton.classList.add('is-connected-account');
      const strong = matchingButton.querySelector('strong');
      if (strong) strong.textContent = normalized === 'demo' ? 'Paper Account Connected' : 'Real Trading Account Connected';
    }

    if (otherButton) {
      otherButton.disabled = true;
      otherButton.classList.remove('is-selected', 'is-connected-account');
      otherButton.setAttribute('aria-checked', 'false');
      otherButton.setAttribute('aria-pressed', 'false');
      const switchText = otherButton.querySelector('.account-choice__switch em');
      if (switchText) switchText.textContent = 'OFF';
    }

    const state = modeSection.querySelector('[data-account-choice-state]');
    if (state) state.textContent = normalized === 'demo' ? 'Paper connected' : 'Real connected';
  }

  function showDashboard(data) {
    const card = document.querySelector('[data-broker-balance]');
    if (!card) return;
    const connected = data?.connection?.status === 'connected' || Boolean(data?.account);
    if (!connected) {
      connectedEnvironment = null;
      card.classList.remove('is-visible');
      document.querySelector('[data-mt5-connect-form]')?.classList.remove('is-hidden');
      markMt5Done(false);
      return;
    }

    connectedEnvironment = data?.connection?.account_environment || null;
    const currency = data?.account?.currency || 'USD';
    card.classList.add('is-visible');
    document.querySelector('[data-mt5-connect-form]')?.classList.add('is-hidden');

    const balance = card.querySelector('[data-broker-balance-value]');
    const equity = card.querySelector('[data-broker-equity-value]');
    const environment = card.querySelector('[data-broker-environment]');
    const login = card.querySelector('[data-broker-login]');
    const server = card.querySelector('[data-broker-server]');

    if (balance) balance.textContent = formatMoney(data?.account?.balance, currency);
    if (equity) equity.textContent = formatMoney(data?.account?.equity, currency);
    if (environment) environment.textContent = connectedEnvironment === 'demo' ? 'Paper MT5 connected' : 'Real MT5 connected';
    if (login) login.textContent = data?.connection?.login_masked || 'MT5 connected';
    if (server) server.textContent = data?.connection?.server || 'Vantage MT5';

    markMt5Done(true);
    syncTradeModeFromConnectedAccount(connectedEnvironment);
    setMessage('Existing MT5 connection found. Your website and app are using the same Smart Signals account.', 'success');
  }

  async function loadDashboard() {
    try {
      const response = await fetch(`${API_BASE}/account/mt5/dashboard`, { credentials: 'include', cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) {
        connectedEnvironment = null;
        markMt5Done(false);
        return;
      }
      const data = await response.json();
      showDashboard(data);
    } catch {
      connectedEnvironment = null;
      markMt5Done(false);
    }
  }

  function readableError(body) {
    const detail = body?.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail.message === 'string') return detail.message;
    return 'MT5 could not be connected. Check the account number, password and exact Vantage server.';
  }

  function wireConnectForm() {
    const form = document.querySelector('[data-mt5-connect-form]');
    if (!form) return;
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      clearMessage();
      const button = form.querySelector('button[type="submit"]');
      const formData = new FormData(form);
      const payload = {
        login: String(formData.get('login') || '').trim(),
        server: String(formData.get('server') || '').trim(),
        password: String(formData.get('password') || ''),
      };
      if (button) { button.disabled = true; button.textContent = 'Connecting…'; }
      try {
        const response = await fetch(`${API_BASE}/account/mt5/connect`, {
          method: 'POST', credentials: 'include', cache: 'no-store', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(readableError(body));
        setMessage('MT5 connected. Your broker balance and equity are now linked to your Smart Signals account.', 'success');
        form.reset();
        await loadDashboard();
        modeSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } catch (error) {
        setMessage(error instanceof Error ? error.message : 'MT5 could not be connected.');
      } finally {
        if (button) { button.disabled = false; button.textContent = 'Connect my MT5 account'; }
      }
    });
  }

  function lockTradeModeUntilMt5() {
    const grid = modeSection.querySelector('.account-choice-grid');
    const buttons = [...modeSection.querySelectorAll('.account-choice')];
    const note = document.createElement('div');
    note.className = 'mode-lock-message';
    note.innerHTML = '<span>3</span><div><strong>Connect MT5 first</strong><p>Paper / Real selection unlocks after your MT5 account is connected.</p></div>';
    modeSection.querySelector('.exclusive-note')?.insertAdjacentElement('afterend', note);

    function setLocked(locked, environment = null) {
      grid?.classList.toggle('is-locked', locked);
      buttons.forEach((button) => {
        if (locked) {
          button.disabled = true;
        } else if (environment) {
          button.disabled = button.dataset.accountChoice !== environment;
        } else {
          button.disabled = false;
        }
      });
      note.style.display = locked ? 'flex' : 'none';
    }

    setLocked(true);
    document.addEventListener('smart-signals-mt5-state', (event) => {
      const connected = Boolean(event.detail?.connected);
      const environment = event.detail?.environment === 'demo' ? 'demo' : event.detail?.environment === 'live' ? 'live' : null;
      setLocked(!connected, connected ? environment : null);
    });
  }

  function updateReadyChecklist() {
    const checklist = readySection.querySelector('.ready-checklist');
    if (!checklist) return;
    const tradeRow = checklist.querySelector('[data-ready-check="trade-mode"]');
    const mt5Row = document.createElement('div');
    mt5Row.dataset.readyCheck = 'mt5';
    mt5Row.innerHTML = '<i>○</i><span>MT5 account connected</span><strong>Required</strong>';
    if (tradeRow) checklist.insertBefore(mt5Row, tradeRow);
    else checklist.appendChild(mt5Row);

    document.addEventListener('smart-signals-mt5-state', (event) => {
      const done = Boolean(event.detail?.connected);
      mt5Row.classList.toggle('is-done', done);
      const icon = mt5Row.querySelector('i');
      const status = mt5Row.querySelector('strong');
      if (icon) icon.textContent = done ? '✓' : '○';
      if (status) status.textContent = done ? 'Connected' : 'Required';
    });
  }

  addStylesheet();
  rebuildProgress();
  renumberExistingSections();
  buildMt5Section();
  lockTradeModeUntilMt5();
  updateReadyChecklist();
  wireConnectForm();
  loadDashboard();
})();
