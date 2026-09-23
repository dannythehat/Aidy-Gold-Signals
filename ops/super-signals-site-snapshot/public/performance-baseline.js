(() => {
  const DATA_URL = '/data/public-performance.json';
  let data = null;

  const money = (value) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value || 0));
  const signedMoney = (value) => `${Number(value) >= 0 ? '+' : '-'}${money(Math.abs(Number(value || 0)))}`;
  const prettyDate = (value) => new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T12:00:00Z`));

  function baseline() { return data?.historical_baseline || null; }
  function baselineRecords() { return Array.isArray(data?.daily) ? data.daily.filter((row) => row.history_type === 'reconstructed') : []; }

  function updateTopCopy() {
    const base = baseline();
    if (!base) return;
    const heroTitle = document.querySelector('#ledger-title');
    const heroIntro = document.querySelector('.ledger-intro');
    const badges = document.querySelector('.hero-badges');
    if (heroTitle) heroTitle.textContent = 'Every day. Every result. One running balance.';
    if (heroIntro) heroIntro.textContent = 'The 6–28 August section is a reconstructed historical balance baseline because account resets meant the exact daily broker balances were not preserved. From the next market session onward, results are recorded from the live verified feed.';
    if (badges) badges.innerHTML = '<span>Gold / XAUUSD</span><span>Reconstructed 6–28 Aug</span><span>Verified from 31 Aug</span>';

    const summaryTitle = document.querySelector('#summary-title');
    const summaryText = summaryTitle?.closest('.section-heading')?.querySelector('p:last-child');
    if (summaryTitle) summaryTitle.textContent = 'August reconstructed account baseline';
    if (summaryText) summaryText.textContent = 'This historical bridge shows the known $1,000 starting balance reaching $1,517.23 by 28 August. It is labelled reconstructed; live verified reporting begins with the next market session.';

    const latestCard = document.querySelector('[data-latest-pips]')?.closest('.metric-card');
    const monthCard = document.querySelector('[data-month-pips]')?.closest('.metric-card');
    const totalCard = document.querySelector('[data-total-pips]')?.closest('.metric-card');
    const rateCard = document.querySelector('[data-win-rate]')?.closest('.metric-card');
    if (latestCard?.querySelector('.metric-card__label')) latestCard.querySelector('.metric-card__label').textContent = '28 Aug balance';
    if (monthCard?.querySelector('.metric-card__label')) monthCard.querySelector('.metric-card__label').textContent = '6–28 Aug P&L';
    if (totalCard?.querySelector('.metric-card__label')) totalCard.querySelector('.metric-card__label').textContent = 'Starting balance';
    if (rateCard?.querySelector('.metric-card__label')) rateCard.querySelector('.metric-card__label').textContent = 'Positive days';
    const latest = document.querySelector('[data-latest-pips]');
    const latestDate = document.querySelector('[data-latest-date]');
    const month = document.querySelector('[data-month-pips]');
    const total = document.querySelector('[data-total-pips]');
    const rate = document.querySelector('[data-win-rate]');
    const count = document.querySelector('[data-trade-count]');
    if (latest) latest.textContent = money(base.ending_balance);
    if (latestDate) latestDate.textContent = 'Reconstructed baseline close';
    if (month) month.textContent = signedMoney(base.net_pnl);
    if (monthCard?.querySelector('small')) monthCard.querySelector('small').textContent = 'Reconstructed net P&L';
    if (total) total.textContent = money(base.starting_balance);
    if (totalCard?.querySelector('small')) totalCard.querySelector('small').textContent = 'Baseline start · 6 Aug 2026';
    if (rate) rate.textContent = `${base.positive_days} / ${base.positive_days + base.loss_days}`;
    if (count) count.textContent = `${base.loss_days} loss days`;
  }

  function ensureDisclosure() {
    const base = baseline();
    const history = document.querySelector('#history');
    const layout = history?.querySelector('.history-layout');
    if (!base || !history || !layout) return;
    if (!history.querySelector('.baseline-disclosure')) {
      const box = document.createElement('div');
      box.className = 'baseline-disclosure';
      box.innerHTML = `
        <span class="baseline-disclosure__tag">Reconstructed historical baseline</span>
        <h3>6–28 August 2026</h3>
        <p>${base.note}</p>
        <div class="baseline-stats">
          <div class="baseline-stat"><span>Starting balance</span><strong>${money(base.starting_balance)}</strong></div>
          <div class="baseline-stat baseline-stat--green"><span>Net reconstructed P&L</span><strong>${signedMoney(base.net_pnl)}</strong></div>
          <div class="baseline-stat"><span>28 August balance</span><strong>${money(base.ending_balance)}</strong></div>
        </div>`;
      layout.before(box);
    }
    ensureTable(history, base);
  }

  function ensureTable(history, base) {
    let wrap = history.querySelector('.baseline-table-wrap');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.className = 'baseline-table-wrap';
      history.appendChild(wrap);
    }
    const rows = baselineRecords();
    wrap.innerHTML = `
      <div class="baseline-table-head"><div><h3>Daily balance history</h3><span>Weekends excluded · no Gold trading</span></div><span>${prettyDate(base.start_date)} → ${prettyDate(base.end_date)}</span></div>
      <div class="baseline-table-scroll"><table class="baseline-table">
        <thead><tr><th>Date</th><th>Start balance</th><th>Profit / loss</th><th>End balance</th><th>Record</th></tr></thead>
        <tbody>${rows.map((row) => `<tr><td>${prettyDate(row.date)}</td><td>${money(row.balance_start)}</td><td class="${Number(row.cash_pnl) >= 0 ? 'pnl-positive' : 'pnl-negative'}">${signedMoney(row.cash_pnl)}</td><td>${money(row.balance_end)}</td><td class="status-reconstructed">Reconstructed</td></tr>`).join('')}</tbody>
      </table></div>`;
  }

  function renderBaselineDetail(record) {
    const detail = document.querySelector('[data-day-detail]');
    if (!detail) return;
    detail.classList.add('day-detail--reconstructed');
    detail.innerHTML = `
      <span class="day-detail__eyebrow">Reconstructed historical day</span>
      <h3>${prettyDate(record.date)}</h3>
      <div class="day-stats">
        <div class="day-stat"><span>Start balance</span><strong>${money(record.balance_start)}</strong></div>
        <div class="day-stat"><span>Daily P&L</span><strong class="${Number(record.cash_pnl) >= 0 ? 'pnl-positive' : 'pnl-negative'}">${signedMoney(record.cash_pnl)}</strong></div>
        <div class="day-stat"><span>End balance</span><strong>${money(record.balance_end)}</strong></div>
      </div>
      <div class="empty-state"><strong>Historical reconstruction.</strong> The exact daily broker balance was not preserved during account resets. This day forms part of the disclosed bridge from $1,000 on 6 August to $1,517.23 on 28 August. No individual trade outcomes are being invented for this period.</div>`;
  }

  function monthFromLabel() {
    const label = document.querySelector('[data-month-label]')?.textContent?.trim();
    if (!label) return null;
    const date = new Date(`${label} 1, 12:00:00 UTC`);
    if (Number.isNaN(date.getTime())) return null;
    return { year: date.getUTCFullYear(), month: date.getUTCMonth() + 1 };
  }

  function renderAugustCalendar() {
    const calendar = document.querySelector('[data-calendar]');
    if (!calendar) return;
    const byDay = new Map(baselineRecords().map((row) => [Number(row.date.slice(-2)), row]));
    calendar.innerHTML = '';
    const year = 2026, month = 8;
    const firstDay = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
    const mondayOffset = (firstDay + 6) % 7;
    const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
    for (let i = 0; i < mondayOffset; i += 1) {
      const blank = document.createElement('div'); blank.className = 'calendar-cell calendar-cell--empty'; calendar.appendChild(blank);
    }
    for (let day = 1; day <= daysInMonth; day += 1) {
      const dow = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
      const weekend = dow === 0 || dow === 6;
      const record = byDay.get(day);
      const cell = document.createElement(record ? 'button' : 'div');
      cell.className = 'calendar-cell';
      if (weekend) cell.classList.add('calendar-cell--weekend');
      if (record) {
        cell.type = 'button';
        cell.classList.add('calendar-cell--published', 'calendar-cell--reconstructed');
        cell.classList.add(Number(record.cash_pnl) > 0 ? 'calendar-cell--profit' : Number(record.cash_pnl) < 0 ? 'calendar-cell--loss' : 'calendar-cell--flat');
        cell.setAttribute('aria-label', `${prettyDate(record.date)}, reconstructed ${signedMoney(record.cash_pnl)}`);
        cell.addEventListener('click', () => renderBaselineDetail(record));
      }
      cell.innerHTML = `<span class="calendar-cell__day">${day}</span>${record ? `<strong class="calendar-cell__pips">${signedMoney(record.cash_pnl)}</strong>` : ''}`;
      calendar.appendChild(cell);
    }
    const key = document.querySelector('.calendar-key');
    if (key) key.innerHTML = '<span><i class="key-dot key-dot--profit"></i> Profit day</span><span><i class="key-dot key-dot--loss"></i> Loss day</span><span><i class="key-dot key-dot--flat"></i> Weekend / no result</span>';
  }

  function markOtherMonthWeekends(view) {
    const calendar = document.querySelector('[data-calendar]');
    if (!calendar || !view) return;
    calendar.querySelectorAll('.calendar-cell:not(.calendar-cell--empty)').forEach((cell) => {
      const day = Number(cell.querySelector('.calendar-cell__day')?.textContent || 0);
      if (!day) return;
      const dow = new Date(Date.UTC(view.year, view.month - 1, day)).getUTCDay();
      if (dow === 0 || dow === 6) cell.classList.add('calendar-cell--weekend');
    });
  }

  function enhanceCurrentMonth() {
    const view = monthFromLabel();
    if (!view) return;
    if (view.year === 2026 && view.month === 8) renderAugustCalendar();
    else markOtherMonthWeekends(view);
  }

  async function init() {
    try {
      const response = await fetch(DATA_URL, { cache: 'no-store' });
      if (!response.ok) return;
      data = await response.json();
    } catch { return; }
    if (!baseline()) return;
    updateTopCopy();
    ensureDisclosure();
    enhanceCurrentMonth();
    [120, 450, 1000].forEach((delay) => window.setTimeout(() => { updateTopCopy(); ensureDisclosure(); enhanceCurrentMonth(); }, delay));
    document.querySelector('[data-month-prev]')?.addEventListener('click', () => window.setTimeout(enhanceCurrentMonth, 0));
    document.querySelector('[data-month-next]')?.addEventListener('click', () => window.setTimeout(enhanceCurrentMonth, 0));
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
