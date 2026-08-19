'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { fetchAccounts } from './api';
import type { Account, Channel, AccountItem } from './api';

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
  mounted: boolean;
};

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [account, setAccountState] = useState<Account>('bajaj');
  const [channel, setChannelState] = useState<Channel>('whatsapp');
  const [user, setUserState] = useState<string>('Namann');
  const [accounts, setAccounts] = useState<AccountItem[]>(DEFAULT_ACCOUNTS);
  const [mounted, setMounted] = useState(false);

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
            // Auto-heal / re-register missing custom account on backend
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
      }
    } catch {
      // ignore localStorage failures
    }
    setMounted(true);
    refreshAccounts();
  }, [refreshAccounts]);

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
    const u = newUser.trim() || 'Anonymous Operator';
    setUserState(u);
    try {
      localStorage.setItem('karix_user', u);
    } catch {}
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
        user,
        setUser,
        accounts,
        refreshAccounts,
        getAccountLabel,
        mounted,
      }}
    >
      {children}
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
