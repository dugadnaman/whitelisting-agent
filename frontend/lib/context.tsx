'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import {
  fetchAccounts,
  fetchUsers,
  fetchMe,
  getAuthToken,
  clearAuthToken,
} from './api';
import type { Account, Channel, AccountItem, AuthUser, UserItem } from './api';

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
  currentUser: AuthUser | null;
  setCurrentUser: (user: AuthUser | null) => void;
  authLoading: boolean;
  logout: () => void;
  accounts: AccountItem[];
  refreshAccounts: () => Promise<void>;
  getAccountLabel: (account?: string) => string;
  users: UserItem[];
  refreshUsers: () => Promise<void>;
  isTenantLocked: boolean;
  mounted: boolean;
};

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  const [account, setAccountState] = useState<Account>('bajaj');
  const [channel, setChannelState] = useState<Channel>('whatsapp');
  const [user, setUserState] = useState<string>('');
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [accounts, setAccounts] = useState<AccountItem[]>(DEFAULT_ACCOUNTS);
  const [users, setUsers] = useState<UserItem[]>([]);
  const [mounted, setMounted] = useState(false);
  const isTenantLocked = Boolean(
    currentUser && currentUser.tenant_id !== 'all' && currentUser.role !== 'superadmin'
  );

  const refreshAccounts = useCallback(async () => {
    try {
      const data = await fetchAccounts();
      if (Array.isArray(data) && data.length > 0) {
        setAccounts(data);
      }
    } catch {
      // Fallback
    }
  }, []);

  const refreshUsers = useCallback(async () => {
    try {
      const data = await fetchUsers();
      if (Array.isArray(data)) {
        setUsers(data);
      }
    } catch {
      // Fallback
    }
  }, []);
  const logout = useCallback(() => {
    clearAuthToken();
    setCurrentUser(null);
    setUserState('');
    router.push('/login');
  }, [router]);

  // Authenticate user on mount
  // Authenticate user on initial mount
  useEffect(() => {
    let ignore = false;

    async function checkAuth() {
      const isAuthPage = window.location.pathname === '/login' || window.location.pathname === '/signup';
      const token = getAuthToken();

      if (!token) {
        if (!isAuthPage) {
          router.push('/login');
        }
        setAuthLoading(false);
        setMounted(true);
        return;
      }

      try {
        const userProfile = await fetchMe();
        if (ignore) return;

        setCurrentUser(userProfile);
        setUserState(userProfile.name || userProfile.email);

        // Load saved account preference if valid for tenant
        const savedAccount = localStorage.getItem('karix_account');
        if (savedAccount && savedAccount.trim()) {
          if (userProfile.tenant_id === 'tata') {
            const isTataSub = ['tata', 'tcl_promo', 'tcl_trans', 'tchfl', 'wealth', 'moneyfy'].includes(
              savedAccount.toLowerCase()
            );
            if (isTataSub) {
              setAccountState(savedAccount);
            } else {
              setAccountState('tchfl');
            }
          } else if (userProfile.tenant_id === 'bajaj') {
            setAccountState('bajaj');
          } else {
            setAccountState(savedAccount);
          }
        } else {
          setAccountState(userProfile.tenant_id === 'tata' ? 'tchfl' : userProfile.tenant_id || 'bajaj');
        }

        const savedChannel = localStorage.getItem('karix_channel') as Channel;
        if (savedChannel === 'whatsapp' || savedChannel === 'rcs') {
          setChannelState(savedChannel);
        }

        if (isAuthPage) {
          router.push('/');
        }
      } catch (err) {
        console.warn('Session expired or invalid token:', err);
        clearAuthToken();
        if (!isAuthPage) {
          router.push('/login');
        }
      } finally {
        setAuthLoading(false);
        setMounted(true);
        refreshAccounts();
      }
    }

    checkAuth();

    return () => {
      ignore = true;
    };
  }, [router, refreshAccounts]);

  const setAccount = (newAccount: Account) => {
    if (accounts.length > 0 && !accounts.some((a) => a.id.toLowerCase() === newAccount.toLowerCase())) {
      alert(`Access Denied: You do not have permission to access ${newAccount.toUpperCase()}.`);
      return;
    }
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
  };

  const getAccountLabel = useCallback(
    (accId?: string): string => {
      const target = (accId || account || '').toLowerCase().trim();
      if (!target) return 'Account';
      if (target === 'bajaj') return 'Bajaj Finserv';
      if (target === 'tata') return 'Tata Capital';
      const found = accounts.find((a) => a.id.toLowerCase() === target);
      if (found) return found.name;
      return target.replace(/[_-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    },
    [account, accounts]
  );

  return (
    <AppContext.Provider
      value={{
        account,
        setAccount,
        channel,
        setChannel,
        user: user || currentUser?.name || 'Operator',
        setUser,
        currentUser,
        setCurrentUser,
        authLoading,
        logout,
        accounts,
        refreshAccounts,
        getAccountLabel,
        users,
        refreshUsers,
        isTenantLocked,
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
