const toggle = document.querySelector('[data-menu-toggle]');
const menu = document.querySelector('[data-mobile-menu]');
const menuLinks = menu ? [...menu.querySelectorAll('a')] : [];

function setMenu(open) {
  if (!toggle || !menu) return;
  toggle.setAttribute('aria-expanded', String(open));
  menu.hidden = !open;
  document.body.classList.toggle('menu-open', open);
}

if (toggle && menu) {
  toggle.addEventListener('click', () => {
    setMenu(toggle.getAttribute('aria-expanded') !== 'true');
  });

  menuLinks.forEach((link) => link.addEventListener('click', () => setMenu(false)));

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      setMenu(false);
      toggle.focus();
    }
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth > 860) setMenu(false);
  });
}

function loadStyle(href, marker) {
  if (document.querySelector(`link[${marker}]`)) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = href;
  link.setAttribute(marker, 'true');
  document.head.appendChild(link);
}

loadStyle('/site-polish.css', 'data-site-polish-css');
loadStyle('/layout-fixes.css', 'data-layout-fixes-css');
loadStyle('/trading-section-fix.css', 'data-trading-section-fix-css');
loadStyle('/database-section.css', 'data-database-section-css');
loadStyle('/onboarding.css', 'data-onboarding-css');
loadStyle('/performance-home.css', 'data-performance-home-css');

const gateStage = document.querySelector('.gate-stage');

