'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useApp } from '@/lib/context';
import { canUseApparelAttribution } from '@/lib/apparel-attribution';

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
    href: '/moengage-campaigns',
    label: 'MoEngage Campaigns',
    subtitle: 'WhatsApp, Email & Push builder',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        <path d="M8 10h.01" />
        <path d="M12 10h.01" />
        <path d="M16 10h.01" />
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
    href: '/briefs',
    label: 'Jira Briefs',
    icon: (
      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 4h12v12H4z" />
        <path d="M4 9h12" />
        <path d="M9 4v12" />
      </svg>
    ),
  },
  {
    href: '/work-management',
    label: 'Work Management',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
        <path d="m9 16 2 2 4-4" />
      </svg>
    ),
  },
  {
    href: '/moengage-ops',
    label: 'MoEngage Ops',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 3v18h18" />
        <path d="M18 17V9" />
        <path d="M13 17V5" />
        <path d="M8 17v-3" />
      </svg>
    ),
  },
  {
    href: '/apparel/attribution',
    label: 'Apparel Attribution',
    subtitle: 'WhatsApp, SMS & RCS reporting',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 3v18h18" />
        <path d="M7 17v-4M12 17V7M17 17v-7" />
      </svg>
    ),
  },
  {
    href: '/tata/click-count',
    label: 'Tata Click Counts',
    subtitle: 'Unique clicks across five channels',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 3v18h18" />
        <path d="M7 17v-4M12 17V7M17 17v-7" />
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
  const [mobileOpen, setMobileOpen] = useState(false);
  useEffect(() => { setMobileOpen(false); }, [pathname]);
  useEffect(() => {
    if (mobileOpen) document.getElementById('workspace-navigation-close')?.focus();
  }, [mobileOpen]);
  const {
    account,
    user,
    currentUser,
    logout,
  } = useApp();
  const canViewAll = currentUser?.role === 'superadmin';
  const canViewTataClickCounts = Boolean(currentUser && (
    currentUser.tenant_id === 'tata' ||
    (canViewAll && ['all', 'tata', 'tcl_promo', 'tcl_trans', 'tchfl', 'wealth', 'moneyfy'].includes(account))
  ));
  const canViewJira = Boolean(currentUser && (currentUser.tenant_id === 'tata' ||
    (canViewAll && ['all', 'tata', 'tcl_promo', 'tcl_trans', 'tchfl', 'wealth', 'moneyfy'].includes(account))));
  const primaryRoutes = canViewJira ? ['/briefs', '/', '/activity', '/settings'] : ['/', '/submit', '/activity', '/settings'];
  const visibleLinks = links.filter((link) => {
    if (link.href === '/briefs' && !canViewJira) return false;
    if (link.href === '/apparel/attribution' && !canUseApparelAttribution(currentUser, account)) return false;
    if (link.href === '/tata/click-count' && !canViewTataClickCounts) return false;
    if (link.href === '/moengage-ops' && currentUser?.tenant_id !== 'tata' && !canViewAll) return false;
    return true;
  });

  if (pathname === '/login' || pathname === '/signup') {
    return null;
  }

  return (
    <>
    <header className="workspace-chrome md:hidden sticky top-0 z-40 h-14 flex items-center justify-between gap-3 border-b border-gray-200 px-4">
      <div className="flex items-center gap-2.5 min-w-0">
        <img src="/logo.svg" alt="Attributics" className="w-7 h-7 rounded-lg shadow-xs shrink-0" />
        <span className="font-semibold tracking-tight text-gray-900 truncate">Attributics</span>
      </div>
      <button id="workspace-menu-toggle" type="button" aria-controls="workspace-navigation" aria-expanded={mobileOpen} onClick={() => setMobileOpen((open) => !open)} className="shrink-0 rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-semibold text-gray-700 focus-visible:ring-2 focus-visible:ring-blue-500">Menu</button>
    </header>
    {mobileOpen && <button type="button" aria-label="Close navigation" onClick={() => { setMobileOpen(false); document.getElementById('workspace-menu-toggle')?.focus(); }} className="md:hidden fixed inset-0 z-40 bg-black/30" />}
    <aside id="workspace-navigation" aria-label="Workspace navigation" role={mobileOpen ? 'dialog' : undefined} aria-modal={mobileOpen || undefined} onKeyDown={(event) => {
      if (event.key === 'Escape') {
        setMobileOpen(false);
        document.getElementById('workspace-menu-toggle')?.focus();
      }
      if (mobileOpen && event.key === 'Tab') {
        const items = event.currentTarget.querySelectorAll<HTMLElement>('a[href], button:not([disabled])');
        const first = items[0];
        const last = items[items.length - 1];
        if ((event.shiftKey && document.activeElement === first) || (!event.shiftKey && document.activeElement === last)) {
          event.preventDefault();
          (event.shiftKey ? last : first)?.focus();
        }
      }
    }} className={`fixed top-0 left-0 w-64 h-dvh overflow-y-auto bg-[#f4f4f1] border-r border-gray-200 flex-col z-50 md:z-30 ${mobileOpen ? 'flex' : 'hidden md:flex'}`}>
      <button id="workspace-navigation-close" type="button" onClick={() => { setMobileOpen(false); document.getElementById('workspace-menu-toggle')?.focus(); }} className="md:hidden self-end rounded-lg border border-gray-200 m-3 px-3 py-2 text-sm font-medium">Close navigation</button>
      <div className="px-6 py-6">
        <div className="flex items-center gap-2.5">
          <img src="/logo.svg" alt="" className="w-8 h-8 rounded-lg shrink-0" />
          <div>
            <div className="text-base font-semibold tracking-tight text-gray-900 leading-tight">Attributics</div>
            <div className="text-xs text-gray-500 leading-relaxed mt-0.5">Campaign operations</div>
          </div>
        </div>
      </div>


      {/* Navigation Links */}
      <nav className="flex-1 px-3 pb-5 space-y-4" aria-label="Main navigation">
        {[primaryRoutes.flatMap((href) => visibleLinks.filter((link) => link.href === href)),
          visibleLinks.filter((link) => !primaryRoutes.includes(link.href))].map((group, index) => {
          const items = group.map((link) => {
            const href = link.href === '/moengage-campaigns' && canUseApparelAttribution(currentUser, account) ? '/apparel/campaigns' : link.href;
            const active = href === '/' ? pathname === '/' : pathname.startsWith(href);
            return (
              <Link key={link.href} href={href} onClick={() => setMobileOpen(false)} aria-current={active ? 'page' : undefined}
                className={`workspace-nav-link flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${active ? 'font-semibold bg-white text-blue-800 shadow-sm' : index === 0 ? 'font-medium text-gray-800 hover:bg-white/70' : 'font-normal text-gray-600 hover:bg-white/70 hover:text-gray-900'}`}>
                <span aria-hidden="true" className={`shrink-0 ${active ? 'text-blue-700' : 'text-gray-500'}`}>{link.icon}</span>
                <span>{link.href === '/submit' ? 'Upload templates' : link.label}</span>
              </Link>
            );
          });
          return index === 0 ? <div key="primary" className="space-y-1">{items}</div> : (
            <div key="secondary" className="space-y-1 border-t border-gray-200 pt-3">
              {items}
            </div>
          );
        })}

        {/* AI Copilot Trigger */}
        <button
          type="button"
          onClick={() => window.dispatchEvent(new CustomEvent('toggle-copilot'))}
          className="w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-100 transition-colors group text-left mt-2"
        >
          <div className="flex items-center gap-3">
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m10 2 2.3 5.7L18 10l-5.7 2.3L10 18l-2.3-5.7L2 10l5.7-2.3L10 2Z" /></svg>
            <span>AI Copilot</span>
          </div>
          <kbd className="px-1.5 py-0.5 bg-white text-xs text-gray-500 rounded font-mono border border-gray-200">
            ⌘K
          </kbd>
        </button>
      </nav>

      {/* Footer Info */}
      {/* Active User Card & Target */}
      <div className="p-4 border-t border-gray-200 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-gray-200 text-gray-700 font-semibold text-sm flex items-center justify-center shrink-0">
              {(currentUser?.name || user || 'U').charAt(0).toUpperCase()}
            </div>
            <div className="min-w-0">
              <p className="text-xs font-semibold text-gray-900 truncate">
                {currentUser?.name || user || 'Operator'}
              </p>
              <p className="text-xs text-gray-500 truncate">
                {currentUser?.email || (currentUser?.role ? `${currentUser.role.toUpperCase()}` : 'Operator')}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={logout}
            className="text-xs font-medium text-gray-600 hover:text-red-700 hover:bg-red-50 px-2 py-2 rounded-lg transition-colors shrink-0"
            title="Sign out of account"
          >
            Sign out
          </button>
        </div>

        <div className="flex items-center justify-between text-xs text-gray-500 pt-2 border-t border-gray-200">
          <span>Workspace</span>
          <span className="font-mono font-medium text-gray-700 uppercase text-xs">
            {currentUser?.tenant_id || account}
          </span>
        </div>
      </div>
    </aside>
    </>
  );
}
