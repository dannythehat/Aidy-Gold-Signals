import baseWorker from './index.js';

class FinalHeadInjector {
  element(element) {
    element.append('<link rel="stylesheet" href="/homepage-final.css?v=20260830-final2" />', { html: true });
  }
}

class FinalBodyInjector {
  element(element) {
    element.append('<script src="/auth-state-final.js?v=20260831-session1" defer></script>', { html: true });
  }
}

export default {
  async fetch(request, env, ctx) {
    const response = await baseWorker.fetch(request, env, ctx);
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('text/html')) return response;

    return new HTMLRewriter()
      .on('head', new FinalHeadInjector())
      .on('body', new FinalBodyInjector())
      .transform(response);
  },
};