if (gateStage) {
  loadStyle('/hero-signals.css', 'data-hero-signals-css');
  loadStyle('/gold-signals.css', 'data-gold-signals-css');
  gateStage.classList.add('gate-stage--signals');
  gateStage.setAttribute(
    'aria-label',
    'Different XAUUSD buy and sell signals move sideways toward the Smart Signals filter. Weak sources are rejected at the filter, while an approved gold signal passes through into Smart Signals Trading.'
  );

  gateStage.innerHTML = `
    <div class="signal-demo" data-signal-demo>
      <div class="signal-demo__caption">Gold signal flow</div>

      <div class="signal-filter" aria-hidden="true"></div>
      <span class="filter-reject filter-reject--1" aria-hidden="true">×</span>
      <span class="filter-reject filter-reject--2" aria-hidden="true">×</span>
      <span class="filter-reject filter-reject--3" aria-hidden="true">×</span>
      <span class="filter-reject filter-reject--4" aria-hidden="true">×</span>
      <div class="approved-path" aria-hidden="true"></div>

      <article class="signal-card signal-theme-cyan signal-lane--1 signal-flow--reject-a" aria-label="XAUUSD buy signal rejected at the Smart Signals filter">
        <div class="signal-card__meta"><span class="signal-card__source">Gold provider</span><span>14:47</span></div>
        <div class="signal-card__title">XAUUSD <span class="signal-buy">BUY</span> 4541</div>
        <div class="signal-card__levels"><span>SL</span><span>4532</span><span>TP1</span><span>4548</span><span>TP2</span><span>4556</span></div>
        <div class="signal-card__reason">Rejected after review</div>
      </article>

      <article class="signal-card signal-theme-violet signal-lane--2 signal-flow--reject-b" aria-label="XAUUSD sell signal rejected at the Smart Signals filter">
        <div class="signal-card__meta"><span class="signal-card__source">Gold provider</span><span>14:49</span></div>
        <div class="signal-card__title">XAUUSD <span class="signal-sell">SELL</span> 4564</div>
        <div class="signal-card__levels"><span>SL</span><span>4576</span><span>TP1</span><span>4556</span><span>TP2</span><span>4548</span></div>
        <div class="signal-card__reason">Provider not approved</div>
      </article>

      <article class="signal-card signal-card--approved signal-theme-green signal-lane--3 signal-flow--approved-a" aria-label="Approved XAUUSD sell signal passes through Smart Signals">
        <div class="signal-card__meta"><span class="signal-card__source">Gold provider</span><span>14:52</span></div>
        <div class="signal-card__title">XAUUSD <span class="signal-sell">SELL</span> 4552</div>
        <div class="signal-card__levels"><span>SL</span><span>4570</span><span>TP1</span><span>4548</span><span>TP2</span><span>4547</span><span>TP3</span><span>4520</span></div>
        <div class="signal-card__reason">Approved provider</div>
      </article>

      <article class="signal-card signal-theme-amber signal-lane--4 signal-flow--reject-c" aria-label="XAUUSD buy signal rejected at the Smart Signals filter">
        <div class="signal-card__meta"><span class="signal-card__source">Gold provider</span><span>14:50</span></div>
        <div class="signal-card__title">XAUUSD <span class="signal-buy">BUY</span> 4538</div>
        <div class="signal-card__levels"><span>SL</span><span>4529</span><span>TP1</span><span>4545</span><span>TP2</span><span>4552</span></div>
        <div class="signal-card__reason">Weak long term record</div>
      </article>

      <article class="signal-card signal-theme-blue signal-lane--1 signal-flow--approved-b" aria-label="XAUUSD sell signal passes toward Smart Signals">
        <div class="signal-card__meta"><span class="signal-card__source">Gold provider</span><span>14:54</span></div>
        <div class="signal-card__title">XAUUSD <span class="signal-sell">SELL</span> 4559</div>
        <div class="signal-card__levels"><span>SL</span><span>4571</span><span>TP1</span><span>4550</span><span>TP2</span><span>4542</span></div>
        <div class="signal-card__reason">Testing complete</div>
      </article>

      <article class="signal-card signal-theme-teal signal-lane--2 signal-flow--reject-d" aria-label="XAUUSD buy signal rejected at the Smart Signals filter">
        <div class="signal-card__meta"><span class="signal-card__source">Gold provider</span><span>14:55</span></div>
        <div class="signal-card__title">XAUUSD <span class="signal-buy">BUY</span> 4547</div>
        <div class="signal-card__levels"><span>SL</span><span>4536</span><span>TP1</span><span>4554</span><span>TP2</span><span>4562</span></div>
        <div class="signal-card__reason">Removed after testing</div>
      </article>

      <article class="trade-output" aria-label="Approved XAUUSD signal structured inside Smart Signals Trading">
        <div class="trade-output__meta">
          <span class="trade-output__brand">Smart Signals Trading</span>
          <span class="trade-output__badge">Approved</span>
        </div>
        <div class="trade-output__title">XAUUSD <span class="signal-sell">SELL</span> 4552</div>
        <div class="trade-output__rows">
          <div class="trade-output__row"><span>SL</span><strong>4570</strong></div>
          <div class="trade-output__row"><span>TP1</span><strong>4548</strong></div>
          <div class="trade-output__row"><span>TP2</span><strong>4547</strong></div>
          <div class="trade-output__row"><span>TP3</span><strong>4520</strong></div>
        </div>
        <div class="trade-output__status">● Gold trade active</div>
      </article>
    </div>
  `;
}

const whatWeDo = document.querySelector('#what-we-do');

