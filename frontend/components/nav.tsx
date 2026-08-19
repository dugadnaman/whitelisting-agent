'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useApp } from '@/lib/context';
import type { Account, Channel } from '@/lib/api';

const links = [
  {
    href: '/',
    label: 'Dashboard',
    icon: (
      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="2" width="7" height="7" rx="1.5" />
        <rect x="11" y="2" width="7" height="7" rx="1.5" />
        <rect x="2" y="11" width="7" height="7" rx="1.5" />
        <rect x="11" y="11" width="7" height="7" rx="1.5" />
      </svg>
    ),
  },
  {
    href: '/submit',
    label: 'Submit Templates',
    icon: (
      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10 3v10M6 9l4 4 4-4M3 15h14" />
      </svg>
    ),
  },
  {
    href: '/activity',
    label: 'Activity Logs',
    icon: (
      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="10" cy="10" r="7" />
        <polyline points="10 6 10 10 13 13" />
      </svg>
    ),
  },
  {
    href: '/settings',
    label: 'Settings',
    icon: (
      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="10" cy="10" r="3" />
        <path d="M16.24 7.76a6 6 0 0 1 0 4.48m-2.48 2.48a6 6 0 0 1-4.48 0m-2.48-2.48a6 6 0 0 1 0-4.48m2.48-2.48a6 6 0 0 1 4.48 0" />
      </svg>
    ),
  },
];

export default function Nav() {
  const pathname = usePathname();
  const { account, setAccount, channel, setChannel, user, setUser, accounts, getAccountLabel } = useApp();
  const [isEditingUser, setIsEditingUser] = useState(false);
  const [userNameInput, setUserNameInput] = useState('');

  const handleSaveUser = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (userNameInput.trim()) {
      setUser(userNameInput.trim());
    }
    setIsEditingUser(false);
  };
  return (
    <aside className="fixed top-0 left-0 w-64 h-screen bg-white border-r border-gray-200 flex flex-col z-30">
      {/* Brand Header */}
      <div className="p-5 border-b border-gray-100">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-white font-bold text-base shadow-sm">
            K
          </div>
          <div>
            <div className="text-base font-bold text-gray-900 leading-tight">Karix</div>
            <div className="text-[11px] text-gray-400 font-medium leading-none mt-0.5">Template Whitelisting</div>
          </div>
        </div>
      </div>

      {/* Account & Channel Selectors */}
      <div className="p-4 bg-gray-50/70 border-b border-gray-200/80 space-y-2.5">
        {/* Account Selector */}
        <div>
          <label className="block text-[11px] font-semibold uppercase tracking-wider text-gray-500 mb-1">
            Account
          </label>
          <div className="relative">
            <select
              value={account}
              onChange={(e) => setAccount(e.target.value as Account)}
              className="w-full appearance-none bg-white border border-gray-300 rounded-lg px-3 py-1.5 pr-8 text-xs font-semibold text-gray-800 shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none cursor-pointer transition-colors"
            >
              {accounts.map((acc) => (
                <option key={acc.id} value={acc.id}>
                  {acc.name}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-gray-500">
              <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
            </div>
          </div>
        </div>

        {/* Channel Selector */}
        <div>
          <label className="block text-[11px] font-semibold uppercase tracking-wider text-gray-500 mb-1">
            Channel
          </label>
          <div className="relative">
            <select
              value={channel}
              onChange={(e) => setChannel(e.target.value as Channel)}
              className="w-full appearance-none bg-white border border-gray-300 rounded-lg px-3 py-1.5 pr-8 text-xs font-semibold text-gray-800 shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none cursor-pointer transition-colors"
            >
              <option value="whatsapp">WhatsApp</option>
              <option value="rcs">RCS (DLT)</option>
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-gray-500">
              <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
            </div>
          </div>
        </div>

        {/* Active Context Badge */}
        <div className="flex items-center justify-between pt-1">
          <span className="text-[11px] text-gray-500 font-medium">Active:</span>
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold ${
              channel === 'whatsapp'
                ? 'bg-emerald-100 text-emerald-800'
                : 'bg-blue-100 text-blue-800'
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full mr-1.5 ${
                channel === 'whatsapp' ? 'bg-emerald-500' : 'bg-blue-500'
              }`}
            />
            {getAccountLabel(account)} &bull; {channel === 'whatsapp' ? 'WhatsApp' : 'RCS'}
          </span>
        </div>
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {links.map((link) => {
          const active =
            link.href === '/'
              ? pathname === '/'
              : pathname.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={
                active
                  ? 'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-semibold bg-blue-50 text-blue-700 shadow-xs'
                  : 'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors'
              }
            >
              {link.icon}
              {link.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer Info */}
      {/* Active User Card & Target */}
      <div className="p-3.5 border-t border-gray-200/80 bg-gray-50/60 space-y-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-7 h-7 rounded-full bg-blue-600 text-white font-bold text-xs flex items-center justify-center shrink-0 shadow-xs">
              {(user || 'U').charAt(0).toUpperCase()}
            </div>
            <div className="min-w-0">
              <p className="text-[11px] font-semibold text-gray-900 truncate">
                {user || 'Anonymous'}
              </p>
              <p className="text-[10px] text-gray-400 truncate">Active Operator</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              setUserNameInput(user);
              setIsEditingUser(true);
            }}
            className="text-[11px] font-semibold text-blue-600 hover:text-blue-800 transition-colors p-1"
            title="Switch or rename user"
          >
            Switch
          </button>
        </div>

        {/* User Edit Modal / Popover */}
        {isEditingUser && (
          <div className="p-2.5 bg-white border border-blue-200 rounded-lg shadow-sm space-y-2">
            <p className="text-[11px] font-semibold text-gray-700">Set Your Name / Identity:</p>
            <form onSubmit={handleSaveUser} className="space-y-1.5">
              <input
                type="text"
                value={userNameInput}
                onChange={(e) => setUserNameInput(e.target.value)}
                placeholder="e.g. Namann, M., Team..."
                className="w-full text-xs px-2.5 py-1.5 border border-gray-300 rounded focus:ring-1 focus:ring-blue-500 focus:outline-none"
                autoFocus
              />
              <div className="flex items-center justify-end gap-1.5">
                <button
                  type="button"
                  onClick={() => setIsEditingUser(false)}
                  className="text-[10px] font-semibold text-gray-500 px-2 py-1 hover:bg-gray-100 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="text-[10px] font-semibold text-white bg-blue-600 hover:bg-blue-700 px-2.5 py-1 rounded"
                >
                  Save
                </button>
              </div>
            </form>
          </div>
        )}

        <div className="flex items-center justify-between text-[11px] text-gray-400 pt-1 border-t border-gray-200/60">
          <span>Target</span>
          <span className="font-mono font-semibold text-gray-700 uppercase">
            {account} / {channel}
          </span>
        </div>
      </div>
    </aside>
  );
}
