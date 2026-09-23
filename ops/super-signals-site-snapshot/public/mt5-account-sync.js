(()=>{
  const API='/account-api';
  const path=location.pathname;
  const onJoin=path==='/join'||path==='/join-launch.html'||path==='/join.html';
  const onAccount=path==='/account'||path==='/account.html';
  if(!onJoin&&!onAccount) return;

  let lastState=null;
  let applying=false;
  let requestInFlight=false;

  async function read(endpoint){
    const response=await fetch(API+endpoint,{credentials:'include',cache:'no-store',headers:{Accept:'application/json'}});
    if(!response.ok){
      const error=new Error(`MT5 sync failed (${response.status})`);
      error.status=response.status;
      throw error;
    }
    return response.json();
  }

  function fromDashboard(body){
    const c=body&&body.connection;
    if(!c) return null;
    const hasSaved=!!(c.configured||c.login_masked||c.server);
    if(!hasSaved) return null;
    return {
      configured:!!c.configured,
      connected:c.status==='connected',
      environment:c.account_environment||null,
      login:c.login_masked||null,
      server:c.server||null,
      status:c.status||null,
      source:'dashboard',
    };
  }

  function fromOnboarding(body){
    if(!body) return null;
    const login=body.approved_login_masked||body.request_login_masked||null;
    const server=body.approved_server||body.request_server||null;
    if(!login&&!server&&!body.configured) return null;
    const serverText=String(server||'').toLowerCase();
    return {
      configured:!!body.configured,
      connected:body.connection_status==='connected',
      environment:serverText.includes('demo')?'demo':(server?'live':null),
      login,
      server,
      status:body.connection_status||body.approval_status||body.request_status||null,
      source:'onboarding',
    };
  }

  function shortLabel(state){
    if(state.environment==='demo') return 'Paper';
    if(state.environment==='live') return 'Real';
    return 'MT5';
  }

  function longLabel(state){
    if(state.environment==='demo') return 'Paper account';
    if(state.environment==='live') return 'Real account';
    return 'MT5 account';
  }

  function accountDetails(state){
    return [longLabel(state),state.login,state.server].filter(Boolean).join(' · ');
  }

  function markProgress(stage){
    const progress=document.querySelector(`[data-progress="${stage}"]`);
    const step=progress&&progress.closest('.progress-step');
    if(progress) progress.textContent='Done';
    if(step) step.classList.add('is-done');
  }

  function cleanLaunchVantage(state){
    const vantage=document.querySelector('#vantage:not([data-stage])');
    if(!vantage) return;
    vantage.dataset.accountSynced='true';
    const title=vantage.querySelector('h2');
    const lead=vantage.querySelector('.lead');
    if(title) title.textContent='Your Vantage account is already connected.';
    if(lead) lead.textContent=`Smart Signals already recognises the Vantage MT5 account saved to your login: ${accountDetails(state)}.`;
    vantage.querySelectorAll('a[href*="vigco.co"],a[href*="vantagemarkets"]').forEach(link=>{
      link.hidden=true;
      link.style.display='none';
    });
    const small=vantage.querySelector('.small');
    if(small) small.textContent='No Vantage signup is needed for this account.';
  }

  function applyLaunch(state){
    cleanLaunchVantage(state);
    const section=document.querySelector('#mt5[data-mt5-section]');
    if(!section) return;
    section.dataset.mt5Synced='true';
    const connected=section.querySelector('[data-mt5-connected]');
    const details=section.querySelector('[data-mt5-details]');
    const form=section.querySelector('[data-mt5-form]');
    const lock=section.querySelector('[data-mt5-lock]');
    const chooser=section.querySelector('.launch-account-choice');
    const title=section.querySelector('h2');
    const lead=section.querySelector('.lead');

    if(title) title.textContent=`${longLabel(state)} connected.`;
    if(lead) lead.textContent='This MT5 account is already saved to your Smart Signals login. You do not need to enter the account number, server or trading password again.';
    if(connected){
      connected.hidden=false;
      connected.style.display='flex';
      const strong=connected.querySelector('strong');
      if(strong) strong.textContent=state.connected||state.configured?'MT5 connected ✓':'MT5 details already saved ✓';
    }
    if(details) details.textContent=accountDetails(state);
    if(form){
      form.hidden=true;
      form.style.display='none';
    }
    if(chooser){
      chooser.hidden=true;
      chooser.style.display='none';
    }
    if(lock){
      lock.hidden=true;
      lock.style.display='none';
    }
  }

  function ensureLegacyVantageSummary(vantage,state){
    let summary=vantage.querySelector('[data-synced-vantage-summary]');
    if(!summary){
      summary=document.createElement('div');
      summary.className='account-mode-status is-paper';
      summary.setAttribute('data-synced-vantage-summary','true');
      const trust=vantage.querySelector('.trust-banner');
      if(trust) trust.insertAdjacentElement('afterend',summary);
      else vantage.appendChild(summary);
    }
    summary.classList.toggle('is-paper',state.environment==='demo');
    summary.classList.toggle('is-live',state.environment==='live');
    summary.innerHTML=`<span>Vantage account connected</span><strong>${accountDetails(state)}</strong>`;
  }

  function applyLegacy(state){
    const vantage=document.querySelector('#vantage[data-stage="vantage"],.setup-card--vantage');
    const accounts=document.querySelector('#accounts[data-stage="accounts"],.setup-card--accounts');
    if(!vantage&&!accounts) return;

    if(vantage){
      vantage.dataset.accountSynced='true';
      const title=vantage.querySelector('.setup-card__head h2,h2');
      const stage=vantage.querySelector('.stage-state');
      if(title) title.textContent='Your Vantage account is already connected.';
      if(stage){
        stage.textContent='CONNECTED';
        stage.classList.add('is-connected');
      }
      vantage.querySelectorAll('.vantage-action,a[href*="vigco.co"],a[href*="vantagemarkets"]').forEach(el=>{
        el.hidden=true;
        el.style.display='none';
      });
      ensureLegacyVantageSummary(vantage,state);
      markProgress('vantage');
    }

    if(accounts){
      accounts.dataset.mt5Synced='true';
      const title=accounts.querySelector('.setup-card__head h2,h2');
      const stage=accounts.querySelector('[data-account-choice-state],.stage-state');
      if(title) title.textContent=`${longLabel(state)} connected.`;
      if(stage){
        stage.textContent='CONNECTED';
        stage.classList.add('is-connected');
      }

      const choiceGrid=accounts.querySelector('.account-choice-grid');
      const exclusive=accounts.querySelector('.exclusive-note');
      if(choiceGrid){choiceGrid.hidden=true;choiceGrid.style.display='none';}
      if(exclusive){exclusive.hidden=true;exclusive.style.display='none';}

      const modeSummary=accounts.querySelector('[data-account-mode-status]');
      if(modeSummary){
        modeSummary.classList.remove('is-paper','is-live');
        modeSummary.classList.add(state.environment==='demo'?'is-paper':'is-live');
        const label=modeSummary.querySelector('span');
        const detail=modeSummary.querySelector('strong');
        if(label) label.textContent=`${longLabel(state)} connected`;
        if(detail) detail.textContent=accountDetails(state);
      }

      const preview=accounts.querySelector('.connection-preview');
      if(preview){
        preview.innerHTML=`
          <div class="connection-preview__top"><span>Connected account</span><strong>${longLabel(state)} is already linked to Smart Signals</strong></div>
          <p>${[state.login,state.server].filter(Boolean).join(' · ')}${state.login||state.server?' · ':''}No MT5 details need to be entered again.</p>`;
      }

      const selectedLabel=accounts.querySelector('[data-selected-account-label]');
      if(selectedLabel) selectedLabel.textContent=`${longLabel(state)} connected`;

      const readyTradeMode=document.querySelector('[data-ready-check="trade-mode"]');
      if(readyTradeMode){
        readyTradeMode.classList.add('is-done');
        const icon=readyTradeMode.querySelector('i');
        const status=readyTradeMode.querySelector('strong');
        if(icon) icon.textContent='✓';
        if(status) status.textContent=`${shortLabel(state)} connected`;
      }
      markProgress('accounts');
    }
  }

  function applyAccount(state){
    const connection=document.querySelector('[data-connection-status]');
    const mode=document.querySelector('[data-account-mode]');
    const accountLabel=document.querySelector('[data-account-label]');
    const login=document.querySelector('[data-login-mask]');
    const server=document.querySelector('[data-server]');
    const error=document.querySelector('[data-account-error]');

    if(connection){
      connection.innerHTML=`<i></i> ${state.connected||state.configured?'MT5 connected':'MT5 details saved'}`;
      connection.classList.toggle('is-connected',!!(state.connected||state.configured));
    }
    if(mode) mode.textContent=longLabel(state);
    if(accountLabel) accountLabel.textContent=longLabel(state);
    if(login&&state.login) login.textContent=state.login;
    if(server&&state.server) server.textContent=state.server;

    if(error&&!state.configured&&!state.connected){
      error.textContent='Your MT5 account details are already saved to your Smart Signals account. You do not need to enter them again.';
      error.classList.remove('is-hidden');
    }
  }

  function apply(state){
    if(!state) return;
    lastState=state;
    applying=true;
    try{
      if(onJoin){
        applyLaunch(state);
        applyLegacy(state);
      }
      if(onAccount) applyAccount(state);
    }finally{
      applying=false;
    }
  }

  async function sync(){
    if(requestInFlight) return;
    requestInFlight=true;
    try{
      try{
        const dashboard=await read('/account/mt5/dashboard?timezone_name=Europe%2FLondon');
        const state=fromDashboard(dashboard);
        if(state){apply(state);return;}
      }catch(error){
        if(error.status===401) return;
      }

      try{
        const onboarding=await read('/account/mt5/onboarding');
        const state=fromOnboarding(onboarding);
        if(state) apply(state);
      }catch(error){
        if(error.status===401) return;
      }
    }finally{
      requestInFlight=false;
    }
  }

  function keepSynced(){
    if(!lastState||applying) return;
    if(onJoin){
      const launch=document.querySelector('#mt5[data-mt5-section]');
      const legacy=document.querySelector('#accounts[data-stage="accounts"],.setup-card--accounts');
      if(launch){
        const connected=launch.querySelector('[data-mt5-connected]');
        const form=launch.querySelector('[data-mt5-form]');
        const chooser=launch.querySelector('.launch-account-choice');
        if((connected&&connected.hidden)||(form&&!form.hidden)||(chooser&&!chooser.hidden)) apply(lastState);
      }
      if(legacy){
        const preview=legacy.querySelector('.connection-preview');
        const choiceGrid=legacy.querySelector('.account-choice-grid');
        const legacyVantage=document.querySelector('#vantage[data-stage="vantage"],.setup-card--vantage');
        const signup=legacyVantage&&legacyVantage.querySelector('.vantage-action');
        if((preview&&!preview.textContent.includes('No MT5 details need to be entered again'))||(choiceGrid&&!choiceGrid.hidden)||(signup&&!signup.hidden)) apply(lastState);
      }
      return;
    }
    if(onAccount){
      const login=document.querySelector('[data-login-mask]');
      const server=document.querySelector('[data-server]');
      if((lastState.login&&login&&login.textContent!==lastState.login)||(lastState.server&&server&&server.textContent!==lastState.server)) apply(lastState);
    }
  }

  function scheduleAfterAuth(){
    setTimeout(sync,300);
    setTimeout(sync,1000);
    setTimeout(sync,2500);
  }

  function start(){
    sync();
    const observer=new MutationObserver(()=>{
      keepSynced();
      if(!lastState&&onJoin){
        const signed=document.querySelector('[data-signed],[data-auth-success]');
        if(signed&&!signed.hidden&&!signed.classList.contains('is-hidden')) sync();
      }
    });
    observer.observe(document.body,{subtree:true,attributes:true,attributeFilter:['hidden','class','style'],childList:true});
    document.addEventListener('submit',event=>{
      if(event.target&&event.target.matches&&event.target.matches('[data-login],[data-signup],[data-login-form],[data-signup-form]')) scheduleAfterAuth();
    },true);
    window.addEventListener('focus',sync);
    window.addEventListener('pageshow',sync);
    setInterval(sync,15000);
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start,{once:true});
  else start();
})();
