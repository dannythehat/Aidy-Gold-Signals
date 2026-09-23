(() => {
  function updateLinks() {
    document.querySelectorAll('a[href="/join"], a[href="/join.html"]').forEach((link) => {
      link.href = '/join?manage=1';
      if (link.textContent.trim() === 'Setup') link.textContent = 'Manage setup';
      const strong = link.querySelector('strong');
      if (strong && /Change MT5|Paper|Real/i.test(strong.textContent || '')) {
        strong.textContent = 'Manage MT5 / Paper / Real';
      }
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', updateLinks, { once: true });
  else updateLinks();
})();