if (whatWeDo) {
  whatWeDo.classList.add('database-section');
  whatWeDo.innerHTML = `
    <div class="section-shell">
      <div class="database-intro">
        <div class="database-copy">
          <p class="section-kicker">Super Signals Database</p>
          <h2 id="what-we-do-title">Every gold signal. Every trade. Every result. Stored and audited.</h2>
          <p>We monitor hundreds of Gold signal providers, free and paid. Every call, update, close and profit or loss result is stored in one database so performance can be judged on the full record, not screenshots or a good week.</p>
        </div>

        <div class="database-points" aria-label="How the Super Signals database works">
          <div class="database-point">
            <span class="database-point__icon">01</span>
            <div><strong>Hundreds of providers</strong><span>Free groups and paid VIP channels are tracked side by side.</span></div>
          </div>
          <div class="database-point">
            <span class="database-point__icon">02</span>
            <div><strong>The full trading record</strong><span>Signals, entries, stop changes, targets, closes, wins and losses stay together.</span></div>
          </div>
          <div class="database-point">
            <span class="database-point__icon">03</span>
            <div><strong>Re-audited every month</strong><span>Approval is never permanent. Providers have to keep proving their worth.</span></div>
          </div>
          <div class="database-point">
            <span class="database-point__icon">04</span>
            <div><strong>Only the strongest reach the app</strong><span>Consistently proven Gold providers pass the gate into Smart Signals Trading.</span></div>
          </div>
        </div>
      </div>

      <div class="database-visual" aria-label="Gold signal providers feed every signal and trade result into the Super Signals database. Providers are audited monthly and only approved providers continue into Smart Signals Trading.">
        <div class="database-flow" aria-hidden="true">
          <div class="provider-stack">
            <div class="provider-mini">
              <div class="provider-mini__meta"><span>Provider A</span><span>Free</span></div>
              <div class="provider-mini__signal">XAUUSD <span class="buy">BUY</span> 4541</div>
              <div class="provider-mini__levels">SL 4532 · TP1 4548 · TP2 4556</div>
              <span class="provider-mini__tag">Tracked</span>
            </div>
            <div class="provider-mini">
              <div class="provider-mini__meta"><span>Provider B</span><span>Paid</span></div>
              <div class="provider-mini__signal">XAUUSD <span class="sell">SELL</span> 4552</div>
              <div class="provider-mini__levels">SL 4570 · TP1 4548 · TP2 4547</div>
              <span class="provider-mini__tag">Tracked</span>
            </div>
            <div class="provider-mini">
              <div class="provider-mini__meta"><span>Provider C</span><span>Free</span></div>
              <div class="provider-mini__signal">XAUUSD <span class="buy">BUY</span> 4538</div>
              <div class="provider-mini__levels">SL 4529 · TP1 4545 · TP2 4552</div>
              <span class="provider-mini__tag">Tracked</span>
            </div>
            <div class="provider-mini">
              <div class="provider-mini__meta"><span>Provider D</span><span>Paid</span></div>
              <div class="provider-mini__signal">XAUUSD <span class="sell">SELL</span> 4564</div>
              <div class="provider-mini__levels">SL 4576 · TP1 4556 · TP2 4548</div>
              <span class="provider-mini__tag">Tracked</span>
            </div>
          </div>

          <div class="database-core">
            <div class="database-core__label">Super Signals Database</div>
            <h3>Every signal lives here.</h3>
            <div class="database-panels">
              <div class="database-panel">
                <strong>Signal history</strong>
                <p>Original call, entry, SL, targets and every later provider update.</p>
              </div>
              <div class="database-panel">
                <strong>Trade log</strong>
                <p>What actually happened after entry, including partial closes and cancellations.</p>
              </div>
              <div class="database-panel">
                <strong>Profit & loss</strong>
                <p>Wins and losses are kept together so the provider is judged on the complete record.</p>
              </div>
            </div>
            <div class="pnl-strip">
              <div><span>Signals</span><strong>Stored</strong></div>
              <div><span>P&L</span><strong>Tracked</strong></div>
              <div><span>Audit</span><strong>Monthly</strong></div>
            </div>
          </div>

          <div class="audit-gate">
            <span class="audit-gate__label">Monthly audit</span>
            <span class="audit-pass">✓</span>
            <span class="audit-fail">×</span>
          </div>

          <div class="app-result">
            <span class="app-result__eyebrow">Approved provider</span>
            <h3>Passes to the app</h3>
            <p>Only Gold providers that keep proving themselves remain available inside Smart Signals Trading.</p>
            <span class="app-result__status">✓ Approved</span>
          </div>
        </div>

        <div class="database-mobile-flow">
          <article class="database-mobile-card">
            <span class="database-mobile-num">01 · PROVIDERS</span>
            <h3>We track the Gold signal market.</h3>
            <p>Free groups and paid VIP providers are monitored side by side.</p>
            <div class="database-mobile-tags"><span>XAUUSD</span><span>Free</span><span>Paid</span></div>
          </article>

          <article class="database-mobile-card database-mobile-card--core">
            <span class="database-mobile-num">02 · DATABASE</span>
            <h3>Every signal and result is stored.</h3>
            <p>Entries, SLs, targets, edits, closes and the final profit or loss stay together in one record.</p>
            <div class="database-mobile-tags"><span>Signal history</span><span>Trade log</span><span>P&L</span></div>
          </article>

          <article class="database-mobile-card database-mobile-card--audit">
            <span class="database-mobile-num">03 · MONTHLY AUDIT</span>
            <h3>They have to keep proving it.</h3>
            <p>Every provider is reviewed again each month. A strong past does not guarantee a place next month.</p>
            <div class="database-mobile-tags"><span>Reviewed monthly</span><span>Full record</span></div>
          </article>

          <article class="database-mobile-card database-mobile-card--approved">
            <span class="database-mobile-num">04 · THE GATE</span>
            <h3>Only the strongest reach Smart Signals Trading.</h3>
            <p>Providers that remain consistently strong pass through. Weak or inconsistent providers stay out.</p>
            <div class="database-mobile-tags"><span>Approved</span><span>Gold only</span><span>To the app</span></div>
          </article>
        </div>
      </div>
    </div>
  `;
}

