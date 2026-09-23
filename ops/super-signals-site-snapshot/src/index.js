const ACCOUNT_API_PREFIX = '/account-api';
const ACCOUNT_API_ORIGIN = 'https://super-signals-day-8.onrender.com';
const GOLD_PRICE_PATH = '/api/gold-price';
const GOLD_PRIMARY_URL = 'https://biquote.io/api/XAUUSD?allowStale=false';
const GOLD_FALLBACK_URL = 'https://api.gold-api.com/price/XAU';
const ALLOWED_METHODS = new Set(['GET', 'POST', 'PATCH', 'HEAD', 'OPTIONS']);
const APPROVED_LOGO = '/assets/logo/smart-signals-approved.webp';

let goldCache = { expiresAt: 0, payload: null };

const CLEAN_ROUTES = new Map([
  ['/performance', '/performance.html'],
  ['/how-it-works', '/how-smart-signals-works.html'],
  ['/join', '/join-launch.html'],
  ['/account', '/account.html'],
  ['/complimentary', '/complimentary.html'],
]);

const LEGACY_ROUTES = new Map([
  ['/index.html', '/'],
  ['/performance.html', '/performance'],
  ['/how-smart-signals-works.html', '/how-it-works'],
  ['/how-smart-signals-works', '/how-it-works'],
  ['/join.html', '/join'],
  ['/join-launch.html', '/join'],
  ['/account.html', '/account'],
  ['/complimentary.html', '/complimentary'],
]);

function premiumPage(pathname) {
  if (pathname === '/') return 'home';
  if (pathname === '/performance') return 'performance';
  if (pathname === '/how-it-works') return 'guide';
  if (pathname === '/join') return 'join';
  if (pathname === '/account') return 'account';
  return 'other';
}

function proxyPath(pathname) {
  const stripped = pathname.slice(ACCOUNT_API_PREFIX.length);
  return stripped || '/';
}

async function proxyAccountApi(request) {
  if (!ALLOWED_METHODS.has(request.method)) return new Response('Method not allowed', { status: 405 });

  const incoming = new URL(request.url);
  const upstream = new URL(ACCOUNT_API_ORIGIN);
  upstream.pathname = proxyPath(incoming.pathname);
  upstream.search = incoming.search;

  const headers = new Headers(request.headers);
  headers.delete('host');
  headers.delete('origin');
  headers.set('x-forwarded-host', incoming.host);
  headers.set('x-forwarded-proto', 'https');

  const init = { method: request.method, headers, redirect: 'manual' };
  if (request.method !== 'GET' && request.method !== 'HEAD') init.body = request.body;

  const upstreamResponse = await fetch(upstream.toString(), init);
  const responseHeaders = new Headers(upstreamResponse.headers);
  responseHeaders.set('cache-control', 'no-store');
  responseHeaders.set('pragma', 'no-cache');

  return new Response(upstreamResponse.body, {
    status: upstreamResponse.status,
    statusText: upstreamResponse.statusText,
    headers: responseHeaders,
  });
}

function positiveNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

async function fetchJsonWithTimeout(url, timeoutMs = 2800) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      headers: {
        Accept: 'application/json',
        'Cache-Control': 'no-cache',
        'User-Agent': 'SmartSignalsWebsite/1.0',
      },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`upstream_${response.status}`);
    const payload = await response.json();
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('invalid_gold_payload');
    return payload;
  } finally {
    clearTimeout(timeout);
  }
}

function goldResponse(payload, status = 200, method = 'GET') {
  const body = method === 'HEAD' ? null : JSON.stringify(payload);
  return new Response(body, {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store, max-age=0',
      pragma: 'no-cache',
      'x-content-type-options': 'nosniff',
    },
  });
}

