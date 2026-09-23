const proofCounters = [...document.querySelectorAll('[data-count-to]')];

if (proofCounters.length) {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let hasRun = false;

  function setFinalValues() {
    proofCounters.forEach((counter) => {
      counter.textContent = counter.dataset.countTo || counter.textContent;
    });
    hasRun = true;
  }

  function runCounters() {
    if (hasRun) return;
    if (reducedMotion.matches) {
      setFinalValues();
      return;
    }

    hasRun = true;
    const duration = 920;
    const start = performance.now();

    function frame(now) {
      const progress = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);

      proofCounters.forEach((counter) => {
        const target = Number(counter.dataset.countTo || 0);
        counter.textContent = String(Math.round(target * eased));
      });

      if (progress < 1) requestAnimationFrame(frame);
      else setFinalValues();
    }

    requestAnimationFrame(frame);
  }

  if (reducedMotion.matches || !('IntersectionObserver' in window)) {
    setFinalValues();
  } else {
    const proofSection = document.querySelector('[data-proof-section]');
    if (proofSection) {
      const observer = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          runCounters();
          observer.disconnect();
        }
      }, { threshold: 0.22 });
      observer.observe(proofSection);
    } else {
      setFinalValues();
    }
  }

  reducedMotion.addEventListener('change', (event) => {
    if (event.matches) setFinalValues();
  });
}
