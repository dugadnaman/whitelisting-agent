'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { fetchAccounts, fetchUsers, registerUser } from './api';
import type { Account, Channel, AccountItem, UserItem } from './api';

const DEFAULT_ACCOUNTS: AccountItem[] = [
  { id: 'bajaj', name: 'Bajaj Finserv', is_builtin: true },
  { id: 'tata', name: 'Tata Capital', is_builtin: true },
];

type AppContextType = {
  account: Account;
  setAccount: (account: Account) => void;
  channel: Channel;
  setChannel: (channel: Channel) => void;
  user: string;
  setUser: (user: string) => void;
  accounts: AccountItem[];
  refreshAccounts: () => Promise<void>;
  getAccountLabel: (account?: string) => string;
  users: UserItem[];
  refreshUsers: () => Promise<void>;
  openUserModal: () => void;
  mounted: boolean;
};

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [account, setAccountState] = useState<Account>('bajaj');
  const [channel, setChannelState] = useState<Channel>('whatsapp');
  const [user, setUserState] = useState<string>('');
  const [accounts, setAccounts] = useState<AccountItem[]>(DEFAULT_ACCOUNTS);
  const [users, setUsers] = useState<UserItem[]>([]);
  const [mounted, setMounted] = useState(false);

  // User Identity Modal state
  const [showUserModal, setShowUserModal] = useState(false);
  const [nameInput, setNameInput] = useState('');
  const [roleInput, setRoleInput] = useState('Operator');
  const [registering, setRegistering] = useState(false);

  const refreshAccounts = useCallback(async () => {
    let localCustom: AccountItem[] = [];
    try {
      const stored = localStorage.getItem('karix_custom_accounts');
      if (stored) {
        localCustom = JSON.parse(stored);
      }
    } catch {}

    try {
      const data = await fetchAccounts();
      if (Array.isArray(data) && data.length > 0) {
        const mergedMap = new Map<string, AccountItem>();
        for (const a of data) {
          mergedMap.set(a.id, a);
        }
        for (const localA of localCustom) {
          if (!mergedMap.has(localA.id)) {
            mergedMap.set(localA.id, localA);
            fetch('/api/accounts', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ name: localA.name, id: localA.id }),
            }).catch(() => {});
          }
        }
        const merged = Array.from(mergedMap.values());
        setAccounts(merged);
        const customOnly = merged.filter((a) => !a.is_builtin);
        try {
          localStorage.setItem('karix_custom_accounts', JSON.stringify(customOnly));
        } catch {}
      }
    } catch (err) {
      console.warn('Could not load accounts list:', err);
      if (localCustom.length > 0) {
        const fallbackMap = new Map<string, AccountItem>();
        for (const d of DEFAULT_ACCOUNTS) fallbackMap.set(d.id, d);
        for (const c of localCustom) fallbackMap.set(c.id, c);
        setAccounts(Array.from(fallbackMap.values()));
      }
    }
  }, []);

  const refreshUsers = useCallback(async () => {
    try {
      const data = await fetchUsers();
      if (Array.isArray(data)) {
        setUsers(data);
      }
    } catch (err) {
      console.warn('Could not load team users list:', err);
    }
  }, []);

  useEffect(() => {
    try {
      const savedAccount = localStorage.getItem('karix_account');
      const savedChannel = localStorage.getItem('karix_channel') as Channel;
      if (savedAccount && savedAccount.trim()) {
        setAccountState(savedAccount.trim());
      }
      if (savedChannel === 'whatsapp' || savedChannel === 'rcs') {
        setChannelState(savedChannel);
      }

      const savedUser = localStorage.getItem('karix_user');
      if (savedUser && savedUser.trim()) {
        setUserState(savedUser.trim());
      } else {
        // First-time user on this browser: show setup modal
        setShowUserModal(true);
      }
    } catch {
      // ignore localStorage failures
    }
    // Auto-sync all saved credentials from browser storage to backend in background
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith('karix_creds_')) {
          const raw = localStorage.getItem(k);
          if (raw) {
            try {
              const creds = JSON.parse(raw);
              if (creds && creds.account) {
                fetch('/api/credentials', {
                  method: 'PUT',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(creds),
                }).catch(() => {});
              }
            } catch {}
          }
        }
      }
    } catch {}

    setMounted(true);
    refreshAccounts();
    refreshUsers();
  }, [refreshAccounts, refreshUsers]);
  const setAccount = (newAccount: Account) => {
    setAccountState(newAccount);
    try {
      localStorage.setItem('karix_account', newAccount);
    } catch {}
  };

  const setChannel = (newChannel: Channel) => {
    setChannelState(newChannel);
    try {
      localStorage.setItem('karix_channel', newChannel);
    } catch {}
  };

  const setUser = (newUser: string) => {
    const u = newUser.trim() || 'Team Operator';
    setUserState(u);
    try {
      localStorage.setItem('karix_user', u);
    } catch {}
    registerUser(u).catch(() => {});
  };

  const handleSaveUserModal = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const finalName = nameInput.trim();
    if (!finalName) return;
    setRegistering(true);
    try {
      await registerUser(finalName, roleInput);
      setUser(finalName);
      await refreshUsers();
      setShowUserModal(false);
      setNameInput('');
    } catch (err) {
      console.error('Error saving operator profile:', err);
      setUser(finalName);
      setShowUserModal(false);
    } finally {
      setRegistering(false);
    }
  };

  const handlePickExistingUser = (uName: string) => {
    setUser(uName);
    setShowUserModal(false);
  };

  const getAccountLabel = useCallback((accId?: string): string => {
    const target = (accId || account || '').toLowerCase().trim();
    if (!target) return 'Account';
    if (target === 'bajaj') return 'Bajaj';
    if (target === 'tata') return 'Tata Capital';
    const found = accounts.find((a) => a.id.toLowerCase() === target);
    if (found) return found.name;
    return target.replace(/[_-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }, [account, accounts]);

  return (
    <AppContext.Provider
      value={{
        account,
        setAccount,
        channel,
        setChannel,
        user: user || 'Team Operator',
        setUser,
        accounts,
        refreshAccounts,
        getAccountLabel,
        users,
        refreshUsers,
        openUserModal: () => setShowUserModal(true),
        mounted,
      }}
    >
      {children}

      {/* Operator Identity Onboarding / Switch Modal */}
      {showUserModal && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl border border-gray-100 space-y-5">
            <div className="flex items-center justify-between pb-2 border-b border-gray-100">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-blue-600 text-white flex items-center justify-center font-bold text-sm shadow-sm">
                  K
                </div>
                <div>
                  <h3 className="text-base font-bold text-gray-900">Operator Identity</h3>
                  <p className="text-xs text-gray-400">Set your name for template &amp; audit tracking</p>
                </div>
              </div>
              {user && (
                <button
                  onClick={() => setShowUserModal(false)}
                  className="text-gray-400 hover:text-gray-600 font-bold p-1"
                >
                  &times;
                </button>
              )}
            </div>

            {/* If there are existing team members, offer quick-select */}
            {users.length > 0 && (
              <div className="space-y-2">
                <label className="block text-[11px] font-bold uppercase tracking-wider text-gray-500">
                  Select Existing Team Member:
                </label>
                <div className="grid grid-cols-2 gap-2 max-h-40 overflow-y-auto p-1">
                  {users.map((u) => {
                    const isSelected = (user || '').toLowerCase() === u.name.toLowerCase();
                    return (
                      <button
                        key={u.id || u.name}
                        type="button"
                        onClick={() => handlePickExistingUser(u.name)}
                        className={`p-2.5 rounded-xl border text-left flex items-center gap-2 transition-all ${
                          isSelected
                            ? 'bg-blue-50 border-blue-500 ring-2 ring-blue-500/20'
                            : 'bg-gray-50/70 border-gray-200 hover:bg-gray-100 hover:border-gray-300'
                        }`}
                      >
                        <div className="w-6 h-6 rounded-full bg-blue-600 text-white font-bold text-[10px] flex items-center justify-center shrink-0">
                          {u.name.charAt(0).toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs font-bold text-gray-900 truncate">{u.name}</p>
                          <p className="text-[10px] text-gray-400 truncate">{u.role || 'Operator'}</p>
                        </div>
                      </button>
                    );
                  })}
                </div>
                <div className="relative flex py-1 items-center">
                  <div className="flex-grow border-t border-gray-200"></div>
                  <span className="flex-shrink mx-2 text-[10px] font-bold text-gray-400 uppercase">Or create your own profile</span>
                  <div className="flex-grow border-t border-gray-200"></div>
                </div>
              </div>
            )}

            {/* Create New Operator Profile Form */}
            <form onSubmit={handleSaveUserModal} className="space-y-3.5">
              <div>
                <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                  Your Full Name / Alias <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Rahul Sharma, Priya P., Siddharth"
                  value={nameInput}
                  onChange={(e) => setNameInput(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3.5 py-2.5 text-xs focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors"
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                  Your Role <span className="text-gray-400 font-normal">(Optional)</span>
                </label>
                <select
                  value={roleInput}
                  onChange={(e) => setRoleInput(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs bg-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none cursor-pointer"
                >
                  <option value="Operator">Campaign Operator</option>
                  <option value="Lead">Marketing Lead</option>
                  <option value="Admin">Administrator</option>
                  <option value="QA">QA / Reviewer</option>
                </select>
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                {user && (
                  <button
                    type="button"
                    onClick={() => setShowUserModal(false)}
                    className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-lg transition-colors"
                  >
                    Cancel
                  </button>
                )}
                <button
                  type="submit"
                  disabled={registering || !nameInput.trim()}
                  className="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-colors disabled:opacity-50 flex items-center gap-1.5"
                >
                  {registering ? 'Saving Profile...' : 'Save & Continue'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </AppContext.Provider>
  );
}

export function useApp() {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
}