async function publicGoldPrice(request) {
  if (request.method !== 'GET' && request.method !== 'HEAD') return goldResponse({ available: false, error: 'method_not_allowed' }, 405, request.method);

  const now = Date.now();
  if (goldCache.payload && now < goldCache.expiresAt) return goldResponse(goldCache.payload, 200, request.method);

  let quote = null;
  try {
    const payload = await fetchJsonWithTimeout(GOLD_PRIMARY_URL);
    const bid = positiveNumber(payload.bid);
    const ask = positiveNumber(payload.ask);
    let price = positiveNumber(payload.mid);
    if (price === null && bid !== null && ask !== null) price = (bid + ask) / 2;
    if (price !== null) {
      const marketState = String(payload.marketState || '').trim().toLowerCase();
      const age = positiveNumber(payload.quoteAgeSeconds);
      const stale = Boolean(payload.stale) || marketState === 'closed' || (age !== null && age > 5);
      quote = {
        symbol: 'XAUUSD',
        price,
        bid,
        ask,
        available: true,
        stale,
        market_state: marketState || (stale ? 'stale' : 'open'),
        quote_time: payload.timestamp || payload.lastQuoteAt || null,
        source: 'biquote live MT5',
        read_at: new Date().toISOString(),
      };
    }
  } catch {
    quote = null;
  }

  if (!quote) {
    try {
      const payload = await fetchJsonWithTimeout(GOLD_FALLBACK_URL);
      const price = positiveNumber(payload.price);
      if (price !== null) {
        quote = {
          symbol: 'XAUUSD',
          price,
          bid: positiveNumber(payload.bid),
          ask: positiveNumber(payload.ask),
          available: true,
          stale: true,
          market_state: 'stale',
          quote_time: payload.updatedAt || payload.updated_at || null,
          source: 'Gold API fallback',
          read_at: new Date().toISOString(),
        };
      }
    } catch {
      quote = null;
    }
  }

  if (!quote && goldCache.payload && goldCache.payload.available) {
    quote = { ...goldCache.payload, stale: true, market_state: 'stale', read_at: new Date().toISOString() };
  }
  if (!quote) {
    quote = {
      symbol: 'XAUUSD', price: null, bid: null, ask: null, available: false, stale: true,
      market_state: 'unavailable', quote_time: null, source: 'free gold feeds', read_at: new Date().toISOString(),
    };
  }

  goldCache = {
    payload: quote,
    expiresAt: now + (quote.available && !quote.stale ? 1200 : 4500),
  };
  return goldResponse(quote, 200, request.method);
}

class PortalScriptInjector {
  constructor(pathname) { this.pathname = pathname; }
  element(element) {
    const existingClass = (element.getAttribute('class') || '').trim();
    const pageClass = `premium-v3 page-${premiumPage(this.pathname)}`;
    element.setAttribute('class', `${existingClass} ${pageClass}`.trim());
    element.append('<script src="/portal-links.js" defer></script>', { html: true });
    element.append('<script src="/launch-site-fixes.js?v=20260830-2" defer></script>', { html: true });
    element.append('<script src="/mt5-account-sync.js?v=20260830-3" defer></script>', { html: true });
    element.append('<script src="/site-premium-v3.js?v=20260830-premium3" defer></script>', { html: true });
    element.append(`<script>(function(){const m={'/index.html':'/','/performance.html':'/performance','/how-smart-signals-works.html':'/how-it-works','/how-smart-signals-works':'/how-it-works','/join.html':'/join','/join-launch.html':'/join','/account.html':'/account','/complimentary.html':'/complimentary'};function clean(){document.querySelectorAll('a[href]').forEach(a=>{const raw=a.getAttribute('href');if(!raw)return;for(const [oldPath,newPath] of Object.entries(m)){if(raw===oldPath||raw.startsWith(oldPath+'?')||raw.startsWith(oldPath+'#')){a.setAttribute('href',newPath+raw.slice(oldPath.length));break;}}});}clean();new MutationObserver(clean).observe(document.body,{childList:true,subtree:true});})();</script>`, { html: true });
  }
}

class CleanLinkRewriter {
  element(element) {
    const href = element.getAttribute('href');
    if (!href) return;
    for (const [legacy, clean] of LEGACY_ROUTES.entries()) {
      if (href === legacy || href.startsWith(`${legacy}?`) || href.startsWith(`${legacy}#`)) {
        element.setAttribute('href', `${clean}${href.slice(legacy.length)}`);
        return;
      }
    }
  }
}

