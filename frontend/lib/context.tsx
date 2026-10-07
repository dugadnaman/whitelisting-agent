'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import {
  fetchAccounts,
  fetchTeam,
  fetchMe,
  getAuthToken,
  clearAuthToken,
  canAccessAccount,
  authorizedAccount,
} from './api';
import type { Account, Channel, AccountItem, AuthUser, UserItem } from './api';

const DEFAULT_ACCOUNTS: AccountItem[] = [
  {
    id: 'tcl_promo',
    name: 'Tata Capital Limited (Promotional)',
    is_builtin: true,
    entity: 'Tata Capital Limited',
  },
  {
    id: 'tcl_trans',
    name: 'Tata Capital Limited (Transactional)',
    is_builtin: true,
    entity: 'Tata Capital Limited',
  },
  {
    id: 'tchfl',
    name: 'Tata Capital Housing Finance Limited',
    is_builtin: true,
    entity: 'Tata Capital Housing finance Limited',
  },
  {
    id: 'wealth',
    name: 'Tata Capital Wealth',
    is_builtin: true,
    entity: 'Tata Capital Wealth',
  },
  {
    id: 'moneyfy',
    name: 'Tata Capital Moneyfy',
    is_builtin: true,
    entity: 'Tata Capital Moneyfy',
  },
];

export function getRcsDetails(accId: string, accList: AccountItem[] = DEFAULT_ACCOUNTS) {
  const found = accList.find((a) => a.id === accId);
  const botId = found?.rcs_bot_id || '';
  const botName = botId ? (found?.rcs_bot_name || 'Not configured') : 'Not configured';
  const rcsUser = botId ? (found?.rcs_username || 'Not configured') : 'Not configured';
  return { botId, botName, rcsUser, entity: found?.entity || '', name: found?.name || accId };
}

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

  const [account, setAccountState] = useState<Account>('tcl_promo');
  const [channel, setChannelState] = useState<Channel>('whatsapp');
  const [user, setUserState] = useState<string>('');
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [accounts, setAccounts] = useState<AccountItem[]>(DEFAULT_ACCOUNTS);
  const [users, setUsers] = useState<UserItem[]>([]);
  const [mounted, setMounted] = useState(false);
  const isTenantLocked = Boolean(
    currentUser && currentUser.role !== 'superadmin'
  );

  const refreshAccounts = useCallback(async () => {
    try {
      const data = await fetchAccounts();
      if (Array.isArray(data)) {
        setAccounts(data);
      }
    } catch {
      // Fallback
    }
  }, []);

  const refreshUsers = useCallback(async () => {
    try {
      if (!currentUser || account === 'all') {
        setUsers([]);
        return;
      }
      const data = await fetchTeam(currentUser.role === 'superadmin' ? account : undefined);
      if (Array.isArray(data)) {
        setUsers(data);
      }
    } catch {
      // Fallback
    }
  }, [currentUser, account]);
  const logout = useCallback(() => {
    clearAuthToken();
    setCurrentUser(null);
    setUserState('');
    setAccounts([]);
    setUsers([]);
    router.push('/login');
  }, [router]);

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

        // Clamp saved preferences to the current, server-verified organization.
        const selectedAccount = authorizedAccount(userProfile, localStorage.getItem('karix_account'));
        setAccountState(selectedAccount);
        localStorage.setItem('karix_account', selectedAccount);

        const savedChannel = localStorage.getItem('karix_channel') as Channel;
        if (selectedAccount === 'apparel') {
          setChannelState('rcs');
        } else if (savedChannel === 'whatsapp' || savedChannel === 'rcs' || savedChannel === 'sms') {
          setChannelState(savedChannel);
        }

        await refreshAccounts();
        if (window.location.pathname === '/login') router.push('/');
      } catch (err) {
        console.warn('Session expired or invalid token:', err);
        clearAuthToken();
        setCurrentUser(null);
        setAccounts([]);
        setUsers([]);
        if (!isAuthPage) {
          router.push('/login');
        }
      } finally {
        setAuthLoading(false);
        setMounted(true);
      }
    }

    checkAuth();

    return () => {
      ignore = true;
    };
  }, [router, refreshAccounts]);

  const setAccount = (newAccount: Account) => {
    const cleanAccount = newAccount.toLowerCase();
    if (!canAccessAccount(currentUser, cleanAccount)) {
      alert('Access denied: This account is outside your authorized organization.');
      return;
    }
    if (cleanAccount !== 'all' && accounts.length > 0 && !accounts.some((a) => a.id.toLowerCase() === cleanAccount)) {
      alert(`Access Denied: You do not have permission to access ${newAccount.toUpperCase()}.`);
      return;
    }
    setAccountState(cleanAccount);
    try {
      localStorage.setItem('karix_account', cleanAccount);
    } catch {}
    if (cleanAccount === 'apparel') {
      setChannelState('rcs');
      try {
        localStorage.setItem('karix_channel', 'rcs');
      } catch {}
    }
  };

  const setChannel = (newChannel: Channel) => {
    if (account === 'apparel') {
      setChannelState('rcs');
      return;
    }
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
      if (target === 'all') return 'All Accounts';
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
