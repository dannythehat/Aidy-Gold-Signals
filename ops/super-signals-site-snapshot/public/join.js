const API_BASE = '/account-api';

const signupForm = document.querySelector('[data-signup-form]');
const loginForm = document.querySelector('[data-login-form]');
const authTabs = [...document.querySelectorAll('[data-auth-tab]')];
const authPanels = [...document.querySelectorAll('[data-auth-panel]')];
const authNotice = document.querySelector('[data-auth-notice]');
const authSuccess = document.querySelector('[data-auth-success]');
const authName = document.querySelector('[data-auth-name]');
const authEmail = document.querySelector('[data-auth-email]');
const accountState = document.querySelector('[data-account-state]');
const signoutButton = document.querySelector('[data-signout]');
const accountChoiceButtons = [...document.querySelectorAll('[data-account-choice]')];
const accountChoiceState = document.querySelector('[data-account-choice-state]');
const selectedAccountLabel = document.querySelector('[data-selected-account-label]');
const progressSteps = [...document.querySelectorAll('.progress-step')];
const readyAccount = document.querySelector('[data-ready-check="account"]');

let currentUser = null;
let selectedAccountMode = null;

function api(path, options = {}) {
  return fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    cache: 'no-store',
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
}

async function jsonOrEmpty(response) {
  return response.json().catch(() => ({}));
}

function errorMessage(body, fallback) {
  if (typeof body?.detail === 'string') return body.detail;
  if (typeof body?.detail?.message === 'string') return body.detail.message;
  if (typeof body?.message === 'string') return body.message;
  return fallback;
}

function showNotice(message, tone = 'error') {
  if (!authNotice) return;
  authNotice.textContent = message;
  authNotice.className = `form-notice is-${tone}`;
}

function clearNotice() {
  if (!authNotice) return;
  authNotice.textContent = '';
  authNotice.className = 'form-notice is-hidden';
}

function switchAuthTab(tab) {
  authTabs.forEach((button) => button.classList.toggle('is-active', button.dataset.authTab === tab));
  authPanels.forEach((panel) => panel.classList.toggle('is-hidden', panel.dataset.authPanel !== tab));
  clearNotice();
}

function stageDone(stage, done) {
  const progress = document.querySelector(`[data-progress="${stage}"]`);
  const step = progress?.closest('.progress-step');
  if (step) step.classList.toggle('is-done', done);
  if (progress) progress.textContent = done ? 'Done' : stage === 'account' ? 'Start' : 'Next';
}

function renderUser() {
  const signedIn = Boolean(currentUser);
  signupForm?.closest('[data-auth-panel]')?.classList.toggle('is-hidden', signedIn || !authTabs.find((button) => button.dataset.authTab === 'signup')?.classList.contains('is-active'));
  loginForm?.closest('[data-auth-panel]')?.classList.toggle('is-hidden', signedIn || !authTabs.find((button) => button.dataset.authTab === 'login')?.classList.contains('is-active'));
  document.querySelector('.auth-switch')?.classList.toggle('is-hidden', signedIn);
  authSuccess?.classList.toggle('is-hidden', !signedIn);

  if (signedIn) {
    if (authName) authName.textContent = currentUser.display_name ? `${currentUser.display_name}, your account is ready.` : 'Your Smart Signals account is ready.';
    if (authEmail) authEmail.textContent = currentUser.email || '';
    if (accountState) {
      accountState.textContent = 'Connected';
      accountState.classList.add('is-connected');
    }
    readyAccount?.classList.add('is-done');
    if (readyAccount) {
      const icon = readyAccount.querySelector('i');
      const status = readyAccount.querySelector('strong');
      if (icon) icon.textContent = '✓';
      if (status) status.textContent = 'Complete';
    }
    stageDone('account', true);
  } else {
    if (accountState) {
      accountState.textContent = 'Not signed in';
      accountState.classList.remove('is-connected');
    }
    readyAccount?.classList.remove('is-done');
    if (readyAccount) {
      const icon = readyAccount.querySelector('i');
      const status = readyAccount.querySelector('strong');
      if (icon) icon.textContent = '○';
      if (status) status.textContent = 'Required';
    }
    stageDone('account', false);
  }
}

