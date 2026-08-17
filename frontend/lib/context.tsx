'use client';

import React, { createContext, useContext, useEffect, useState } from 'react';
import type { Account, Channel } from './api';

type AppContextType = {
  account: Account;
  setAccount: (account: Account) => void;
  channel: Channel;
  setChannel: (channel: Channel) => void;
};

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [account, setAccountState] = useState<Account>('bajaj');
  const [channel, setChannelState] = useState<Channel>('whatsapp');
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
    } catch {
      // localStorage may fail in private mode
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

  return (
    <AppContext.Provider value={{ account, setAccount, channel, setChannel }}>
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
