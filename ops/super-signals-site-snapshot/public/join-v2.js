(() => {
  const modeButtons = [...document.querySelectorAll('.account-choice[data-account-choice]')];
  const modeState = document.querySelector('[data-account-choice-state]');
  const modeSummary = document.querySelector('[data-account-mode-status]');
  const selectedLabel = document.querySelector('[data-selected-account-label]');
  const readyTradeMode = document.querySelector('[data-ready-check="trade-mode"]');
  const progress = document.querySelector('[data-progress="accounts"]');

  if (!modeButtons.length) return;

  function setReadyState(mode) {
    if (!readyTradeMode) return;
    const icon = readyTradeMode.querySelector('i');
    const status = readyTradeMode.querySelector('strong');
    readyTradeMode.classList.add('is-done');
    if (icon) icon.textContent = '✓';
    if (status) status.textContent = mode === 'demo' ? 'Paper selected' : 'Real selected';
  }

  function setProgressDone() {
    const step = progress?.closest('.progress-step');
    if (step) step.classList.add('is-done');
    if (progress) progress.textContent = 'Done';
  }

  function selectMode(selected) {
    const mode = selected.dataset.accountChoice;
    const paper = mode === 'demo';

    modeButtons.forEach((button) => {
      const active = button === selected;
      button.classList.toggle('is-selected', active);
      button.setAttribute('aria-checked', String(active));
      button.setAttribute('aria-pressed', String(active));
      const switchText = button.querySelector('.account-choice__switch em');
      if (switchText) switchText.textContent = active ? 'ON' : 'OFF';
    });

    if (modeState) modeState.textContent = paper ? 'Paper active' : 'Real active';

    if (selectedLabel) {
      selectedLabel.textContent = paper
        ? 'Paper account selected — real trading is OFF'
        : 'Real trading account selected — paper trading is OFF';
    }

    if (modeSummary) {
      modeSummary.classList.remove('is-paper', 'is-live');
      modeSummary.classList.add(paper ? 'is-paper' : 'is-live');
      const label = modeSummary.querySelector('span');
      const detail = modeSummary.querySelector('strong');
      if (label) label.textContent = paper ? 'Paper trading selected' : 'Real trading selected';
      if (detail) {
        detail.textContent = paper
          ? 'Paper account ON · Real trading OFF'
          : 'Real trading ON · Paper account OFF';
      }
    }

    setReadyState(mode);
    setProgressDone();
  }

  modeButtons.forEach((button) => {
    button.addEventListener('click', () => selectMode(button));
  });
})();
