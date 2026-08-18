'use client';

import React, { createContext, useContext, useEffect, useState } from 'react';
import type { Account, Channel } from './api';

type AppContextType = {
  account: Account;
  setAccount: (account: Account) => void;
  channel: Channel;
  setChannel: (channel: Channel) => void;
  user: string;
  setUser: (user: string) => void;
};

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [account, setAccountState] = useState<Account>('bajaj');
  const [channel, setChannelState] = useState<Channel>('whatsapp');
  const [user, setUserState] = useState<string>('Namann');
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    try {
      const savedAccount = localStorage.getItem('karix_account') as Account;
      const savedChannel = localStorage.getItem('karix_channel') as Channel;
      if (savedAccount === 'bajaj' || savedAccount === 'tata') {
        setAccountState(savedAccount);
      }
      if (savedChannel === 'whatsapp' || savedChannel === 'rcs') {
        setChannelState(savedChannel);
      }
      const savedUser = localStorage.getItem('karix_user');
      if (savedUser && savedUser.trim()) {
        setUserState(savedUser.trim());
      }
      // localStorage may fail in private mode
    } catch {
      // ignore localStorage failures (e.g. private mode)
    }
    setMounted(true);
  }, []);

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
  return (
    <AppContext.Provider value={{ account, setAccount, channel, setChannel, user, setUser }}>
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
