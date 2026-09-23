(()=>{
  const INTERVAL_MS=5000;
  let timer=null;

  function refresh(){
    if(document.visibilityState!=='visible')return;
    const button=document.querySelector('[data-refresh]');
    if(button instanceof HTMLButtonElement&&!button.disabled)button.click();
  }

  function start(){
    if(timer!==null)return;
    const delay=INTERVAL_MS-(Date.now()%INTERVAL_MS);
    window.setTimeout(()=>{
      refresh();
      timer=window.setInterval(refresh,INTERVAL_MS);
    },delay);
  }

  window.addEventListener('focus',refresh);
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')refresh();});
  start();
})();