const resultsSection = document.querySelector('#results');

if (resultsSection) {
  resultsSection.classList.add('performance-teaser');
  resultsSection.innerHTML = `
    <div class="section-shell">
      <div class="section-head">
        <p class="section-kicker">Public Performance Ledger</p>
        <h2 id="results-title">Every day. Every pip. Open for anyone to check.</h2>
        <p class="section-lead">The public record is built around realised XAUUSD pips first, because pips can be compared regardless of account size. Each completed day locks at midnight UK time, and every published date stays available to inspect.</p>
      </div>

      <div class="performance-teaser-grid">
        <article class="performance-teaser-card performance-teaser-card--pips">
          <span class="performance-teaser-card__tag">Main record · pips</span>
          <h3>Daily and monthly Smart Signals P&amp;L.</h3>
          <p>See realised pips by day, month and across the full public history. Click any published date to open its anonymised trade breakdown.</p>
          <div class="performance-mini-metrics">
            <span>Daily pips</span><span>Monthly pips</span><span>Full history</span>
          </div>
        </article>

        <article class="performance-teaser-card performance-teaser-card--calc">
          <span class="performance-teaser-card__tag">Account calculator</span>
          <h3>Replay the record from your balance.</h3>
          <p>Choose $1k, $2k, $3k, $4k and upwards. Once the final sizing model is locked, the calculator will replay the historical trades using the policy valid at the time.</p>
          <div class="performance-balance-row"><span>$1k</span><span>$2k</span><span>$3k</span><span>$4k</span><span>Custom</span></div>
        </article>

        <article class="performance-teaser-card performance-teaser-card--challenge">
          <span class="performance-teaser-card__tag">Separate funded account</span>
          <h3>The $100 → $1,000 Challenge.</h3>
          <p>A dedicated funded sub-account starts on 10 September 2026. Its real balance, wins and losses will be recorded separately from paper testing and private trading.</p>
          <div class="performance-challenge-line"><strong>$100</strong><i></i><strong>$1,000</strong></div>
        </article>
      </div>

      <div class="performance-teaser-actions">
        <a class="performance-teaser-button" href="/performance.html">Open the full performance ledger →</a>
        <span class="performance-teaser-note">Provider names remain private. Performance does not.</span>
      </div>
      <div class="performance-teaser-strip"><strong>Publication rule:</strong> official daily figures update after the 00:00 Europe/London cut-off. Floating P&amp;L is never presented as realised profit.</div>
    </div>
  `;
}

const howItWorks = document.querySelector('#how-it-works');

