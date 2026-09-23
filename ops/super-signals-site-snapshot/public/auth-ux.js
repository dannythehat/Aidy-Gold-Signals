(()=>{
  const COOKIE_KEY='smart-signals-essential-cookie-notice-v1';

  function enhancePasswords(root=document){
    root.querySelectorAll('input[type="password"]:not([data-ss-password-ready])').forEach(input=>{
      input.dataset.ssPasswordReady='true';
      const label=input.closest('label');
      if(!label)return;
      const wrap=document.createElement('span');
      wrap.className='ss-password-wrap';
      input.parentNode.insertBefore(wrap,input);
      wrap.appendChild(input);
      const button=document.createElement('button');
      button.type='button';
      button.className='ss-password-toggle';
      button.textContent='Show';
      button.setAttribute('aria-label','Show password');
      button.addEventListener('click',()=>{
        const showing=input.type==='text';
        input.type=showing?'password':'text';
        button.textContent=showing?'Show':'Hide';
        button.setAttribute('aria-label',showing?'Show password':'Hide password');
      });
      wrap.appendChild(button);
    });
  }

  function showCookieNotice(){
    try{if(localStorage.getItem(COOKIE_KEY)==='seen')return;}catch{}
    if(document.querySelector('.ss-cookie-notice'))return;
    const notice=document.createElement('aside');
    notice.className='ss-cookie-notice';
    notice.setAttribute('role','dialog');
    notice.setAttribute('aria-label','Cookie notice');
    notice.innerHTML='<div class="ss-cookie-notice__row"><div class="ss-cookie-notice__copy"><strong>Essential cookies only</strong><p>Smart Signals uses essential cookies to keep you signed in securely and remember your account session. We do not use advertising cookies.</p></div><button type="button">Got it</button></div>';
    notice.querySelector('button')?.addEventListener('click',()=>{
      try{localStorage.setItem(COOKIE_KEY,'seen');}catch{}
      notice.remove();
    });
    document.body.appendChild(notice);
  }

  function boot(){
    enhancePasswords();
    showCookieNotice();
    new MutationObserver(mutations=>{
      for(const mutation of mutations){
        for(const node of mutation.addedNodes){
          if(node instanceof Element){
            if(node.matches('input[type="password"]'))enhancePasswords(node.parentElement||document);
            else enhancePasswords(node);
          }
        }
      }
    }).observe(document.body,{childList:true,subtree:true});
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();
