(()=>{
  const API='/account-api';
  const $=(s,r=document)=>r.querySelector(s);
  const $$=(s,r=document)=>Array.from(r.querySelectorAll(s));
  let me=null;
  let selectedPlan='monthly';
  let entitlement=null;
  let mt5=null;
  let pollTimer=null;

  const detailMessage=(body,fallback='Something went wrong.')=>{
    const d=body&&body.detail;
    if(typeof d==='string') return d;
    if(d&&typeof d.message==='string') return d.message;
    return fallback;
  };

  async function api(path,options={}){
    const response=await fetch(API+path,{
      credentials:'include',
      cache:'no-store',
      headers:{'Content-Type':'application/json',...(options.headers||{})},
      ...options,
    });
    let body={};
    try{body=await response.json();}catch{}
    if(!response.ok){
      const error=new Error(detailMessage(body,`Request failed (${response.status}).`));
      error.status=response.status;
      error.body=body;
      throw error;
    }
    return body;
  }

  function setNotice(selector,message,error=false){
    const el=$(selector);
    if(!el) return;
    el.textContent=message||'';
    el.classList.toggle('error',!!error);
  }

  function setAuthUI(){
    const signed=$('[data-signed]');
    const signup=$('[data-signup]');
    const login=$('[data-login]');
    const tabs=$('.tabs');
    if(me){
      if(signed) signed.hidden=false;
      if(signup) signup.hidden=true;
      if(login) login.hidden=true;
      if(tabs) tabs.hidden=true;
      $('[data-user-name]').textContent=me.display_name||'Smart Signals account ready';
      $('[data-user-email]').textContent=me.email||'';
      setNotice('[data-auth-notice]','Account ready ✓');
    }else{
      if(signed) signed.hidden=true;
      if(tabs) tabs.hidden=false;
      const active=$('.tabs button.active')?.dataset.tab||'signup';
      if(signup) signup.hidden=active!=='signup';
      if(login) login.hidden=active!=='login';
    }
  }

  function setPlan(plan){
    selectedPlan=plan==='annual'?'annual':'monthly';
    $$('[data-plan]').forEach(btn=>{
      const active=btn.dataset.plan===selectedPlan;
      btn.classList.toggle('active',active);
      btn.setAttribute('aria-checked',active?'true':'false');
    });
    const submit=$('[data-claim-button]');
    if(submit) submit.textContent=selectedPlan==='annual'?'Submit €999 annual payment':'Submit €99 monthly payment';
  }

  function renderEntitlement(){
    const state=$('[data-subscription-state]');
    const approval=$('[data-approval]');
    const title=$('[data-approval-title]');
    const copy=$('[data-approval-copy]');
    const pill=$('[data-approval-pill]');
    const mt5Section=$('[data-mt5-section]');
    const mt5Form=$('[data-mt5-form]');
    const mt5Lock=$('[data-mt5-lock]');
    const paymentBlocks=[$('.plans'),$('.paybox'),$('[data-claim]')].filter(Boolean);

    if(!me){
      if(state){$('strong',state).textContent='Sign in above to continue';$('small',state).textContent='';}
      approval?.classList.add('locked');
      mt5Section?.classList.add('locked');
      if(mt5Form) mt5Form.hidden=true;
      return;
    }

    if(!entitlement){
      if(state){$('strong',state).textContent='Checking membership…';$('small',state).textContent='';}
      return;
    }

    const active=!!entitlement.active;
    const complimentary=active&&entitlement.plan_code==='complimentary';
    paymentBlocks.forEach(el=>el.hidden=active);

    if(state){
      const strong=$('strong',state); const small=$('small',state);
      if(active){
        strong.textContent=complimentary?'Complimentary access · Active':`${entitlement.plan_code==='annual'?'Annual':'Monthly'} membership · Active`;
        small.textContent=complimentary?'No payment or renewal is required while complimentary access remains active.':(entitlement.active_until?`Active until ${new Date(entitlement.active_until).toLocaleDateString()}`:'Membership active');
      }else if(entitlement.status==='pending'){
        strong.textContent='Payment submitted · Awaiting approval';
        small.textContent=entitlement.pending_amount_eur?`€${entitlement.pending_amount_eur} ${entitlement.pending_plan_code||''} claim is waiting for review.`:'Payment claim waiting for review.';
      }else if(entitlement.status==='rejected'){
        strong.textContent='Payment needs attention';
        small.textContent='The last payment claim was not approved. Check the transaction and submit again.';
      }else{
        strong.textContent='Payment required';
        small.textContent='Choose monthly or annual, pay USDC on Solana, then submit the transaction ID.';
      }
    }

    if(active){
      approval?.classList.remove('locked');
      approval?.classList.add('unlocked');
      if(title) title.textContent=complimentary?'Complimentary access approved.':'Membership approved.';
      if(copy) copy.textContent=complimentary?'Your Smart Signals access is active. You can continue directly to MT5.':'Your membership is active. You can now connect your Vantage MT5 account.';
      if(pill) pill.textContent='ACCESS ACTIVE ✓';
      mt5Section?.classList.remove('locked');
      mt5Section?.classList.add('unlocked');
      if(mt5Lock) mt5Lock.hidden=true;
      if(mt5Form && !(mt5&&mt5.configured)) mt5Form.hidden=false;
    }else{
      approval?.classList.add('locked');
      approval?.classList.remove('unlocked');
      if(title) title.textContent=entitlement.status==='pending'?'Approval pending.':'Payment approval.';
      if(copy) copy.textContent=entitlement.status==='pending'?'Your transaction has been submitted. Smart Signals will unlock MT5 as soon as the payment is approved.':'After you submit your payment transaction, Smart Signals checks the claim and activates your membership after approval.';
      if(pill) pill.textContent=entitlement.status==='pending'?'AWAITING APPROVAL':'WAITING FOR PAYMENT';
      mt5Section?.classList.add('locked');
      mt5Section?.classList.remove('unlocked');
      if(mt5Lock) mt5Lock.hidden=false;
      if(mt5Form) mt5Form.hidden=true;
    }
  }

  function renderMt5(){
    const connected=$('[data-mt5-connected]');
    const form=$('[data-mt5-form]');
    const ready=$('[data-ready]');
    if(mt5&&mt5.configured){
      if(connected){
        connected.hidden=false;
        const details=$('[data-mt5-details]');
        if(details) details.textContent=[mt5.account_environment==='demo'?'Paper':'Real',mt5.login_masked,mt5.server].filter(Boolean).join(' · ');
      }
      if(form) form.hidden=true;
      if(entitlement&&entitlement.active){ready?.classList.remove('locked');}
    }else{
      if(connected) connected.hidden=true;
      if(form) form.hidden=!(entitlement&&entitlement.active);
      ready?.classList.add('locked');
    }
  }

  async function loadMe(){
    try{me=await api('/auth/me');}
    catch(error){if(error.status===401) me=null; else throw error;}
    setAuthUI();
    return me;
  }

  async function loadEntitlement(){
    if(!me||me.role!=='user'){entitlement=null;renderEntitlement();return;}
    try{entitlement=await api('/account/mt5/subscription');}
    catch(error){
      if(error.status===404){entitlement={active:false,status:'unpaid'};}
      else throw error;
    }
    renderEntitlement();
  }

  async function loadMt5(){
    if(!me||me.role!=='user'||!(entitlement&&entitlement.active)){mt5=null;renderMt5();return;}
    try{mt5=await api('/account/mt5/status');}
    catch(error){
      if(error.status===404||error.status===503){mt5=null;}
      else throw error;
    }
    renderMt5();
  }

  async function refreshAll(){
    try{
      await loadMe();
      await loadEntitlement();
      await loadMt5();
    }catch(error){setNotice('[data-auth-notice]',error.message,true);}
  }

  function startPolling(){
    clearInterval(pollTimer);
    pollTimer=setInterval(async()=>{
      if(!me||me.role!=='user') return;
      try{
        const wasActive=!!(entitlement&&entitlement.active);
        await loadEntitlement();
        if(!wasActive&&entitlement&&entitlement.active){
          setNotice('[data-payment-notice]','Access approved ✓ MT5 is now unlocked.');
          await loadMt5();
        }
      }catch{}
    },12000);
  }

  $$('.tabs button').forEach(btn=>btn.addEventListener('click',()=>{
    $$('.tabs button').forEach(x=>x.classList.toggle('active',x===btn));
    $$('[data-panel]').forEach(panel=>panel.hidden=panel.dataset.panel!==btn.dataset.tab);
    setNotice('[data-auth-notice]','');
  }));

  $$('[data-plan]').forEach(btn=>btn.addEventListener('click',()=>setPlan(btn.dataset.plan)));

  $('[data-signup]')?.addEventListener('submit',async event=>{
    event.preventDefault();
    const form=event.currentTarget;
    const data=Object.fromEntries(new FormData(form));
    if(data.password!==data.confirm_password){setNotice('[data-auth-notice]','Passwords do not match.',true);return;}
    const button=$('button[type="submit"]',form);button.disabled=true;
    try{
      await api('/auth/signup',{method:'POST',body:JSON.stringify({display_name:data.display_name,email:data.email,password:data.password})});
      me=await api('/auth/login',{method:'POST',body:JSON.stringify({email:data.email,password:data.password})});
      setAuthUI();
      await loadEntitlement();
      await loadMt5();
      setNotice('[data-auth-notice]','Account created and signed in ✓');
      document.getElementById('vantage')?.scrollIntoView({behavior:'smooth',block:'start'});
    }catch(error){setNotice('[data-auth-notice]',error.message,true);}
    finally{button.disabled=false;}
  });

  $('[data-login]')?.addEventListener('submit',async event=>{
    event.preventDefault();
    const form=event.currentTarget;
    const data=Object.fromEntries(new FormData(form));
    const button=$('button[type="submit"]',form);button.disabled=true;
    try{
      me=await api('/auth/login',{method:'POST',body:JSON.stringify(data)});
      setAuthUI();
      await loadEntitlement();
      await loadMt5();
      setNotice('[data-auth-notice]','Signed in ✓');
    }catch(error){setNotice('[data-auth-notice]',error.message,true);}
    finally{button.disabled=false;}
  });

  $('[data-signout]')?.addEventListener('click',async()=>{
    try{await api('/auth/logout',{method:'POST',body:'{}'});}catch{}
    me=null;entitlement=null;mt5=null;setAuthUI();renderEntitlement();renderMt5();
  });

  $('[data-claim]')?.addEventListener('submit',async event=>{
    event.preventDefault();
    if(!me){setNotice('[data-payment-notice]','Create or sign in to your Smart Signals account first.',true);document.getElementById('account')?.scrollIntoView({behavior:'smooth'});return;}
    const form=event.currentTarget;
    const data=Object.fromEntries(new FormData(form));
    const button=$('[data-claim-button]');button.disabled=true;
    try{
      await api('/account/mt5/subscription/claim',{method:'POST',body:JSON.stringify({plan_code:selectedPlan,transaction_signature:String(data.transaction_signature||'').trim()})});
      setNotice('[data-payment-notice]','Payment submitted ✓ Waiting for Smart Signals approval.');
      form.reset();
      await loadEntitlement();
      document.getElementById('approval')?.scrollIntoView({behavior:'smooth',block:'center'});
    }catch(error){setNotice('[data-payment-notice]',error.message,true);}
    finally{button.disabled=false;}
  });

  $('[data-mt5-form]')?.addEventListener('submit',async event=>{
    event.preventDefault();
    if(!(entitlement&&entitlement.active)){setNotice('[data-mt5-notice]','Membership approval is required first.',true);return;}
    const form=event.currentTarget;
    const data=Object.fromEntries(new FormData(form));
    const button=$('button[type="submit"]',form);button.disabled=true;
    try{
      await api('/account/mt5/profiles/connect',{method:'POST',body:JSON.stringify({login:String(data.login||'').trim(),server:String(data.server||'').trim(),password:String(data.password||''),make_active:true})});
      mt5=await api('/account/mt5/status');
      form.reset();
      renderMt5();
      setNotice('[data-mt5-notice]','MT5 connected ✓');
      document.getElementById('ready')?.scrollIntoView({behavior:'smooth',block:'center'});
    }catch(error){setNotice('[data-mt5-notice]',error.message,true);}
    finally{button.disabled=false;}
  });

  $$('[data-copy]').forEach(btn=>btn.addEventListener('click',async()=>{
    const value=btn.dataset.copy||'';
    try{await navigator.clipboard.writeText(value);}catch{
      const ta=document.createElement('textarea');ta.value=value;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();
    }
    const badge=$('b',btn);if(badge){const old=badge.textContent;badge.textContent='Copied ✓';setTimeout(()=>badge.textContent=old,1300);}
  }));

  const mode=new URLSearchParams(location.search).get('mode');
  if(mode==='login') $('.tabs button[data-tab="login"]')?.click();
  setPlan('monthly');
  refreshAll().finally(startPolling);
  window.addEventListener('focus',()=>refreshAll());
})();
