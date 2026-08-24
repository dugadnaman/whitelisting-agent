'use client';

import { useState, useEffect } from 'react';
import { updateCredentials, testCredentials, createAccount, deleteAccount, fetchCredentials, refreshSession } from '@/lib/api';
import type { Account, Channel, AccountItem } from '@/lib/api';
import { useApp } from '@/lib/context';

type Banner = { type: 'success' | 'error'; message: string } | null;

export default function SettingsPage() {
  const {
    account: activeAccount,
    channel: activeChannel,
    setAccount: setActiveAccount,
    setChannel: setActiveChannel,
    user: currentOperator,
    currentUser,
    accounts,
    refreshAccounts,
    getAccountLabel,
    isTenantLocked,
  } = useApp();
  // Selected config tab
  const [selectedAccount, setSelectedAccount] = useState<Account>(activeAccount);
  const [selectedChannel, setSelectedChannel] = useState<Channel>(activeChannel);

  // New Account Modal state
  const [showAddModal, setShowAddModal] = useState(false);
  const [newAccountName, setNewAccountName] = useState('');
  const [newAccountId, setNewAccountId] = useState('');
  const [creatingAccount, setCreatingAccount] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [accountToDelete, setAccountToDelete] = useState<{ id: string; name: string } | null>(null);
  const [deleting, setDeleting] = useState(false);
  // WhatsApp form fields
  const [wabaAuthToken, setWabaAuthToken] = useState('');
  const [wabaId, setWabaId] = useState('');
  const [bearerToken, setBearerToken] = useState('');
  const [session, setSession] = useState('');
  const [user, setUser] = useState('');
  const [showPortalCreds, setShowPortalCreds] = useState(false);
  const [portalUsername, setPortalUsername] = useState('');
  const [portalPassword, setPortalPassword] = useState('');
  const [refreshingSession, setRefreshingSession] = useState(false);
  // RCS form fields
  const [entityId, setEntityId] = useState('');
  const [loungeCookie, setLoungeCookie] = useState('');

  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);

  // Load server-configured credentials (synced across all devices & team members)
  useEffect(() => {
    let ignore = false;
    async function loadServerCreds() {
      try {
        const creds = await fetchCredentials(selectedAccount, selectedChannel);
        if (ignore) return;
        if (selectedChannel === 'whatsapp') {
          setWabaAuthToken(creds.waba_auth_token || '');
          setWabaId(creds.waba_id || '');
          setBearerToken(creds.bearer_token || '');
          setSession(creds.session || '');
          setUser(creds.user || '');
        } else {
          setEntityId(creds.entity_id || '');
          setLoungeCookie(creds.lounge_cookie || '');
        }
      } catch {
        if (ignore) return;
        try {
          const cacheKey = `karix_creds_${selectedAccount}_${selectedChannel}`;
          const saved = localStorage.getItem(cacheKey);
          if (saved) {
            const parsed = JSON.parse(saved);
            if (selectedChannel === 'whatsapp') {
              setWabaAuthToken(parsed.waba_auth_token || '');
              setWabaId(parsed.waba_id || '');
              setBearerToken(parsed.bearer_token || '');
              setSession(parsed.session || '');
              setUser(parsed.user || '');
            } else {
              setEntityId(parsed.entity_id || '');
              setLoungeCookie(parsed.lounge_cookie || '');
            }
          }
        } catch {}
      }
    }
    loadServerCreds();
    return () => {
      ignore = true;
    };
  }, [selectedAccount, selectedChannel]);
  const isWhatsApp = selectedChannel === 'whatsapp';
  const isTata = selectedAccount === 'tata';
  const isBajaj = selectedAccount === 'bajaj';
  const envPrefix = isTata
    ? 'TATA'
    : isBajaj
    ? 'BAJAJ'
    : selectedAccount.replace(/[^a-zA-Z0-9_]/g, '_').toUpperCase();

  const accountTitle = getAccountLabel(selectedAccount);
  const channelTitle = isWhatsApp ? 'WhatsApp' : 'RCS (DLT)';

  const selectedAccountItem = accounts.find((a) => a.id === selectedAccount);
  const isCustomAccount = selectedAccountItem && !selectedAccountItem.is_builtin;

  async function handleCreateAccount(e: React.FormEvent) {
    e.preventDefault();
    if (!newAccountName.trim()) return;
    setCreatingAccount(true);
    setCreateError(null);
    try {
      const created = await createAccount(
        newAccountName.trim(),
        newAccountId.trim() || undefined,
        currentOperator
      );
      await refreshAccounts();
      setSelectedAccount(created.id);
      setShowAddModal(false);
      setNewAccountName('');
      setNewAccountId('');
      setBanner({ type: 'success', message: `Account "${created.name}" created! You can now configure its WABA credentials.` });
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create account');
    } finally {
      setCreatingAccount(false);
    }
  }

  async function handleConfirmDelete() {
    if (!accountToDelete) return;
    const accId = accountToDelete.id;
    const accName = accountToDelete.name;
    setDeleting(true);
    try {
      try {
        localStorage.removeItem(`karix_creds_${accId}_whatsapp`);
        localStorage.removeItem(`karix_creds_${accId}_rcs`);
        const stored = localStorage.getItem('karix_custom_accounts');
        if (stored) {
          const arr: AccountItem[] = JSON.parse(stored);
          const filtered = arr.filter((a) => a.id !== accId);
          localStorage.setItem('karix_custom_accounts', JSON.stringify(filtered));
        }
      } catch {}
      await deleteAccount(accId, currentOperator);
      await refreshAccounts();
      if (selectedAccount === accId) {
        setSelectedAccount('bajaj');
      }
      if (activeAccount === accId) {
        setActiveAccount('bajaj');
      }
      setAccountToDelete(null);
      setBanner({ type: 'success', message: `Account "${accName}" deleted.` });
    } catch (err) {
      setBanner({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to delete account',
      });
    } finally {
      setDeleting(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setBanner(null);
    try {
      const res = await testCredentials(selectedAccount, selectedChannel, {
        waba_auth_token: wabaAuthToken.trim() || undefined,
        waba_id: wabaId.trim() || undefined,
        bearer_token: bearerToken.trim() || undefined,
        session: session.trim() || undefined,
        user: user.trim() || undefined,
        entity_id: entityId.trim() || undefined,
        lounge_cookie: loungeCookie.trim() || undefined,
        user_name: currentOperator,
      });
      if (res.ok) {
        setBanner({ type: 'success', message: res.message || 'Connection verified successfully!' });
      } else {
        setBanner({ type: 'error', message: res.message || 'Connection test failed.' });
      }
    } catch (err) {
      setBanner({
        type: 'error',
        message: err instanceof Error ? err.message : 'Connection test failed',
      });
    } finally {
      setTesting(false);
    }
  }

  async function handleSave() {
    setSaving(true);
    setBanner(null);
    try {
      const credsToSave = {
        account: selectedAccount,
        channel: selectedChannel,
        waba_auth_token: wabaAuthToken.trim() || undefined,
        waba_id: wabaId.trim() || undefined,
        bearer_token: bearerToken.trim() || undefined,
        session: session.trim() || undefined,
        user: user.trim() || undefined,
        entity_id: entityId.trim() || undefined,
        lounge_cookie: loungeCookie.trim() || undefined,
        user_name: currentOperator,
      };
      await updateCredentials(credsToSave);

      // Save to localStorage cache so it never vanishes on page refresh
      try {
        const cacheKey = `karix_creds_${selectedAccount}_${selectedChannel}`;
        localStorage.setItem(cacheKey, JSON.stringify(credsToSave));
      } catch {}

      // Run immediate test to verify
      const testRes = await testCredentials(selectedAccount, selectedChannel, {
        waba_auth_token: wabaAuthToken.trim() || undefined,
        waba_id: wabaId.trim() || undefined,
        user_name: currentOperator,
      });

      if (testRes.ok) {
        setBanner({
          type: 'success',
          message: `Saved & Verified credentials for ${accountTitle} — ${channelTitle}! (${testRes.message})`,
        });
      } else {
        setBanner({
          type: 'success',
          message: `Saved credentials for ${accountTitle} — ${channelTitle}. (${testRes.message})`,
        });
      }
    } catch (err) {
      setBanner({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to save credentials',
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-gray-200">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Settings &amp; Credentials</h1>
          <p className="text-sm text-gray-500 mt-1">
            Manage WABA IDs, API keys, and custom client accounts for WhatsApp &amp; RCS.
          </p>
        </div>
        {!isTenantLocked && (
          <button
            onClick={() => {
              setShowAddModal(true);
              setCreateError(null);
            }}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-colors self-start sm:self-auto"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Add New Account
          </button>
        )}
      </div>

      {/* Tenant Security Notice */}
      {isTenantLocked && (
        <div className="p-3.5 bg-blue-50/70 border border-blue-200 rounded-xl text-xs text-blue-800 flex items-center justify-between shadow-2xs">
          <div className="flex items-center gap-2.5">
            <span className="text-base">🔒</span>
            <div>
              <span className="font-bold">Multi-Tenant Boundary Active: </span>
              <span>Logged in as <strong>{currentUser?.name}</strong> ({currentUser?.email}). Scoped exclusively to <strong>{getAccountLabel(currentUser?.tenant_id)}</strong>.</span>
            </div>
          </div>
          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-100 text-blue-900 uppercase">
            {currentUser?.role || 'Operator'}
          </span>
        </div>
      )}

      {/* Account Cards & Selector */}
      <div className="space-y-3">
        <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider">
          Select Client Account
        </label>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2.5">
          {accounts.map((acc) => {
            const isSelected = selectedAccount === acc.id;
            return (
              <div
                key={acc.id}
                onClick={() => {
                  setSelectedAccount(acc.id);
                  setBanner(null);
                }}
                className={`group relative p-3 rounded-xl border text-left cursor-pointer transition-all ${
                  isSelected
                    ? 'bg-blue-50/70 border-blue-500 shadow-xs ring-2 ring-blue-500/20'
                    : 'bg-white border-gray-200 hover:border-gray-300 hover:bg-gray-50/50'
                }`}
              >
                <div className="flex items-center justify-between gap-1 mb-1">
                  <span className="text-xs font-bold text-gray-900 truncate">
                    {acc.name}
                  </span>
                  {!acc.is_builtin && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setAccountToDelete({ id: acc.id, name: acc.name });
                      }}
                      title="Delete custom account"
                      className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-600 transition-opacity p-0.5"
                    >
                      <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                      </svg>
                    </button>
                  )}
                </div>
                <div className="flex items-center gap-1.5 text-[10px] text-gray-500 font-mono">
                  <span>ID: {acc.id}</span>
                  {acc.id === activeAccount && (
                    <span className="ml-auto inline-flex items-center px-1.5 py-0.2 rounded text-[9px] font-bold bg-emerald-100 text-emerald-800">
                      ACTIVE
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Channel Tabs */}
      <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-2">
        <div className="flex flex-wrap gap-2">
          {/* WhatsApp Tab */}
          <button
            onClick={() => {
              setSelectedChannel('whatsapp');
              setBanner(null);
            }}
            className={`px-4 py-2 rounded-lg text-xs font-bold transition-colors flex items-center gap-2 ${
              selectedChannel === 'whatsapp'
                ? 'bg-blue-600 text-white shadow-xs'
                : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            {accountTitle} — WhatsApp
          </button>

          {/* RCS Tab */}
          <button
            onClick={() => {
              setSelectedChannel('rcs');
              setBanner(null);
            }}
            className={`px-4 py-2 rounded-lg text-xs font-bold transition-colors flex items-center gap-2 ${
              selectedChannel === 'rcs'
                ? 'bg-blue-600 text-white shadow-xs'
                : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-blue-400" />
            {accountTitle} — RCS (DLT)
          </button>
        </div>
      </div>

      {/* Target Info Banner */}
      <div className="flex items-center justify-between p-4 bg-blue-50/50 border border-blue-100 rounded-xl">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-600 text-white flex items-center justify-center font-bold text-xs uppercase">
            {accountTitle.slice(0, 2)}
          </div>
          <div>
            <div className="text-xs font-bold text-gray-900">
              Configuring: {accountTitle} &bull; {channelTitle}
            </div>
            <div className="text-[11px] text-gray-500">
              {isWhatsApp
                ? 'Official WhatsApp Template REST API via static Bearer Token'
                : 'DLT Template Registration via Karix Lounge / RCS Bot Builder'}
            </div>
          </div>
        </div>

        <button
          onClick={() => {
            setActiveAccount(selectedAccount);
            setActiveChannel(selectedChannel);
            setBanner({
              type: 'success',
              message: `Active Context switched to ${accountTitle} • ${channelTitle}.`,
            });
          }}
          className="px-3 py-1.5 bg-white border border-blue-200 text-blue-700 text-xs font-semibold rounded-lg hover:bg-blue-50 transition-colors shadow-xs"
        >
          Set as Active Context
        </button>
      </div>

      {/* Credential Form Card */}
      <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-6 space-y-5">
        {isWhatsApp ? (
          <>
            {/* WABA Auth Token */}
            <div>
              <label htmlFor="waba_auth_token" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                Official WABA API Token ({envPrefix}_WABA_AUTH_TOKEN)
              </label>
              <input
                id="waba_auth_token"
                type="password"
                value={wabaAuthToken}
                onChange={(e) => setWabaAuthToken(e.target.value)}
                placeholder="Enter static Bearer token from Karix Lounge..."
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors"
              />
              <p className="text-[11px] text-gray-400 mt-1">
                Static token generated from Karix Lounge for {accountTitle}. Does not expire with browser sessions.
              </p>
            </div>

            {/* WABA ID */}
            <div>
              <label htmlFor="waba_id" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                WhatsApp Business Account ID ({envPrefix}_WABA_ID)
              </label>
              <input
                id="waba_id"
                type="text"
                value={wabaId}
                onChange={(e) => setWabaId(e.target.value)}
                placeholder="e.g. 1064104141771475"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors"
              />
              <p className="text-[11px] text-gray-400 mt-1">
                The numeric WhatsApp Business Account ID assigned to {accountTitle} by Meta / Karix.
              </p>
            </div>

            {/* Optional Portal Credentials */}
            <div className="pt-2 border-t border-gray-100">
              <button
                type="button"
                onClick={() => setShowPortalCreds((prev) => !prev)}
                className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1 font-medium"
              >
                <span>{showPortalCreds ? 'Hide' : 'Show'} Portal Session & Self-Healing Browser Auth</span>
                <span className="text-[10px] text-gray-400">(Auto-harvests Bearer & Session on 401)</span>
              </button>

              {showPortalCreds && (
                <div className="mt-4 space-y-5 p-4 bg-gray-50 rounded-xl border border-gray-200">
                  {/* Self-Healing Auto-Login Box */}
                  <div className="p-3.5 bg-white rounded-lg border border-blue-100 shadow-2xs space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-sm">⚡</span>
                        <div>
                          <h4 className="text-xs font-bold text-gray-900">Self-Healing Browser Login (Playwright)</h4>
                          <p className="text-[11px] text-gray-500">
                            Launches a headless browser, logs into Karix portal, and automatically extracts fresh tokens.
                          </p>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={async () => {
                          setRefreshingSession(true);
                          setBanner(null);
                          try {
                            const res = await refreshSession(
                              selectedAccount,
                              portalUsername.trim() || undefined,
                              portalPassword.trim() || undefined,
                              currentOperator || 'Operator'
                            );
                            setBanner({ type: 'success', message: res.message || 'Session refreshed successfully!' });
                            const creds = await fetchCredentials(selectedAccount, selectedChannel);
                            setBearerToken(creds.bearer_token || '');
                            setSession(creds.session || '');
                            setUser(creds.user || '');
                          } catch (err) {
                            setBanner({
                              type: 'error',
                              message: err instanceof Error ? err.message : String(err),
                            });
                          } finally {
                            setRefreshingSession(false);
                          }
                        }}
                        disabled={refreshingSession}
                        className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition shrink-0"
                      >
                        {refreshingSession ? (
                          <>
                            <span className="w-2 h-2 rounded-full bg-white animate-pulse" />
                            <span>Logging in...</span>
                          </>
                        ) : (
                          <>
                            <span>⚡ Run Auto-Login</span>
                          </>
                        )}
                      </button>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-gray-100">
                      <div>
                        <label htmlFor="portal_user" className="block text-[11px] font-bold text-gray-600 uppercase tracking-wider mb-1">
                          Portal Username / Email ({envPrefix}_PORTAL_USER)
                        </label>
                        <input
                          id="portal_user"
                          type="text"
                          value={portalUsername}
                          onChange={(e) => setPortalUsername(e.target.value)}
                          placeholder="e.g. operator@company.com"
                          className="w-full border border-gray-300 rounded-lg px-2.5 py-1.5 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none bg-gray-50/50"
                        />
                      </div>
                      <div>
                        <label htmlFor="portal_pass" className="block text-[11px] font-bold text-gray-600 uppercase tracking-wider mb-1">
                          Portal Password ({envPrefix}_PORTAL_PASSWORD)
                        </label>
                        <input
                          id="portal_pass"
                          type="password"
                          value={portalPassword}
                          onChange={(e) => setPortalPassword(e.target.value)}
                          placeholder="••••••••••••"
                          className="w-full border border-gray-300 rounded-lg px-2.5 py-1.5 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none bg-gray-50/50"
                        />
                      </div>
                    </div>
                  </div>

                  <div>
                    <label htmlFor="bearer_token" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                      Current Portal Bearer Token ({envPrefix}_KARIX_BEARER_TOKEN)
                    </label>
                    <input
                      id="bearer_token"
                      type="password"
                      value={bearerToken}
                      onChange={(e) => setBearerToken(e.target.value)}
                      placeholder="e.g. eyJhbGciOi..."
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors bg-white"
                    />
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label htmlFor="session" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                        Session ID ({envPrefix}_KARIX_SESSION)
                      </label>
                      <input
                        id="session"
                        type="password"
                        value={session}
                        onChange={(e) => setSession(e.target.value)}
                        placeholder="Session header from DevTools..."
                        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors bg-white"
                      />
                    </div>

                    <div>
                      <label htmlFor="user" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                        User Header ({envPrefix}_KARIX_USER)
                      </label>
                      <input
                        id="user"
                        type="text"
                        value={user}
                        onChange={(e) => setUser(e.target.value)}
                        placeholder="User header from DevTools..."
                        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors bg-white"
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          <>
            {/* RCS DLT Entity ID */}
            <div>
              <label htmlFor="entity_id" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                DLT Principal Entity ID ({envPrefix}_ENTITY_ID)
              </label>
              <input
                id="entity_id"
                type="text"
                value={entityId}
                onChange={(e) => setEntityId(e.target.value)}
                placeholder="e.g. 1001490234791338781"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors"
              />
              <p className="text-[11px] text-gray-400 mt-1">
                Govt. DLT Registration Principal Entity ID (PE ID) registered on Vilpower / Jio / Airtel DLT portal.
              </p>
            </div>

            {/* Karix Lounge Cookie */}
            <div>
              <label htmlFor="lounge_cookie" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                Karix Lounge Session Cookie ({envPrefix}_KARIX_LOUNGE_COOKIE)
              </label>
              <input
                id="lounge_cookie"
                type="password"
                value={loungeCookie}
                onChange={(e) => setLoungeCookie(e.target.value)}
                placeholder="PHPSESSID=... from lounge.karix.solutions"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors"
              />
              <p className="text-[11px] text-gray-400 mt-1">
                Required for automated submission to Karix Lounge DLT Registration.
              </p>
            </div>
          </>
        )}

        {/* Action Buttons */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 pt-4 border-t border-gray-100">
          <div className="text-[11px] text-gray-400">
            Current operator: <span className="font-semibold text-gray-600">{currentOperator}</span>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleTest}
              disabled={testing || saving}
              className="flex-1 sm:flex-none px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-lg transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {testing ? (
                <>
                  <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                  Testing...
                </>
              ) : (
                'Test Connection'
              )}
            </button>

            <button
              type="button"
              onClick={handleSave}
              disabled={saving || testing}
              className="flex-1 sm:flex-none px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {saving ? (
                <>
                  <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                  Saving...
                </>
              ) : (
                'Save Credentials'
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Banner */}
      {banner && (
        <div
          className={`p-4 rounded-xl text-xs font-medium flex items-start gap-3 border ${
            banner.type === 'success'
              ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
              : 'bg-red-50 text-red-800 border-red-200'
          }`}
        >
          {banner.type === 'success' ? (
            <svg className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
          ) : (
            <svg className="w-4 h-4 text-red-600 shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
            </svg>
          )}
          <span className="flex-1 leading-relaxed">{banner.message}</span>
          <button onClick={() => setBanner(null)} className="text-gray-400 hover:text-gray-600 text-sm font-bold">
            &times;
          </button>
        </div>
      )}

      {/* Add Account Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-gray-100 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-gray-900">Add New Client Account</h3>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-gray-400 hover:text-gray-600 font-bold"
              >
                &times;
              </button>
            </div>

            <p className="text-xs text-gray-500">
              Create a new client environment (e.g. Kotak Mahindra, HDFC Bank, Axis, Groww). Each account maintains its own isolated credentials and template logs.
            </p>

            <form onSubmit={handleCreateAccount} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                  Account Display Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Kotak Mahindra Bank"
                  value={newAccountName}
                  onChange={(e) => setNewAccountName(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                  Account Identifier Slug <span className="text-gray-400 font-normal">(Optional)</span>
                </label>
                <input
                  type="text"
                  placeholder="e.g. kotak (auto-generated if empty)"
                  value={newAccountId}
                  onChange={(e) => setNewAccountId(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                />
              </div>

              {createError && (
                <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded-lg">
                  {createError}
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creatingAccount || !newAccountName.trim()}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1.5"
                >
                  {creatingAccount ? 'Creating...' : 'Create Account'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {accountToDelete && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-sm w-full p-6 shadow-xl border border-gray-100 space-y-4">
            <div className="flex items-center gap-3 text-red-600">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center shrink-0">
                <svg className="w-5 h-5 text-red-600" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
              </div>
              <div>
                <h3 className="text-base font-bold text-gray-900">Delete Account?</h3>
                <p className="text-xs text-gray-500">This action cannot be undone.</p>
              </div>
            </div>

            <p className="text-xs text-gray-600 leading-relaxed">
              Are you sure you want to delete <span className="font-bold text-gray-900">&quot;{accountToDelete.name}&quot;</span>? All saved WABA tokens, IDs, and configurations for this brand will be removed.
            </p>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setAccountToDelete(null)}
                disabled={deleting}
                className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmDelete}
                disabled={deleting}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-xs font-semibold rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1.5"
              >
                {deleting ? 'Deleting...' : 'Delete Account'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
