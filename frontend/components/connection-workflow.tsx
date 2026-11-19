'use client';

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { canAccessAccount, testCredentials } from '@/lib/api';
import type { Channel } from '@/lib/api';
import { useApp } from '@/lib/context';
import { destinationLabel } from '@/lib/destination';
import KarixAuthSync from '@/components/KarixAuthSync';

type Connection = {
  connected: boolean;
  ensureConnected: () => Promise<boolean>;
  reconnect: () => void;
};
type Check = { state: 'checking' | 'connected' | 'unverified' | 'check_failed'; message: string };
const Context = createContext<Connection | null>(null);

export function useWhitelistingConnection(): Connection {
  const connection = useContext(Context);
  if (!connection) throw new Error('Whitelisting requires the scoped connection workflow.');
  return connection;
}

export default function ConnectionWorkflow({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const { account, channel, currentUser, getAccountLabel } = useApp();
  const label = destinationLabel(account, channel, getAccountLabel(account));
  const [check, setCheck] = useState<Check>({ state: 'checking', message: 'Checking the selected provider connection…' });
  const [entered, setEntered] = useState(false);
  const enteredRef = useRef(false);
  const [recovering, setRecovering] = useState(false);
  const [popupBlocked, setPopupBlocked] = useState(false);
  const active = useRef(true);
  const flight = useRef<Promise<boolean> | null>(null);
  const popup = useRef<Window | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const validDestination = Boolean(account && account !== 'all');
  const setupUrl = `/settings?${new URLSearchParams({ connect: '1', account, channel })}`;

  const verify = useCallback((): Promise<boolean> => {
    if (flight.current) return flight.current;
    if (!account || account === 'all' || !active.current) return Promise.resolve(false);
    setCheck({ state: 'checking', message: 'Verifying this account’s live template inventory…' });
    const request = (async () => {
      try {
        const result = await testCredentials(account, channel);
        if (!active.current) return false;
        if (typeof result?.ok !== 'boolean' || typeof result?.message !== 'string') throw new Error('The connection check returned an unexpected response. Retry the check.');
        if (!result.ok) {
          setCheck({ state: 'unverified', message: result.message });
          return false;
        }
        setCheck({ state: 'connected', message: result.message });
        enteredRef.current = true;
        setEntered(true);
        setRecovering(false);
        setPopupBlocked(false);
        popup.current?.close();
        popup.current = null;
        return true;
      } catch (error) {
        if (active.current) setCheck({ state: 'check_failed', message: error instanceof Error ? error.message : 'Could not check the connection. Retry without discarding your draft.' });
        return false;
      } finally {
        flight.current = null;
      }
    })();
    flight.current = request;
    return request;
  }, [account, channel]);

  const ensureConnected = useCallback(async () => {
    const ready = await verify();
    if (!ready && active.current && enteredRef.current) setRecovering(true);
    return ready;
  }, [verify]);

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      popup.current?.close();
      popup.current = null;
    };
  }, []);
  useEffect(() => { if (enabled) void verify(); }, [enabled, verify]);
  useEffect(() => {
    if (!enabled) return;
    const onFocus = () => { void ensureConnected(); };
    const onMessage = (event: MessageEvent) => {
      if (event.origin === window.location.origin && event.source === popup.current &&
          event.data?.type === 'KARIX_CONNECTION_UPDATED' && event.data.account === account && event.data.channel === channel) {
        void ensureConnected();
      }
    };
    const timer = window.setInterval(() => {
      if (popup.current?.closed) { popup.current = null; void ensureConnected(); }
    }, 1000);
    window.addEventListener('focus', onFocus);
    window.addEventListener('message', onMessage);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', onFocus);
      window.removeEventListener('message', onMessage);
    };
  }, [enabled, account, channel, ensureConnected]);
  useEffect(() => {
    if (recovering && !dialog.current?.open) dialog.current?.showModal();
    if (!recovering && dialog.current?.open) dialog.current.close();
  }, [recovering]);

  const openSetup = () => {
    popup.current = window.open(setupUrl, `karix-connect-${currentUser?.id}-${currentUser?.tenant_id}-${account}-${channel}`, 'popup,width=660,height=780');
    setPopupBlocked(!popup.current);
    popup.current?.focus();
  };
  const reconnect = useCallback(() => setRecovering(true), []);
  const actions = <div className="connection-actions">
    <button type="button" className="connection-primary" onClick={openSetup}>Connect this account</button>
    <button type="button" className="connection-retry" disabled={check.state === 'checking'} onClick={() => { void ensureConnected(); }}>{check.state === 'checking' ? 'Checking connection…' : 'Retry connection check'}</button>
    {popupBlocked && <p role="alert" className="w-full text-xs leading-relaxed text-amber-800">Allow this site’s connection window, or <a href={setupUrl} target="_blank" rel="noopener noreferrer" className="underline">open secure connection setup</a>, then return here. Your draft stays on this page.</p>}
  </div>;
  const destination = <p className="connection-destination"><span>Destination</span><strong>{label}</strong></p>;
  const status = <div role={check.state === 'check_failed' ? 'alert' : 'status'} className="connection-status" data-state={check.state}>
    <p className="connection-kicker">{check.state === 'checking' ? 'Checking connection' : check.state === 'check_failed' ? 'Connection check failed' : check.state === 'connected' ? 'Connection verified' : 'Connection required'}</p>
    <p>{check.message}</p>
  </div>;
  const initialGate = enabled && validDestination && !entered;

  return <Context.Provider value={{ connected: check.state === 'connected', ensureConnected, reconnect }}>
    {enabled && validDestination && (initialGate ? <section aria-label="Connect before whitelisting" className="connection-gate">
      <ol className="connection-steps" aria-label="Whitelisting steps">
        <li aria-current="step"><span>01</span> Connect</li>
        <li><span>02</span> Review</li>
        <li><span>03</span> Whitelist</li>
      </ol>
      <div className="connection-layout">
        <div className="connection-intro">
          <p className="connection-kicker connection-accent">Connection setup</p>
          <h1>Connect before whitelisting</h1>
          <p className="connection-description">One connection. A clear path from template to approval.</p>
          {destination}
          <p className="connection-explanation">Verify this exact account and channel first. Then upload templates or choose a Jira ticket to review.</p>
          {status}
          {actions}
          <p className="connection-footnote">Setup opens in a separate window. Nothing is submitted when you connect.</p>
        </div>
        <figure className="connection-illustration">
          <div className="connection-illustration-heading"><span>THE PATH TO WHITELISTING</span><span>01 — 03</span></div>
          <div className="connection-diagram" aria-hidden="true">
            <div className="connection-provider">
              <span className="connection-provider-mark">K</span>
              <div><strong>Provider access</strong><span>Your account + channel</span></div>
            </div>
            <div className="connection-link"><span>Connect to continue</span></div>
            <div className="connection-preview">
              <div className="connection-preview-heading"><strong>Template review</strong><span>Next step</span></div>
              <div className="connection-preview-lines"><i /><i /><i /></div>
              <div className="connection-preview-footer"><span>Review your draft</span><span>Then whitelist</span></div>
            </div>
          </div>
          <figcaption>Illustration of the workflow, not a live connection or template.</figcaption>
          <div className="connection-illustration-note"><strong>Connect first. Stay in control.</strong><p>Review every template before you choose to submit. Existing drafts stay here while you reconnect.</p></div>
        </figure>
      </div>
    </section> : <section aria-label="Provider connection" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3 text-xs">
      <p><strong>{label}</strong> · {check.state === 'connected' ? 'Connection verified' : check.state === 'checking' ? 'Checking connection…' : 'Connection needs verification'}</p>
      <button type="button" className="workspace-button" onClick={reconnect}>Manage connection</button>
    </section>)}
    <div hidden={initialGate}>{children}</div>
    <dialog ref={dialog} onCancel={() => setRecovering(false)} onClose={() => setRecovering(false)} aria-labelledby="reconnect-title" className="connection-dialog">
      <div className="connection-dialog-header"><p className="connection-kicker connection-accent">Keep your review moving</p><h2 id="reconnect-title">Reconnect without losing your work</h2></div>
      <div className="connection-dialog-body">
        {destination}
        <p className="connection-explanation">Your uploaded file, edits and selections stay here. Connect in the secure setup window; we’ll verify the saved connection and return you to this review. Reconnecting never submits this draft.</p>
        {status}
        {actions}
      </div>
      <div className="connection-dialog-footer"><span>Your draft stays on this page.</span><button type="button" className="connection-retry" onClick={() => setRecovering(false)}>Back to draft</button></div>
    </dialog>
  </Context.Provider>;
}

