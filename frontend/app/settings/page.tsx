'use client';

import { useState } from 'react';
import { updateCredentials, testCredentials } from '@/lib/api';
import type { Account, Channel } from '@/lib/api';
import { useApp } from '@/lib/context';

type Banner = { type: 'success' | 'error'; message: string } | null;

export default function SettingsPage() {
  const { account: activeAccount, channel: activeChannel, setAccount: setActiveAccount, setChannel: setActiveChannel } = useApp();

  // Selected config tab
  const [selectedAccount, setSelectedAccount] = useState<Account>(activeAccount);
  const [selectedChannel, setSelectedChannel] = useState<Channel>(activeChannel);

  // WhatsApp form fields
  const [wabaAuthToken, setWabaAuthToken] = useState('');
  const [wabaId, setWabaId] = useState('');
  const [bearerToken, setBearerToken] = useState('');
  const [session, setSession] = useState('');
  const [user, setUser] = useState('');
  const [showPortalCreds, setShowPortalCreds] = useState(false);

  // RCS form fields
  const [entityId, setEntityId] = useState('');
  const [loungeCookie, setLoungeCookie] = useState('');

  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);

  const isWhatsApp = selectedChannel === 'whatsapp';
  const isTata = selectedAccount === 'tata';
  const accountTitle = isTata ? 'Tata Capital' : 'Bajaj';
  const channelTitle = isWhatsApp ? 'WhatsApp' : 'RCS (DLT)';

  async function handleTest() {
    setTesting(true);
    setBanner(null);
    try {
      const res = await testCredentials(selectedAccount, selectedChannel);
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
      await updateCredentials({
        account: selectedAccount,
        channel: selectedChannel,
        waba_auth_token: wabaAuthToken.trim() || undefined,
        waba_id: wabaId.trim() || undefined,
        bearer_token: bearerToken.trim() || undefined,
        session: session.trim() || undefined,
        user: user.trim() || undefined,
        entity_id: entityId.trim() || undefined,
        lounge_cookie: loungeCookie.trim() || undefined,
      });

      setBanner({
        type: 'success',
        message: `Saved credentials for ${accountTitle} — ${channelTitle} successfully!`,
      });

      // Clear input fields
      setWabaAuthToken('');
      setWabaId('');
      setBearerToken('');
      setSession('');
      setUser('');
      setEntityId('');
      setLoungeCookie('');
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
      <div className="pb-2 border-b border-gray-200">
        <h1 className="text-2xl font-bold text-gray-900">Settings &amp; Credentials</h1>
        <p className="text-sm text-gray-500 mt-1">
          Manage API keys, WABA IDs, and portal credentials across accounts and channels.
        </p>
      </div>

      {/* Account & Channel Tabs */}
      <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-2">
        <div className="flex flex-wrap gap-2">
          {/* Bajaj WhatsApp */}
          <button
            onClick={() => {
              setSelectedAccount('bajaj');
              setSelectedChannel('whatsapp');
              setBanner(null);
            }}
            className={`px-4 py-2 rounded-lg text-xs font-bold transition-colors flex items-center gap-2 ${
              selectedAccount === 'bajaj' && selectedChannel === 'whatsapp'
                ? 'bg-indigo-600 text-white shadow-xs'
                : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            Bajaj — WhatsApp
          </button>

          {/* Bajaj RCS */}
          <button
            onClick={() => {
              setSelectedAccount('bajaj');
              setSelectedChannel('rcs');
              setBanner(null);
            }}
            className={`px-4 py-2 rounded-lg text-xs font-bold transition-colors flex items-center gap-2 ${
              selectedAccount === 'bajaj' && selectedChannel === 'rcs'
                ? 'bg-indigo-600 text-white shadow-xs'
                : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-blue-400" />
            Bajaj — RCS
          </button>

          {/* Tata WhatsApp */}
          <button
            onClick={() => {
              setSelectedAccount('tata');
              setSelectedChannel('whatsapp');
              setBanner(null);
            }}
            className={`px-4 py-2 rounded-lg text-xs font-bold transition-colors flex items-center gap-2 ${
              selectedAccount === 'tata' && selectedChannel === 'whatsapp'
                ? 'bg-indigo-600 text-white shadow-xs'
                : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            Tata Capital — WhatsApp
          </button>

          {/* Tata RCS */}
          <button
            onClick={() => {
              setSelectedAccount('tata');
              setSelectedChannel('rcs');
              setBanner(null);
            }}
            className={`px-4 py-2 rounded-lg text-xs font-bold transition-colors flex items-center gap-2 ${
              selectedAccount === 'tata' && selectedChannel === 'rcs'
                ? 'bg-indigo-600 text-white shadow-xs'
                : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-blue-400" />
            Tata Capital — RCS
          </button>
        </div>
      </div>

      {/* Target Info Banner */}
      <div className="flex items-center justify-between p-4 bg-indigo-50/50 border border-indigo-100 rounded-xl">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-indigo-600 text-white flex items-center justify-center font-bold text-xs">
            {isTata ? 'TC' : 'B'}
          </div>
          <div>
            <div className="text-xs font-bold text-gray-900">
              Configuring: {accountTitle} &bull; {channelTitle}
            </div>
            <div className="text-[11px] text-gray-500">
              {isWhatsApp
                ? 'Official WhatsApp Template REST API via static Bearer Token'
                : 'DLT Template Registration via Karix Lounge'}
            </div>
          </div>
        </div>

        <button
          onClick={() => {
            setActiveAccount(selectedAccount);
            setActiveChannel(selectedChannel);
          }}
          className="px-3 py-1.5 bg-white border border-indigo-200 text-indigo-700 text-xs font-semibold rounded-lg hover:bg-indigo-50 transition-colors shadow-xs"
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
                Official WABA API Token ({isTata ? 'TATA_WABA_AUTH_TOKEN' : 'WABA_AUTH_TOKEN'})
              </label>
              <input
                id="waba_auth_token"
                type="password"
                value={wabaAuthToken}
                onChange={e => setWabaAuthToken(e.target.value)}
                placeholder="Enter static Bearer token from Karix Lounge..."
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-colors"
              />
              <p className="text-[11px] text-gray-400 mt-1">
                Static token generated from Karix Lounge. Does not expire with browser sessions.
              </p>
            </div>

            {/* WABA ID */}
            <div>
              <label htmlFor="waba_id" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                WhatsApp Business Account ID ({isTata ? 'TATA_WABA_ID' : 'BAJAJ_WABA_ID'})
              </label>
              <input
                id="waba_id"
                type="text"
                value={wabaId}
                onChange={e => setWabaId(e.target.value)}
                placeholder={isTata ? 'e.g. 109823487123984' : '286109054585247'}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-colors"
              />
            </div>

            {/* Optional Portal Credentials */}
            <div className="pt-2 border-t border-gray-100">
              <button
                type="button"
                onClick={() => setShowPortalCreds(!showPortalCreds)}
                className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 flex items-center gap-1.5"
              >
                <span>{showPortalCreds ? '▼' : '▶'}</span>
                <span>Legacy Portal Session Headers (Optional — only for image media uploads)</span>
              </button>
            </div>

            {showPortalCreds && (
              <div className="space-y-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
                <div>
                  <label htmlFor="bearer_token" className="block text-xs font-medium text-gray-700 mb-1">
                    Portal Bearer Token
                  </label>
                  <textarea
                    id="bearer_token"
                    rows={2}
                    value={bearerToken}
                    onChange={e => setBearerToken(e.target.value)}
                    placeholder="eyJhbGciOi..."
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-colors resize-none"
                  />
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="session" className="block text-xs font-medium text-gray-700 mb-1">
                      Session ID
                    </label>
                    <input
                      id="session"
                      type="text"
                      value={session}
                      onChange={e => setSession(e.target.value)}
                      placeholder="6a757401c8ba692973064983"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-colors"
                    />
                  </div>
                  <div>
                    <label htmlFor="user" className="block text-xs font-medium text-gray-700 mb-1">
                      User
                    </label>
                    <input
                      id="user"
                      type="text"
                      value={user}
                      onChange={e => setUser(e.target.value)}
                      placeholder="Username / Nirmal"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-colors"
                    />
                  </div>
                </div>
              </div>
            )}
          </>
        ) : (
          <>
            {/* Entity ID */}
            <div>
              <label htmlFor="entity_id" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                DLT Principal Entity ID ({isTata ? 'TATA_ENTITY_ID' : 'BAJAJ_ENTITY_ID'})
              </label>
              <input
                id="entity_id"
                type="text"
                value={entityId}
                onChange={e => setEntityId(e.target.value)}
                placeholder={isTata ? 'e.g. 110100009999' : '110100001654'}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-colors"
              />
              <p className="text-[11px] text-gray-400 mt-1">
                DLT Principal Entity ID registered with telemarketer / Karix Lounge.
              </p>
            </div>

            {/* Karix Lounge Cookie */}
            <div>
              <label htmlFor="lounge_cookie" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                Karix Lounge Session Cookie ({isTata ? 'TATA_KARIX_LOUNGE_COOKIE' : 'KARIX_LOUNGE_COOKIE'})
              </label>
              <textarea
                id="lounge_cookie"
                rows={2}
                value={loungeCookie}
                onChange={e => setLoungeCookie(e.target.value)}
                placeholder="PHPSESSID=...; login_user=..."
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-colors resize-none"
              />
              <p className="text-[11px] text-gray-400 mt-1">
                Extracted from logged-in Karix Lounge session (karix.solutions/lounge).
              </p>
            </div>
          </>
        )}

        {/* Banner */}
        {banner && (
          <div
            className={`rounded-lg p-4 text-xs font-semibold ${
              banner.type === 'success'
                ? 'bg-emerald-50 border border-emerald-200 text-emerald-800'
                : 'bg-red-50 border border-red-200 text-red-700'
            }`}
          >
            {banner.message}
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-3 pt-2">
          <button
            onClick={handleTest}
            disabled={testing}
            className="inline-flex items-center gap-2 bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 px-4 py-2 rounded-lg text-xs font-bold shadow-xs transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {testing && (
              <svg className="animate-spin h-3.5 w-3.5 text-gray-500" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
              </svg>
            )}
            Test Connection ({accountTitle} &bull; {channelTitle})
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-xs font-bold shadow-xs transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving && (
              <svg className="animate-spin h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
              </svg>
            )}
            Save Credentials
          </button>
        </div>
      </div>

      {/* Help Guide */}
      <div className="bg-gray-50 rounded-xl border border-gray-200/80 p-6">
        <h3 className="text-xs font-bold text-gray-900 uppercase tracking-wider mb-3">
          How to get credentials for {accountTitle} ({channelTitle})
        </h3>
        {isWhatsApp ? (
          <ol className="list-decimal list-inside space-y-2 text-xs text-gray-700">
            <li>Log into the Karix Lounge portal for {accountTitle} (<span className="font-mono text-indigo-600">karix.solutions/lounge</span>).</li>
            <li>Navigate to the API Keys section to generate your static WABA Template API Token.</li>
            <li>Copy your WABA ID from your WhatsApp Business Account settings in Meta Business Manager or Karix.</li>
            <li>Paste into the fields above and click <span className="font-semibold text-gray-800">&quot;Save Credentials&quot;</span>.</li>
          </ol>
        ) : (
          <ol className="list-decimal list-inside space-y-2 text-xs text-gray-700">
            <li>Log into the Karix Lounge DLT portal for {accountTitle}.</li>
            <li>Obtain your 12-digit DLT Principal Entity ID registered with Karix.</li>
            <li>For session cookie: Open DevTools (F12) on Lounge &rarr; Copy Cookie header from any registration request.</li>
            <li>Paste into the fields above and click <span className="font-semibold text-gray-800">&quot;Save Credentials&quot;</span>.</li>
          </ol>
        )}
      </div>
    </div>
  );
}
