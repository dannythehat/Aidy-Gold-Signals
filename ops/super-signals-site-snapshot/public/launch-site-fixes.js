(()=>{
  const VANTAGE_URL='https://vigco.co/la-com-inv/rVbJG9xZ';

  function patchHomepageOnboarding(){
    const onboarding=document.querySelector('#onboarding');
    if(!onboarding||onboarding.dataset.launchFixed==='true') return false;
    onboarding.dataset.launchFixed='true';
    onboarding.innerHTML=`
      <div class="section-shell">
        <div class="section-head">
          <p class="section-kicker">Join Smart Signals</p>
          <h2 id="onboarding-title">Ready to trade Gold with Smart Signals?</h2>
          <p class="section-lead">Five simple steps take you from checking the evidence to connecting your trading account. Review how we perform and how we choose providers first — then decide if Smart Signals is right for you.</p>
          <div class="onboarding-price"><strong>€99</strong><span>per month</span></div>
        </div>

        <div class="onboarding-track" aria-label="Five steps to join Smart Signals">
          <article class="onboarding-step" data-step="01">
            <span class="onboarding-step__tag">Results</span>
            <h3>See our results first.</h3>
            <p>Start with the evidence. Review the public pip ledger, daily history, account replay calculator and the separate $100 → $1,000 funded challenge.</p>
            <div class="onboarding-step__action"><a class="onboarding-button" href="/performance">View the results</a></div>
          </article>

          <article class="onboarding-step" data-step="02">
            <span class="onboarding-step__tag">Our process</span>
            <h3>See how we find the signals.</h3>
            <p>See how we track Gold providers, store their full trading record, re-audit them and only allow consistently strong providers into Smart Signals Trading.</p>
            <div class="onboarding-step__action"><a class="onboarding-button" href="/how-it-works">See how we operate</a></div>
          </article>

          <article class="onboarding-step" data-step="03">
            <span class="onboarding-step__tag">Vantage</span>
            <h3>Open your Vantage account.</h3>
            <p>Create your trading account through the Smart Signals Vantage signup link.</p>
            <div class="onboarding-step__action"><a class="onboarding-button" href="${VANTAGE_URL}" target="_blank" rel="noopener noreferrer">Sign up to Vantage →</a></div>
          </article>

          <article class="onboarding-step" data-step="04">
            <span class="onboarding-step__tag">Subscription</span>
            <h3>Activate Smart Signals — €99/month.</h3>
            <p>Continue into the secure Smart Signals setup portal to activate your membership.</p>
            <div class="onboarding-step__action"><a class="onboarding-button" href="/join#membership">Activate membership →</a></div>
          </article>

          <article class="onboarding-step" data-step="05">
            <span class="onboarding-step__tag">Connect</span>
            <h3>Choose Paper or Real and connect MT5.</h3>
            <p>Once your subscription is active, choose the Vantage account Smart Signals should use and connect that MT5 account securely.</p>
            <div class="onboarding-connectors" aria-label="Connections required"><span>VANTAGE</span><span>MT5</span><span>SMART SIGNALS</span></div>
            <div class="onboarding-step__action"><a class="onboarding-button" href="/join#mt5">Start secure setup →</a></div>
          </article>
        </div>

        <p class="onboarding-footnote">Gold trading carries risk. Smart Signals does not guarantee profits. Users remain responsible for their trading account, risk settings and funds.</p>
      </div>`;
    return true;
  }

  function installHomepageWatcher(){
    if(patchHomepageOnboarding()) return;
    const observer=new MutationObserver(()=>{
      if(patchHomepageOnboarding()) observer.disconnect();
    });
    observer.observe(document.documentElement,{childList:true,subtree:true});
    setTimeout(()=>observer.disconnect(),10000);
  }

  function installJoinAccountChoice(){
    const section=document.querySelector('#mt5[data-mt5-section]');
    if(!section||section.dataset.accountChoiceFixed==='true') return;
    section.dataset.accountChoiceFixed='true';

    const lead=section.querySelector('.lead');
    const form=section.querySelector('[data-mt5-form]');
    const connected=section.querySelector('[data-mt5-connected]');
    const notice=section.querySelector('[data-mt5-notice]');
    if(!form||!lead) return;

    const chooser=document.createElement('div');
    chooser.className='launch-account-choice';
    chooser.innerHTML=`
      <div class="launch-account-choice__head">
        <span>Choose the account Smart Signals will trade</span>
        <strong data-launch-choice-state>Choose one</strong>
      </div>
      <div class="launch-account-choice__grid" role="radiogroup" aria-label="Choose Paper or Real trading account">
        <button type="button" class="launch-account-option" data-launch-account-choice="demo" role="radio" aria-checked="false">
          <b>PAPER</b><strong>Paper account</strong><span>Practice with your Vantage demo MT5 account.</span><i>OFF</i>
        </button>
        <button type="button" class="launch-account-option launch-account-option--live" data-launch-account-choice="live" role="radio" aria-checked="false">
          <b>REAL</b><strong>Real account</strong><span>Trade through your funded Vantage MT5 account.</span><i>OFF</i>
        </button>
      </div>
      <p class="launch-account-choice__note" data-launch-choice-note>Only one trading account can be connected at a time.</p>`;
    lead.insertAdjacentElement('afterend',chooser);

    let selected=null;
    let syncing=false;
    const state=chooser.querySelector('[data-launch-choice-state]');
    const choiceNote=chooser.querySelector('[data-launch-choice-note]');
    const buttons=[...chooser.querySelectorAll('[data-launch-account-choice]')];
    const serverInput=form.querySelector('input[name="server"]');

    function setNotice(message,error=false){
      if(!notice) return;
      notice.textContent=message||'';
      notice.classList.toggle('error',!!error);
    }

    function inferExisting(){
      if(selected||!connected||connected.hidden) return;
      const text=(connected.textContent||'').trim().toLowerCase();
      if(text.includes('paper')) choose('demo',false);
      else if(text.includes('real')) choose('live',false);
    }

    function isUnlocked(){
      return section.classList.contains('unlocked')&&!section.classList.contains('locked');
    }

    function syncForm(){
      if(syncing) return;
      syncing=true;
      inferExisting();
      const isConnected=connected&&!connected.hidden;
      if(!isConnected){
        if(!selected) form.hidden=true;
        else if(isUnlocked()) form.hidden=false;
      }
      syncing=false;
    }

    function choose(mode,scroll=true){
      selected=mode==='live'?'live':'demo';
      buttons.forEach(btn=>{
        const active=btn.dataset.launchAccountChoice===selected;
        btn.classList.toggle('active',active);
        btn.setAttribute('aria-checked',active?'true':'false');
        const flag=btn.querySelector('i');
        if(flag) flag.textContent=active?'ON':'OFF';
      });
      if(state) state.textContent=selected==='demo'?'Paper selected':'Real selected';
      if(choiceNote) choiceNote.textContent=selected==='demo'
        ?'Use the exact Vantage demo server shown for your Paper MT5 account.'
        :'Use the exact Vantage live server shown for your funded MT5 account.';
      if(serverInput){
        serverInput.placeholder=selected==='demo'?'e.g. VantageMarkets-Demo':'Exact Vantage live MT5 server';
      }
      setNotice('');
      syncForm();
      if(scroll&&isUnlocked()) form.scrollIntoView({behavior:'smooth',block:'nearest'});
    }

    buttons.forEach(btn=>btn.addEventListener('click',()=>choose(btn.dataset.launchAccountChoice)));

    form.addEventListener('submit',event=>{
      const server=(serverInput?.value||'').trim().toLowerCase();
      if(!selected){
        event.preventDefault();
        event.stopImmediatePropagation();
        setNotice('Choose Paper or Real before connecting MT5.',true);
        chooser.scrollIntoView({behavior:'smooth',block:'center'});
        return;
      }
      if(selected==='demo'&&!server.includes('demo')){
        event.preventDefault();
        event.stopImmediatePropagation();
        setNotice('Paper was selected, so use the exact Vantage demo MT5 server.',true);
        serverInput?.focus();
        return;
      }
      if(selected==='live'&&server.includes('demo')){
        event.preventDefault();
        event.stopImmediatePropagation();
        setNotice('Real was selected, so use the exact Vantage live MT5 server, not a demo server.',true);
        serverInput?.focus();
      }
    },true);

    const observer=new MutationObserver(syncForm);
    observer.observe(section,{attributes:true,attributeFilter:['class'],subtree:false});
    if(connected) observer.observe(connected,{attributes:true,attributeFilter:['hidden']});
    observer.observe(form,{attributes:true,attributeFilter:['hidden']});
    syncForm();
  }

  function run(){
    installHomepageWatcher();
    installJoinAccountChoice();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',run,{once:true});
  else run();
})();