/** Uses the existing extension-authorized Settings path without leaving the draft window. */
export function FocusedConnectionSetup({ account, channel }: { account: string; channel: Channel }) {
  const { currentUser, getAccountLabel } = useApp();
  const [message, setMessage] = useState('Connect this browser, sign in to the provider if needed, and reload its template inventory.');
  const active = useRef(true);
  const busy = useRef(false);
  const authorized = canAccessAccount(currentUser, account) && account !== 'all';
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const verify = useCallback(async () => {
    if (!authorized || busy.current) return;
    busy.current = true;
    try {
      const result = await testCredentials(account, channel);
      if (!active.current) return;
      setMessage(result.message);
      if (result.ok === true) {
        window.opener?.postMessage({ type: 'KARIX_CONNECTION_UPDATED', account, channel }, window.location.origin);
        if (window.opener) window.close();
      }
    } catch (error) {
      if (active.current) setMessage(error instanceof Error ? error.message : 'Connection check failed. Retry here; your original draft is unchanged.');
    } finally { busy.current = false; }
  }, [authorized, account, channel]);
  if (!authorized) return <p role="alert">This connection is outside your authorized organization.</p>;
  return <section className="space-y-4">
    <h1 className="text-xl font-semibold">Connect {destinationLabel(account, channel, getAccountLabel(account))}</h1>
    <p className="text-sm text-gray-600">Keep your template review open in the original window. This setup window only updates the selected connection.</p>
    <KarixAuthSync account={account} integration={channel} onSessionChanged={() => { void verify(); }} />
    <p role="status" className="text-sm">{message}</p>
    <button type="button" className="workspace-button-primary" onClick={() => { void verify(); }}>Verify and return to draft</button>
  </section>;
}