class ApprovedLogoRewriter {
  element(element) {
    const alt = (element.getAttribute('alt') || '').trim().toLowerCase();
    const src = element.getAttribute('src') || '';
    const isSmartSignalsLogo = alt === 'smart signals' || src.includes('/assets/logo/smart-signals-logo') || src.includes('/assets/logo/smart-signals-approved');
    if (!isSmartSignalsLogo) return;
    element.setAttribute('src', APPROVED_LOGO);
    element.removeAttribute('srcset');
    element.setAttribute('data-approved-brand-logo', 'true');
  }
}

class ApprovedLogoSourceRewriter {
  element(element) {
    const srcset = element.getAttribute('srcset') || '';
    if (srcset.includes('/assets/logo/smart-signals-')) element.setAttribute('srcset', APPROVED_LOGO);
  }
}

class CanonicalInjector {
  constructor(pathname) { this.pathname = pathname; }
  element(element) {
    const canonicalPath = this.pathname === '/' ? '/' : this.pathname.replace(/\/$/, '');
    element.append(`<link rel="canonical" href="https://smartsignals.site${canonicalPath}" />`, { html: true });
    element.append('<link rel="stylesheet" href="/launch-site-fixes.css?v=20260830-1" />', { html: true });
    element.append('<link rel="stylesheet" href="/site-premium-v3.css?v=20260830-premium3" />', { html: true });
    element.append('<link rel="stylesheet" href="/site-scale-fix.css?v=20260830-scale1" />', { html: true });
    element.append('<style>img[data-approved-brand-logo="true"]{object-fit:contain!important;object-position:left center!important;height:auto!important;max-width:100%!important}.page-home .live-gold-wrap{position:absolute;top:150px;left:50%;transform:translateX(-50%);margin:0;z-index:40}.page-home .hero-inner{padding-top:250px!important}@media(min-width:981px){.page-home .onboarding-track{grid-template-columns:repeat(4,minmax(0,1fr))!important}}@media(min-width:761px) and (max-width:980px){.page-home .onboarding-track{grid-template-columns:repeat(2,minmax(0,1fr))!important}}@media(max-width:900px){.page-home .live-gold-wrap{top:88px}.page-home .hero-inner{padding-top:154px!important}}@media(max-width:420px){.page-home .live-gold-wrap{top:80px}.page-home .hero-inner{padding-top:142px!important}}</style>', { html: true });
  }
}

class HomeStyleInjector {
  element(element) { element.append('<link rel="stylesheet" href="/homepage-auth.css?v=20260830-fast2" />', { html: true }); }
}
class AccountPremiumStyleInjector {
  element(element) { element.append('<link rel="stylesheet" href="/account-premium.css" />', { html: true }); }
}
class ExplainerPremiumStyleInjector {
  element(element) {
    element.append('<link rel="stylesheet" href="/explainer-premium.css" />', { html: true });
    element.append('<link rel="stylesheet" href="/explainer-contrast.css" />', { html: true });
  }
}

async function serveAsset(request, env) {
  const publicUrl = new URL(request.url);
  const assetUrl = new URL(request.url);
  assetUrl.pathname = CLEAN_ROUTES.get(publicUrl.pathname) || publicUrl.pathname;
  const assetRequest = new Request(assetUrl.toString(), request);
  const response = await env.ASSETS.fetch(assetRequest);
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('text/html')) return response;

  const path = publicUrl.pathname;
  const rewriter = new HTMLRewriter()
    .on('head', new CanonicalInjector(path))
    .on('a[href]', new CleanLinkRewriter())
    .on('img', new ApprovedLogoRewriter())
    .on('source', new ApprovedLogoSourceRewriter())
    .on('body', new PortalScriptInjector(path));

  if (path === '/') rewriter.on('head', new HomeStyleInjector());
  if (path === '/account') rewriter.on('head', new AccountPremiumStyleInjector());
  if (path === '/how-it-works') rewriter.on('head', new ExplainerPremiumStyleInjector());
  return rewriter.transform(response);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === GOLD_PRICE_PATH) {
      return publicGoldPrice(request);
    }

    if (url.pathname === ACCOUNT_API_PREFIX || url.pathname.startsWith(`${ACCOUNT_API_PREFIX}/`)) {
      return proxyAccountApi(request);
    }

    const canonical = LEGACY_ROUTES.get(url.pathname);
    if (canonical) {
      url.pathname = canonical;
      return Response.redirect(url.toString(), 301);
    }

    return serveAsset(request, env);
  },
};
