(() => {
  const SUBSCRIPTION_URL = '/join.html#subscription';
  const SIGNUP_URL = '/join.html?mode=signup#account';

  function makeSubscriptionPriceActionable() {
    const price = document.querySelector('.canonical-onboarding-price');
    if (price && price.tagName !== 'A') {
      const link = document.createElement('a');
      link.className = `${price.className} canonical-onboarding-price--link`;
      link.href = SUBSCRIPTION_URL;
      link.setAttribute('aria-label', 'Activate Smart Signals for €99 per month');
      while (price.firstChild) link.appendChild(price.firstChild);
      price.replaceWith(link);
    }

    document.querySelectorAll('.setup-hero__chips span').forEach((chip) => {
      if (!/€99/i.test(chip.textContent || '')) return;
      const link = document.createElement('a');
      link.className = chip.className;
      link.href = '#subscription';
      link.textContent = chip.textContent;
      link.setAttribute('aria-label', 'Go to subscription payment');
      chip.replaceWith(link);
    });
  }

  function fixLaunchAnchors() {
    const onJoin = /^\/join(?:\.html)?$/.test(window.location.pathname);
    document.querySelectorAll('a[href="#subscription"]').forEach((link) => {
      if (!onJoin) link.href = SUBSCRIPTION_URL;
    });

    document.querySelectorAll('a[href="/#onboarding"], a[href="#start"]').forEach((link) => {
      link.href = SIGNUP_URL;
    });
  }

  function boot() {
    makeSubscriptionPriceActionable();
    fixLaunchAnchors();
  }

  boot();
  document.addEventListener('DOMContentLoaded', boot, { once: true });
  window.setTimeout(boot, 120);
  window.setTimeout(boot, 500);

  const observer = new MutationObserver(boot);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  window.setTimeout(() => observer.disconnect(), 4500);
})();