if (howItWorks && !document.querySelector('#onboarding')) {
  const onboarding = document.createElement('section');
  onboarding.className = 'content-section onboarding-section';
  onboarding.id = 'onboarding';
  onboarding.setAttribute('aria-labelledby', 'onboarding-title');
  onboarding.innerHTML = `
    <div class="section-shell">
      <div class="section-head">
        <p class="section-kicker">Join Smart Signals</p>
        <h2 id="onboarding-title">Ready to trade Gold with Smart Signals?</h2>
        <p class="section-lead">Five simple steps take you from checking the evidence to connecting your trading account. Review how we perform and how we choose providers first — then decide if Smart Signals is right for you.</p>
        <div class="onboarding-price"><strong>€99</strong><span>per month</span></div>
      </div>

      <div class="onboarding-track" aria-label="Five steps to join Smart Signals">
        <article class="onboarding-step" data-step="01">
          <span class="onboarding-step__tag">Results</span>
          <h3>See our results first.</h3>
          <p>Start with the evidence. Review the public pip ledger, daily history, account replay calculator and the separate $100 → $1,000 funded challenge.</p>
          <div class="onboarding-step__action">
            <a class="onboarding-button" href="/performance.html">View the results</a>
          </div>
        </article>

        <article class="onboarding-step" data-step="02">
          <span class="onboarding-step__tag">Our process</span>
          <h3>See how we find the signals.</h3>
          <p>See how we track Gold providers, store their full trading record, re-audit them and only allow consistently strong providers into Smart Signals Trading.</p>
          <div class="onboarding-step__action">
            <a class="onboarding-button" href="#what-we-do">See how we operate</a>
          </div>
        </article>

        <article class="onboarding-step" data-step="03">
          <span class="onboarding-step__tag">Vantage</span>
          <h3>Open your Vantage account.</h3>
          <p>Create your trading account through the Smart Signals Vantage signup link. Your referral link will sit directly in this step.</p>
          <div class="onboarding-placeholder">
            <span>Vantage signup link</span>
            <strong>TO BE ADDED</strong>
          </div>
          <div class="onboarding-step__action">
            <span class="onboarding-button onboarding-button--pending">Vantage link coming</span>
          </div>
        </article>

        <article class="onboarding-step" data-step="04">
          <span class="onboarding-step__tag">Subscription</span>
          <h3>Activate Smart Signals — €99/month.</h3>
          <p>Pay the monthly Smart Signals subscription in USDC. The exact wallet address and required network will be shown here before payment.</p>
          <div class="onboarding-placeholder">
            <span>USDC payment address</span>
            <strong>TO BE ADDED</strong>
          </div>
          <div class="onboarding-placeholder">
            <span>USDC network</span>
            <strong>TO BE CONFIRMED</strong>
          </div>
        </article>

        <article class="onboarding-step" data-step="05">
          <span class="onboarding-step__tag">Connect</span>
          <h3>Connect Vantage + MT5.</h3>
          <p>Once your subscription is active, connect your trading setup to Smart Signals so approved trades can follow the settings attached to your account.</p>
          <div class="onboarding-connectors" aria-label="Connections required">
            <span>VANTAGE</span><span>MT5</span><span>SMART SIGNALS</span>
          </div>
          <div class="onboarding-step__action">
            <span class="onboarding-button onboarding-button--pending">Connection guide coming</span>
          </div>
        </article>
      </div>

      <p class="onboarding-footnote">Gold trading carries risk. Smart Signals does not guarantee profits. Users remain responsible for their trading account, risk settings and funds. Never send USDC until the wallet address and network shown on this page have been verified.</p>
    </div>
  `;
  howItWorks.insertAdjacentElement('afterend', onboarding);
}

document.querySelectorAll('a[href="#results"]').forEach((link) => {
  link.setAttribute('href', '/performance.html');
});

document.querySelectorAll('a[href="#start"]').forEach((link) => {
  link.setAttribute('href', '#onboarding');
});
