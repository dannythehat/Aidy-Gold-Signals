(() => {
  const path = window.location.pathname.replace(/\/$/, '') || '/';
  const page = path === '/' ? 'home'
    : path === '/performance' || path.endsWith('/performance.html') ? 'performance'
    : path === '/how-it-works' || path.endsWith('/how-smart-signals-works.html') ? 'guide'
    : path === '/join' || path.endsWith('/join-launch.html') || path.endsWith('/join.html') ? 'join'
    : path === '/account' || path.endsWith('/account.html') ? 'account'
    : 'other';

  document.body.classList.add('premium-v3', `page-${page}`);

  const setText = (selector, value) => {
    const node = document.querySelector(selector);
    if (node) node.textContent = value;
  };

  function compactHome() {
    setText('.hero-sub', 'We audit hundreds of Gold signal providers. Only the ones that keep proving themselves reach Smart Signals Trading.');

    const databaseCopy = document.querySelector('#what-we-do .database-copy > p:last-child');
    if (databaseCopy) databaseCopy.textContent = 'Every signal, update, win and loss is stored. Providers are re-audited every month.';
    const databasePoints = document.querySelectorAll('#what-we-do .database-point');
    const databaseLines = [
      'Free and paid Gold providers, tracked side by side.',
      'Signals, edits, closes, wins and losses stay together.',
      'Every provider has to keep earning approval.',
      'Only proven providers reach Smart Signals Trading.'
    ];
    databasePoints.forEach((point, index) => {
      const copy = point.querySelector('div > span');
      if (copy && databaseLines[index]) copy.textContent = databaseLines[index];
    });

    const tradingCopy = document.querySelector('#smart-signals-trading .split-copy');
    if (tradingCopy) {
      const paragraphs = tradingCopy.querySelectorAll(':scope > p');
      if (paragraphs[0]) paragraphs[0].textContent = 'Approved Gold signals arrive in one organised workflow: entry, stop, targets, updates and close.';
      if (paragraphs[1]) paragraphs[1].remove();
    }
    const tradingCards = document.querySelectorAll('#smart-signals-trading .trading-card p');
    const tradingLines = [
      'An approved provider sends a Gold trade idea.',
      'Entry, SL and targets are structured in context.',
      'Later edits and closes stay tied to the same trade.'
    ];
    tradingCards.forEach((node, index) => { if (tradingLines[index]) node.textContent = tradingLines[index]; });

    const resultsLead = document.querySelector('#results .section-lead');
    if (resultsLead) resultsLead.textContent = 'Daily profit and loss stays public, with every published trading day available to review.';
    const resultCards = document.querySelectorAll('#results .performance-teaser-card p');
    const resultLines = [
      'Review daily and monthly performance in one public ledger.',
      'Account replay will use the sizing policy that applied at the time.',
      'A separate funded $100 → $1,000 challenge starts 10 September.'
    ];
    resultCards.forEach((node, index) => { if (resultLines[index]) node.textContent = resultLines[index]; });

    setText('#how-it-works .section-lead', 'Four steps explain the whole system. Open the full guide only if you want the detail.');
    const homeSteps = document.querySelectorAll('#how-it-works .step-card p');
    const stepLines = [
      'We find Gold sources worth testing.',
      'We record the full wins-and-losses history.',
      'We learn how each provider communicates.',
      'We follow approved trades from entry to close.'
    ];
    homeSteps.forEach((node, index) => { if (stepLines[index]) node.textContent = stepLines[index]; });

    const onboarding = document.querySelector('#onboarding');
    if (onboarding) {
      onboarding.className = 'content-section onboarding-section canonical-home-onboarding';
      onboarding.innerHTML = `
        <div class="section-shell">
          <div class="section-head">
            <p class="section-kicker">Join Smart Signals</p>
            <h2 id="onboarding-title">From evidence to connected in four steps.</h2>
            <p class="section-lead">Check the results first. If it makes sense for you, the secure Join page handles the rest.</p>
            <div class="onboarding-price"><strong>€99</strong><span>/ month</span><span>or €999 / year</span></div>
          </div>
          <div class="onboarding-track" aria-label="How to join Smart Signals">
            <article class="onboarding-step" data-step="01">
              <span class="onboarding-step__tag">01 · Evidence</span>
              <h3>Check the results.</h3>
              <p>Review the public daily performance record.</p>
              <div class="onboarding-step__action"><a class="onboarding-button" href="/performance">See results</a></div>
            </article>
            <article class="onboarding-step" data-step="02">
              <span class="onboarding-step__tag">02 · Broker</span>
              <h3>Open Vantage.</h3>
              <p>Your trading funds stay with your broker.</p>
              <div class="onboarding-step__action"><a class="onboarding-button" href="https://vigco.co/la-com-inv/rVbJG9xZ" target="_blank" rel="noopener noreferrer">Open Vantage ↗</a></div>
            </article>
            <article class="onboarding-step" data-step="03">
              <span class="onboarding-step__tag">03 · Membership</span>
              <h3>Activate Smart Signals.</h3>
              <p>Choose monthly or annual inside the secure Join flow.</p>
              <div class="onboarding-step__action"><a class="onboarding-button" href="/join#membership">Choose membership</a></div>
            </article>
            <article class="onboarding-step" data-step="04">
              <span class="onboarding-step__tag">04 · Connect</span>
              <h3>Connect Vantage MT5.</h3>
              <p>Once approved, connect MT5 and open your account.</p>
              <div class="onboarding-step__action"><a class="onboarding-button" href="/join">Start setup</a></div>
            </article>
          </div>
          <div class="performance-teaser-actions">
            <a class="performance-teaser-button" href="/join">Join Smart Signals →</a>
            <a class="performance-teaser-note" href="/how-it-works">See how provider approval works</a>
          </div>
        </div>`;
    }

    document.querySelectorAll('.onboarding-placeholder,.onboarding-button--pending').forEach((node) => node.remove());
  }

  function compactGuide() {
    setText('.guide-hero__lead', 'We reduce hundreds of Gold signal sources to the small number that keep earning approval.');
    const intros = document.querySelectorAll('.guide-section__intro');
    const introLines = [
      'We judge the full record, not followers, screenshots or one strong week.',
      'The database keeps the trade instructions as well as the final result.',
      'After approval, every update must stay connected to the correct live trade.'
    ];
    intros.forEach((node, index) => { if (introLines[index]) node.textContent = introLines[index]; });

    const rows = document.querySelectorAll('.process-row');
    const rowCopy = [
      ['We track free and paid Gold sources in real time.', 'Members must receive the same signal we audit.'],
      ['Entries, stops, targets, edits and outcomes stay in one record.', 'Nothing disappears because a trade lost.'],
      ['Consistency over time matters more than a lucky week.', 'Risk and repeatability matter.'],
      ['We learn each provider’s wording and trade-management style.', 'Updates must attach to the right trade.'],
      ['Only sources with strong evidence reach the app.', 'Approval stays selective.'],
      ['Every approved provider is reviewed again each month.', 'Weakening performance can remove approval.']
    ];
    rows.forEach((row, index) => {
      const p = row.querySelector('div:nth-child(2) p');
      const proof = row.querySelector('.process-proof');
      if (p && rowCopy[index]) p.textContent = rowCopy[index][0];
      if (proof && rowCopy[index]) proof.innerHTML = `<strong>Gate</strong>${rowCopy[index][1]}`;
    });

    document.querySelectorAll('.audit-list').forEach((list) => {
      [...list.children].slice(4).forEach((item) => item.remove());
    });
    const principle = document.querySelector('.guide-principle p');
    if (principle) principle.textContent = 'Approved providers keep their place only while the evidence continues to support them.';
  }

  function compactPerformance() {
    const heroCopy = document.querySelector('.perf-shell .hero > p:not(.eyebrow)');
    if (heroCopy) heroCopy.textContent = 'Daily P/L from 6 August. Reconstructed days are labelled clearly; verified live tracking begins 31 August.';
    const sectionIntros = document.querySelectorAll('.perf-shell .section-head p');
    if (sectionIntros[0]) sectionIntros[0].textContent = 'Tap a trading day for its start balance, P/L and end balance.';
    if (sectionIntros[1]) sectionIntros[1].textContent = 'Every published trading day in one ledger.';
    const footnote = document.querySelector('.ledger-footnote');
    if (footnote) footnote.textContent = '6–28 August is reconstructed. Verified tracking begins 31 August.';
    const challenge = document.querySelector('.challenge-card p:not(.eyebrow)');
    if (challenge) challenge.textContent = 'A separate funded account starts 10 September. Its results stay independent from the main ledger.';
  }

  function compactJoin() {
    const heroCopy = document.querySelector('.page-join .hero > p:not(.eyebrow)');
    if (heroCopy) heroCopy.textContent = 'Create your account, open Vantage, activate membership and connect MT5.';
    const accountLead = document.querySelector('#account .lead');
    if (accountLead) accountLead.textContent = 'One Smart Signals login for the website and app.';
    const vantageLead = document.querySelector('#vantage .lead');
    if (vantageLead) vantageLead.textContent = 'Your funds stay with Vantage. Smart Signals only uses the broker connection you authorise.';
    const approvalLead = document.querySelector('#approval .lead');
    if (approvalLead) approvalLead.textContent = 'Submit payment, then membership activates after approval.';
    const mt5Lead = document.querySelector('#mt5 .lead');
    if (mt5Lead) mt5Lead.textContent = 'When membership is active, enter your Vantage MT5 details to connect.';
    const readyCopy = document.querySelector('#ready p:not(.eyebrow)');
    if (readyCopy) readyCopy.textContent = 'Setup complete. Open your account to see your connection and trading activity.';
  }

  function compactAccount() {
    const heroCopy = document.querySelector('.member-hero > div > p:last-child');
    if (heroCopy) heroCopy.textContent = 'Your balance, trading status and Smart Signals activity.';
    document.querySelectorAll('.empty-state span').forEach((node) => {
      if (node.textContent.includes('New Smart Signals trades')) node.textContent = 'New trades appear here automatically.';
      if (node.textContent.includes('latest completed')) node.textContent = 'Completed trades appear here.';
    });
  }

  function addReveal() {
    const targets = document.querySelectorAll('.content-section,.panel,.guide-section,.guide-hero,.guide-cta,.page-join .card,.member-shell > section');
    if (!('IntersectionObserver' in window) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -5% 0px', threshold: .06 });
    targets.forEach((target) => { target.classList.add('premium-reveal'); observer.observe(target); });
  }

  function goldBar() {
    if (!['home','performance','guide','join','account'].includes(page)) return;
    const header = document.querySelector('.site-header,.perf-header,.guide-header,.topbar,.member-header');
    if (!header || document.querySelector('[data-live-gold-wrap]')) return;

    const wrap = document.createElement('div');
    wrap.className = 'live-gold-wrap';
    wrap.dataset.liveGoldWrap = 'true';
    wrap.innerHTML = `
      <div class="live-gold-bar" role="status" aria-live="polite" aria-label="XAUUSD Gold market price">
        <div class="live-gold-symbol">XAUUSD · GOLD</div>
        <strong class="live-gold-price" data-gold-price>—</strong>
        <div class="live-gold-detail"><span>Bid</span><strong data-gold-bid>—</strong></div>
        <div class="live-gold-detail"><span>Ask</span><strong data-gold-ask>—</strong></div>
        <span class="live-gold-state is-offline" data-gold-state>CONNECTING</span>
      </div>`;
    header.insertAdjacentElement('afterend', wrap);

    const priceNode = wrap.querySelector('[data-gold-price]');
    const bidNode = wrap.querySelector('[data-gold-bid]');
    const askNode = wrap.querySelector('[data-gold-ask]');
    const stateNode = wrap.querySelector('[data-gold-state]');
    let lastPrice = null;
    let timer = null;
    const format = (value) => Number.isFinite(Number(value)) ? Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';

    async function refresh() {
      try {
        const response = await fetch('/api/gold-price', { cache: 'no-store', headers: { Accept: 'application/json' } });
        if (!response.ok) throw new Error('quote_unavailable');
        const quote = await response.json();
        if (!quote.available || !Number.isFinite(Number(quote.price))) throw new Error('quote_unavailable');
        const nextPrice = Number(quote.price);
        priceNode.classList.remove('live-gold-flash-up','live-gold-flash-down');
        if (lastPrice !== null && nextPrice !== lastPrice) {
          void priceNode.offsetWidth;
          priceNode.classList.add(nextPrice > lastPrice ? 'live-gold-flash-up' : 'live-gold-flash-down');
        }
        lastPrice = nextPrice;
        priceNode.textContent = `$${format(nextPrice)}`;
        bidNode.textContent = format(quote.bid);
        askNode.textContent = format(quote.ask);
        stateNode.classList.remove('is-offline','is-stale');
        if (quote.stale || quote.market_state === 'closed') {
          stateNode.classList.add('is-stale');
          stateNode.textContent = quote.market_state === 'closed' ? 'MARKET CLOSED' : 'STALE';
        } else {
          stateNode.textContent = 'LIVE';
        }
      } catch {
        stateNode.classList.add('is-offline');
        stateNode.classList.remove('is-stale');
        stateNode.textContent = lastPrice === null ? 'UNAVAILABLE' : 'RECONNECTING';
      }
    }

    function schedule() {
      if (timer) window.clearInterval(timer);
      timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 2500);
    }
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh(); });
    void refresh();
    schedule();
  }

  if (page === 'home') compactHome();
  if (page === 'guide') compactGuide();
  if (page === 'performance') compactPerformance();
  if (page === 'join') compactJoin();
  if (page === 'account') compactAccount();
  goldBar();
  addReveal();
})();
