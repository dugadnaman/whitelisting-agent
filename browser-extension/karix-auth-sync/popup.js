(() => {
  'use strict';
  const state = document.getElementById('state');
  const lastSync = document.getElementById('last-sync');
  const nextStep = document.getElementById('next-step');
  const error = document.getElementById('error');
  const result = document.getElementById('result');
  const retry = document.getElementById('retry');
  const disconnect = document.getElementById('disconnect');
  document.getElementById('settings').href = `${globalThis.KARIX_SYNC_CONFIG.agentOrigin}/settings`;
  let busy = false;
  let lastStatus = null;

  function render(status) {
    lastStatus = status;
    error.textContent = status.error || '';
    error.hidden = !status.error;
    lastSync.textContent = status.last_synced_at
      ? new Date(status.last_synced_at * 1000).toLocaleString() : 'Never';
    if (!status.paired) {
      state.textContent = 'Not paired';
      nextStep.textContent = 'Open agent Settings, select Bajaj WhatsApp and connect this extension. A pairing does not validate Karix credentials.';
    } else if (status.syncing) {
      state.textContent = 'Paired — backend validation in progress';
      nextStep.textContent = 'Wait for backend validation before treating these credentials as synced.';
    } else if (status.error) {
      state.textContent = 'Paired — action required';
      nextStep.textContent = status.pending
        ? 'Retry sync below. If the backend rejects the session, log into Karix again with your mobile OTP and open the Bajaj WhatsApp template list.'
        : 'Open Karix, log in with your mobile OTP and load the Bajaj WhatsApp template list to capture a complete successful request.';
    } else if (status.pending) {
      state.textContent = 'Paired — awaiting backend validation';
      nextStep.textContent = 'A complete Bajaj request is available. Retry sync to submit it for backend validation.';
    } else if (status.last_synced_at) {
      state.textContent = 'Paired — last sync validated by backend';
      nextStep.textContent = 'New successful Bajaj template-list requests sync automatically. The last sync is historical; use Check status in agent Settings for current validity.';
    } else {
      state.textContent = 'Paired — awaiting Karix template request';
      nextStep.textContent = 'Log into Karix normally using the mobile OTP, select Bajaj WhatsApp and open its template list. Nothing is synced until the backend validates the credentials.';
    }
    retry.disabled = busy || !status.paired || !status.pending || status.syncing;
    disconnect.disabled = busy || !status.can_disconnect;
  }

  async function refresh() {
    const status = await chrome.runtime.sendMessage({type: 'KARIX_EXTENSION_STATUS'});
    if (!status || typeof status.paired !== 'boolean') {
      throw new Error('Could not load extension state. Reload the extension and retry.');
    }
    render(status);
  }

  function showError(message) {
    error.textContent = message;
    error.hidden = false;
  }

  async function action(type) {
    if (busy) return;
    busy = true;
    result.hidden = true;
    if (lastStatus) render(lastStatus);
    try {
      const response = await chrome.runtime.sendMessage({type});
      if (!response || typeof response.ok !== 'boolean' || typeof response.message !== 'string') {
        throw new Error('The extension did not return a result. Reload it and retry.');
      }
      await refresh();
      if (response.ok) {
        result.textContent = response.message;
        result.hidden = false;
      } else {
        showError(response.message);
      }
    } catch (failure) {
      showError(failure.message || 'Could not contact the extension. Reload it and retry.');
    } finally {
      busy = false;
      if (lastStatus) {
        retry.disabled = !lastStatus.paired || !lastStatus.pending || lastStatus.syncing;
        disconnect.disabled = !lastStatus.can_disconnect;
      }
    }
  }

  retry.addEventListener('click', () => { void action('KARIX_EXTENSION_RETRY'); });
  disconnect.addEventListener('click', () => { void action('KARIX_EXTENSION_DISCONNECT'); });
  chrome.storage.onChanged.addListener((changes, area) => {
    if ((area === 'local' && changes.karixAuthSync) ||
        (area === 'session' && changes.karixAuthSyncSession)) {
      void refresh().catch(failure => showError(failure.message));
    }
  });
  void refresh().catch(failure => showError(failure.message));
})();