async function loadCurrentUser() {
  try {
    const response = await api('/auth/me');
    if (!response.ok) throw new Error('not_signed_in');
    currentUser = await response.json();
  } catch {
    currentUser = null;
  }
  renderUser();
}

async function signIn(email, password) {
  const response = await api('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  const body = await jsonOrEmpty(response);
  if (!response.ok) throw new Error(errorMessage(body, 'Could not sign in.'));
  currentUser = body;
  renderUser();
  return body;
}

authTabs.forEach((button) => {
  button.addEventListener('click', () => switchAuthTab(button.dataset.authTab));
});

signupForm?.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearNotice();
  const formData = new FormData(signupForm);
  const email = String(formData.get('email') || '').trim();
  const password = String(formData.get('password') || '');
  const confirmPassword = String(formData.get('confirm_password') || '');
  const displayName = String(formData.get('display_name') || '').trim();
  const submit = signupForm.querySelector('button[type="submit"]');

  if (password !== confirmPassword) {
    showNotice('The two passwords do not match.');
    return;
  }

  if (submit) {
    submit.disabled = true;
    submit.textContent = 'Creating account…';
  }

  try {
    const response = await api('/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ email, password, display_name: displayName }),
    });
    const body = await jsonOrEmpty(response);
    if (!response.ok) throw new Error(errorMessage(body, 'Could not create your account.'));
    await signIn(email, password);
    signupForm.reset();
    showNotice('Account created. This same login will work in the Smart Signals app.', 'success');
    document.querySelector('#vantage')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    showNotice(error instanceof Error ? error.message : 'Could not create your account.');
  } finally {
    if (submit) {
      submit.disabled = false;
      submit.textContent = 'Create my Smart Signals account';
    }
  }
});

loginForm?.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearNotice();
  const formData = new FormData(loginForm);
  const email = String(formData.get('email') || '').trim();
  const password = String(formData.get('password') || '');
  const submit = loginForm.querySelector('button[type="submit"]');

  if (submit) {
    submit.disabled = true;
    submit.textContent = 'Signing in…';
  }

  try {
    await signIn(email, password);
    loginForm.reset();
    showNotice('Signed in. Your website setup is attached to this Smart Signals account.', 'success');
  } catch (error) {
    showNotice(error instanceof Error ? error.message : 'Could not sign in.');
  } finally {
    if (submit) {
      submit.disabled = false;
      submit.textContent = 'Sign in';
    }
  }
});

signoutButton?.addEventListener('click', async () => {
  try {
    await api('/auth/logout', { method: 'POST' });
  } catch {
    // Local state still clears; the next authenticated request will confirm session state.
  }
  currentUser = null;
  renderUser();
  switchAuthTab('login');
  showNotice('Signed out.', 'success');
});

const accountModeLabels = {
  demo: 'Paper account selected — real trading is OFF',
  live: 'Real trading account selected — paper trading is OFF',
};

accountChoiceButtons.forEach((button) => {
  button.addEventListener('click', () => {
    selectedAccountMode = button.dataset.accountChoice === 'demo' ? 'demo' : 'live';
    accountChoiceButtons.forEach((item) => item.classList.toggle('is-selected', item === button));
    if (accountChoiceState) accountChoiceState.textContent = selectedAccountMode === 'demo' ? 'Paper active' : 'Real active';
    if (selectedAccountLabel) selectedAccountLabel.textContent = accountModeLabels[selectedAccountMode];
  });
});

progressSteps.forEach((step) => {
  step.addEventListener('click', () => {
    progressSteps.forEach((item) => item.classList.remove('is-current'));
    step.classList.add('is-current');
    document.getElementById(step.dataset.jump)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
});

const stageObserver = new IntersectionObserver((entries) => {
  const visible = entries
    .filter((entry) => entry.isIntersecting)
    .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
  if (!visible) return;
  progressSteps.forEach((step) => step.classList.toggle('is-current', step.dataset.jump === visible.target.id));
}, { threshold: [0.25, 0.5, 0.75] });

document.querySelectorAll('[data-stage]').forEach((section) => stageObserver.observe(section));

loadCurrentUser();
