(() => {
  'use strict';
  const origin = globalThis.KARIX_SYNC_CONFIG.agentOrigin;
  if (window !== window.top || window.location.origin !== origin) return;
  const activeRequests = new Set();

  window.addEventListener('message', async event => {
    if (event.source !== window || event.origin !== origin ||
        window.location.origin !== origin || window.location.pathname !== '/settings') return;
    const message = event.data;
    if (!message || typeof message !== 'object' ||
        !['KARIX_EXTENSION_PING', 'KARIX_EXTENSION_PAIR'].includes(message.type) ||
        typeof message.requestId !== 'string' ||
        !/^[A-Za-z0-9_-]{1,128}$/.test(message.requestId)) return;
    if (message.type === 'KARIX_EXTENSION_PAIR' &&
        (typeof message.code !== 'string' || !message.code || message.code.length > 1024)) return;
    if (activeRequests.has(message.requestId) || activeRequests.size >= 10) return;
    activeRequests.add(message.requestId);
    let result;
    try {
      result = await chrome.runtime.sendMessage({
        type: message.type,
        ...(message.type === 'KARIX_EXTENSION_PAIR' ? {code: message.code} : {}),
      });
      if (!result || typeof result.ok !== 'boolean' || typeof result.message !== 'string') {
        throw new Error('Invalid extension response.');
      }
    } catch {
      result = {ok: false, message: 'Could not contact Karix Auth Sync. Reload the extension and this Settings page, then retry.'};
    } finally {
      activeRequests.delete(message.requestId);
    }
    if (window.location.origin === origin && window.location.pathname === '/settings') {
      window.postMessage({
        type: 'KARIX_EXTENSION_RESULT', requestId: message.requestId,
        ok: result.ok, message: result.message,
      }, origin);
    }
  });
})();
